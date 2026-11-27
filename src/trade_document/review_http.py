import html, json, time
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from .storage import database, current
from .approval import Proof, Binding, Review


async def review_endpoint(scope, receive, send, person, rid):
    from .server import generate_document
    from .remote import get_file_download

    with database() as db:
        row = db.execute(
            "SELECT r.*,b.body FROM requests r JOIN bindings b USING(id) WHERE r.id=?",
            (rid,),
        ).fetchone()
        if row:
            snap = current(db, row["order_id"])
            binding = Binding.model_validate_json(row["body"])
            packet = Review(request_id=rid, snapshot=snap, binding=binding)
    if not row:
        return await JSONResponse({"error": "Unknown review"}, 404)(
            scope, receive, send
        )
    if binding.expires <= time.time() or snap.version != row["version"]:
        return await JSONResponse({"error": "Stale review"}, 409)(scope, receive, send)
    if scope["method"] == "POST":
        if person.role == "viewer":
            return await JSONResponse({"error": "Review role required"}, 403)(
                scope, receive, send
            )
        try:
            data = bytearray()
            async for chunk in Request(scope, receive).stream():
                data.extend(chunk)
                if len(data) > 4096:
                    raise ValueError("Oversized proof")
            proof = Proof.model_validate_json(bytes(data))
            if proof.reviewer != person.actor:
                raise ValueError("Reviewer identity mismatch")
            result = generate_document(rid, proof)
            response = JSONResponse(
                {"artifact_id": result.artifact_id, "audit": result.audit.model_dump()}
            )
        except ValueError as e:
            response = JSONResponse({"error": str(e)}, 403)
    elif scope["method"] == "GET":
        links = [
            get_file_download(binding.preview_id, n).path
            for n in ("document.xlsx", "document.pdf")
        ]
        excerpt = html.escape(
            json.dumps(packet.model_dump(mode="json"), indent=2, ensure_ascii=False)
        )
        response = HTMLResponse(
            f'<!doctype html><html lang="en"><meta charset="utf-8"><title>Review trade document</title><main><h1>Review {html.escape(snap.order.number or "")}</h1><p><a href="{links[0]}">Excel preview</a> · <a href="{links[1]}">PDF preview</a></p><p>Verify these files with trade-doc-sign and return the signed proof to this URL by authenticated POST.</p><pre>{excerpt}</pre></main></html>',
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            },
        )
    else:
        response = JSONResponse({"error": "GET or POST required"}, 405)
    return await response(scope, receive, send)
