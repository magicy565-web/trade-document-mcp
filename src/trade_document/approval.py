from .access import registry
import base64
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
    from .beneficiaries import verified
    from .rules import evaluate

    rules, regional = evaluate(db, snap.order)
    errors = issues(snap.order, verified(db)) + [f.resolution for f in regional]
    if errors:
        raise ValueError(" | ".join(errors))
    duplicate = db.execute(
        """SELECT 1 FROM artifacts a JOIN versions v ON a.order_id=v.id AND a.version=v.version
        WHERE a.preview=0 AND a.order_id<>? AND json_extract(v.body,'$.kind')=? AND json_extract(v.body,'$.number')=?""",
        (snap.order_id, snap.order.kind, snap.order.number),
    ).fetchone()
    if duplicate:
        raise ValueError("Document number already issued")
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
    preview_rules = db.execute(
        "SELECT digest FROM preview_rules WHERE artifact=?", (row["id"],)
    ).fetchone()
    if not preview_rules or preview_rules[0] != rules:
        raise ValueError("Rules changed; preview again")
    binding = Binding(
        preview_id=row["id"],
        workbook=row["workbook"],
        pdf=row["pdf"],
        template=snap.order.template_id or "builtin-v2/" + snap.order.kind,
        rules=rules,
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
    from .beneficiaries import verified
    from .rules import evaluate

    rules, regional = evaluate(db, snap.order)
    if (
        regional
        or binding.expires <= time.time()
        or binding.rules != rules
        or issues(snap.order, verified(db))
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
    key = registry("TRADE_DOC_REVIEWERS").get(proof.reviewer)
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
