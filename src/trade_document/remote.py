"""Authenticated single-worker Streamable HTTP with tenant-scoped artifact handles."""

import hashlib, json, os, re, secrets, time
from collections import deque
from pathlib import Path
from starlette.responses import JSONResponse, FileResponse
from starlette.datastructures import Headers
from .access import Identity, identity
from .model import Model, Text
from .storage import database, home, sha


class Download(Model):
    path: str
    expires: int


def get_file_download(artifact_id: Text, file: Text) -> Download:
    with database() as db:
        row = db.execute(
            "SELECT * FROM artifacts WHERE id=?", (artifact_id,)
        ).fetchone()
        if row and file in ("document.pdf", "document.xlsx"):
            path = home() / "artifacts" / artifact_id / file
            digest = row["pdf" if file.endswith("pdf") else "workbook"]
        else:
            from .shipments import Bundle, Packet

            saved = db.execute(
                "SELECT body FROM shipment_issues WHERE id=?", (artifact_id,)
            ).fetchone()
            review = db.execute(
                "SELECT body FROM ship_reviews WHERE id=?", (artifact_id,)
            ).fetchone()
            if saved:
                bundle = Bundle.model_validate_json(saved[0])
                digest = bundle.hashes.get(file)
                path = next(
                    (Path(p) for p in bundle.files if Path(p).name == file), None
                )
            elif review:
                digest = Packet.model_validate_json(review[0]).preview_hashes.get(file)
                path = home() / "shipping" / artifact_id / file if digest else None
            else:
                raise ValueError("Unknown artifact")
            if not path or not digest:
                raise ValueError("Unknown file")
        if not path.is_file() or sha(path.read_bytes()) != digest:
            raise ValueError("Archive integrity failure")
        token = secrets.token_urlsafe(32)
        expires = int(time.time()) + 180
        db.execute("DELETE FROM downloads WHERE expires<=?", (int(time.time()),))
        db.execute(
            "INSERT INTO downloads VALUES(?,?,?,?)",
            (sha(token.encode()), str(path.relative_to(home())), digest, expires),
        )
        return Download(path="/files/" + token, expires=expires)


class Status(Model):
    api_version: str
    orders: int
    issued: int
    failed_calls: int


def get_service_status() -> Status:
    with database() as db:
        return Status(
            api_version="0.5",
            orders=db.execute("SELECT COUNT(DISTINCT id) FROM versions").fetchone()[0],
            issued=db.execute(
                "SELECT COUNT(*) FROM artifacts WHERE preview=0"
            ).fetchone()[0],
            failed_calls=db.execute(
                "SELECT COUNT(*) FROM events WHERE outcome='error'"
            ).fetchone()[0],
        )


def create_app():
    from .server import mcp

    configured = json.loads(os.environ.get("TRADE_HTTP_IDENTITIES", "{}"))
    people = {k: Identity.model_validate(v) for k, v in configured.items()}
    if not people or any(
        not re.fullmatch("[a-f0-9]{64}", k)
        or not re.fullmatch("[a-z0-9][a-z0-9_-]{0,62}", p.tenant)
        or p.role not in ("viewer", "editor", "admin")
        for k, p in people.items()
    ):
        raise ValueError(
            "Configure hashed credentials with explicit tenant, role and expiry"
        )
    app = mcp.streamable_http_app()
    requests = {k: deque() for k in people}
    limit = int(os.environ.get("TRADE_HTTP_RATE", "240"))

    async def gateway(scope, receive, send):
        if scope["type"] != "http":
            return await app(scope, receive, send)
        auth = Headers(scope=scope).get("authorization", "")
        scheme, _, token = auth.partition(" ")
        key = hashlib.sha256(token.encode()).hexdigest()
        person = people.get(key)
        if scheme.lower() != "bearer" or not person or person.expires <= time.time():
            return await JSONResponse(
                {"error": "Valid bearer credential required"},
                401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
        now = time.monotonic()
        history = requests[key]
        while history and history[0] <= now - 60:
            history.popleft()
        if len(history) >= limit:
            return await JSONResponse({"error": "Rate limit"}, 429)(
                scope, receive, send
            )
        history.append(now)
        scope_token = identity.set(person)
        try:
            path = scope["path"]
            if re.fullmatch(r"/reviews/[0-9a-f]{32}", path):
                from .review_http import review_endpoint

                return await review_endpoint(
                    scope, receive, send, person, path.split("/")[-1]
                )
            if path.startswith("/files/"):
                with database() as db:
                    row = db.execute(
                        "SELECT * FROM downloads WHERE id=? AND expires>?",
                        (sha(path[7:].encode()), int(time.time())),
                    ).fetchone()
                if not row:
                    return await JSONResponse(
                        {"error": "Unknown or expired file"}, 404
                    )(scope, receive, send)
                target = home() / row["path"]
                if not target.is_file() or sha(target.read_bytes()) != row["digest"]:
                    return await JSONResponse({"error": "Integrity check failed"}, 409)(
                        scope, receive, send
                    )
                return await FileResponse(
                    target, filename=target.name, headers={"Cache-Control": "no-store"}
                )(scope, receive, send)
            return await app(scope, receive, send)
        finally:
            identity.reset(scope_token)

    return gateway


def main():
    import uvicorn

    uvicorn.run(
        create_app(),
        host="127.0.0.1",
        port=int(os.environ.get("TRADE_HTTP_PORT", "8000")),
    )
