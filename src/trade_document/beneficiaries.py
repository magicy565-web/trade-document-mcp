"""Separate finance verification and authorization for beneficiary changes."""

from typing import Annotated, Literal
from pydantic import Field
from .access import registry
from .model import Model, Text
from .approval import Proof
from .mapping import verify
from .storage import database, canonical, sha


class Change(Model):
    purpose: Literal["trade.beneficiary.v1"] = "trade.beneficiary.v1"
    reference: Text
    version: Annotated[int, Field(gt=0)]
    instructions: Text
    verification_record: Text
    status: Literal["active", "revoked"]


class Receipt(Model):
    reference: str
    version: int
    digest: str


def verified(db):
    refs = dict(registry("TRADE_DOC_BENEFICIARIES"))
    for row in db.execute(
        "SELECT b.* FROM beneficiaries b WHERE version=(SELECT MAX(version) FROM beneficiaries WHERE ref=b.ref)"
    ):
        change = Change.model_validate_json(row["body"])
        if change.status == "active":
            refs[change.reference] = change.instructions
        else:
            refs.pop(change.reference, None)
    return refs


def change_beneficiary(change: Change, verifier: Proof, authorizer: Proof) -> Receipt:
    payload = change.model_dump(mode="json")
    first = registry("TRADE_FINANCE_VERIFIERS").get(verifier.reviewer)
    second = registry("TRADE_FINANCE_AUTHORIZERS").get(authorizer.reviewer)
    if first == second or verifier.reviewer == authorizer.reviewer:
        raise ValueError("Two independent finance identities required")
    verify("TRADE_FINANCE_VERIFIERS", payload, verifier)
    verify("TRADE_FINANCE_AUTHORIZERS", payload, authorizer)
    digest = sha(canonical(payload))
    with database() as db:
        latest = (
            db.execute(
                "SELECT MAX(version) FROM beneficiaries WHERE ref=?",
                (change.reference,),
            ).fetchone()[0]
            or 0
        )
        if change.version != latest + 1:
            raise ValueError("Stale beneficiary change")
        db.execute(
            "INSERT INTO beneficiaries VALUES(?,?,?,?,?)",
            (
                change.reference,
                change.version,
                change.model_dump_json(),
                verifier.model_dump_json(),
                authorizer.model_dump_json(),
            ),
        )
    return Receipt(reference=change.reference, version=change.version, digest=digest)
