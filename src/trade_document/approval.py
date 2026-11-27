import base64
import json
import os
import time
from uuid import uuid4
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
from .model import Model, issues
from .storage import Snapshot, canonical, current, home, sha


class Binding(Model):
    preview_id: str
    workbook: str
    pdf: str
    template: str
    rules: str
    expires: int


class Review(Model):
    binding: Binding
    request_id: str
    snapshot: Snapshot


class Proof(Model):
    reviewer: str
    signature: str


def request(db, snap):
    errors = issues(snap.order)
    if errors:
        raise ValueError(" | ".join(errors))
    rid = uuid4().hex
    db.execute(
        "INSERT INTO requests(id,order_id,version,digest) VALUES(?,?,?,?)",
        (rid, snap.order_id, snap.version, snap.digest),
    )
    row = db.execute(
        "SELECT * FROM artifacts WHERE order_id=? AND version=? AND preview=1 ORDER BY rowid DESC LIMIT 1",
        (snap.order_id, snap.version),
    ).fetchone()
    if not row:
        raise ValueError("Preview required")
    binding = Binding(
        preview_id=row["id"],
        workbook=row["workbook"],
        pdf=row["pdf"],
        template=snap.order.template_id or "builtin-v2/" + snap.order.kind,
        rules="commercial-v2",
        expires=int(time.time()) + 3600,
    )
    db.execute("INSERT INTO bindings VALUES(?,?)", (rid, binding.model_dump_json()))
    return Review(request_id=rid, snapshot=snap, binding=binding)


def message(review, reviewer):
    s = review.snapshot
    return canonical(
        [
            "trade-document-approval/v1",
            review.request_id,
            s.order_id,
            s.version,
            s.digest,
            review.binding.model_dump(),
            reviewer,
        ]
    )


def authorize(db, rid, proof):
    row = db.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    if not row:
        raise ValueError("Unknown approval request")
    snap = current(db, row["order_id"])
    if (snap.version, snap.digest) != (row["version"], row["digest"]):
        raise ValueError("Approval invalidated by order revision")
    record = db.execute("SELECT body FROM bindings WHERE id=?", (rid,)).fetchone()
    if not record:
        raise ValueError("Legacy approval requires new preview and review")
    binding = Binding.model_validate_json(record[0])
    if (
        binding.expires <= time.time()
        or binding.rules != "commercial-v2"
        or issues(snap.order)
    ):
        raise ValueError("Expired or invalid approval")
    root = home() / "artifacts" / binding.preview_id
    for name, digest in [
        ("document.xlsx", binding.workbook),
        ("document.pdf", binding.pdf),
    ]:
        path = root / name
        if not path.is_file() or sha(path.read_bytes()) != digest:
            raise ValueError("Preview changed")
    key = json.loads(os.environ.get("TRADE_DOC_REVIEWERS", "{}")).get(proof.reviewer)
    if not key:
        raise ValueError("Unregistered reviewer")
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key, validate=True)).verify(
            base64.b64decode(proof.signature, validate=True),
            message(
                Review(request_id=rid, snapshot=snap, binding=binding), proof.reviewer
            ),
        )
    except (InvalidSignature, ValueError) as e:
        raise ValueError("Invalid human approval signature") from e
    db.execute(
        "UPDATE requests SET reviewer=?,proof=? WHERE id=?",
        (proof.reviewer, proof.signature, rid),
    )
    return snap
