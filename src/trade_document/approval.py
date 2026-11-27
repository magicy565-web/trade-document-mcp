import base64
import json
import os
from uuid import uuid4
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
from .model import Model, issues
from .storage import Snapshot, canonical, current


class Review(Model):
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
    return Review(request_id=rid, snapshot=snap)


def message(review, reviewer):
    s = review.snapshot
    return canonical(
        [
            "trade-document-approval/v1",
            review.request_id,
            s.order_id,
            s.version,
            s.digest,
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
    key = json.loads(os.environ.get("TRADE_DOC_REVIEWERS", "{}")).get(proof.reviewer)
    if not key:
        raise ValueError("Unregistered reviewer")
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key, validate=True)).verify(
            base64.b64decode(proof.signature, validate=True),
            message(Review(request_id=rid, snapshot=snap), proof.reviewer),
        )
    except (InvalidSignature, ValueError) as e:
        raise ValueError("Invalid human approval signature") from e
    db.execute(
        "UPDATE requests SET reviewer=?,proof=? WHERE id=?",
        (proof.reviewer, proof.signature, rid),
    )
    return snap
