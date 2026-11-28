import base64
import json
import os
import time
from uuid import uuid4
from importlib.resources import files
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
    beneficiary_version: int | None = None


class Review(Model):
    binding: Binding
    request_id: str
    snapshot: Snapshot


class Proof(Model):
    reviewer: str
    signature: str


def basis():
    package = files("trade_document")
    return sha(
        canonical(
            {
                name: sha(package.joinpath(name).read_bytes())
                for name in ("model.py", "render.py", "audit.py")
            }
        )
    )


def check_number(db, snap):
    duplicate = db.execute(
        """SELECT 1 FROM artifacts a
        JOIN versions v ON v.id=a.order_id AND v.version=a.version
        WHERE a.preview=0 AND a.order_id<>?
          AND json_extract(v.body, '$.kind')=? AND json_extract(v.body, '$.number')=?""",
        (snap.order_id, snap.order.kind, snap.order.number),
    ).fetchone()
    if duplicate:
        raise ValueError("Document number already issued for this document type")


def check_preview(binding):
    root = home() / "artifacts" / binding.preview_id
    for name, digest in (
        ("document.xlsx", binding.workbook),
        ("document.pdf", binding.pdf),
    ):
        path = root / name
        if not path.is_file() or sha(path.read_bytes()) != digest:
            raise ValueError("Preview changed")


def finance_basis(db, order):
    if order.beneficiary_ref is None:
        return None
    row = db.execute(
        "SELECT MAX(version) FROM beneficiaries WHERE ref=?", (order.beneficiary_ref,)
    ).fetchone()
    return row[0]


def template_version(db, order):
    if order.template_id is None:
        return "builtin/" + order.kind
    row = db.execute(
        "SELECT content FROM templates WHERE id=?", (order.template_id,)
    ).fetchone()
    if not row or sha(row[0]) != order.template_id:
        raise ValueError("Template missing or changed")
    return order.template_id


def request(db, snap):
    from .finance import registered

    errors = issues(snap.order, registered(db))
    if errors:
        raise ValueError(" | ".join(errors))
    check_number(db, snap)
    rid = uuid4().hex
    db.execute(
        "INSERT INTO requests(id,order_id,version,digest) VALUES(?,?,?,?)",
        (rid, snap.order_id, snap.version, snap.digest),
    )
    row = db.execute(
        "SELECT a.*, b.digest AS basis FROM artifacts a LEFT JOIN preview_basis b ON b.artifact=a.id WHERE a.order_id=? AND a.version=? AND a.preview=1 ORDER BY a.rowid DESC LIMIT 1",
        (snap.order_id, snap.version),
    ).fetchone()
    if not row:
        raise ValueError("Preview required")
    if row["basis"] != basis():
        raise ValueError("Document rules or layout changed; preview again")
    binding = Binding(
        preview_id=row["id"],
        workbook=row["workbook"],
        pdf=row["pdf"],
        template=template_version(db, snap.order),
        rules=row["basis"],
        expires=int(time.time()) + 3600,
        beneficiary_version=finance_basis(db, snap.order),
    )
    check_preview(binding)
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
    from .finance import registered

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
        or binding.rules != basis()
        or binding.template != template_version(db, snap.order)
        or binding.beneficiary_version != finance_basis(db, snap.order)
        or issues(snap.order, registered(db))
    ):
        raise ValueError("Expired or invalid approval")
    check_preview(binding)
    check_number(db, snap)
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
