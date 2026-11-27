"""Tenant policy registry. Only signed, dated, independently reviewed rules can block."""

from datetime import date, datetime, timezone
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .model import Model, Text
from .storage import database, canonical, sha
from .knowledge import source, Finding
from .mapping import verify
from .approval import Proof


class Rule(Model):
    purpose: Literal["trade.rule.v1"] = "trade.rule.v1"
    rule_id: Text
    version: Annotated[int, Field(gt=0)]
    region: Annotated[str, Field(pattern=r"^(GLOBAL|[A-Z]{2})$")]
    kinds: list[
        Literal["standard-pi", "product-image-pi", "sample-pi", "sample-order"]
    ] = Field(min_length=1)
    required_field: Literal[
        "valid_until",
        "ship_to",
        "seller_address",
        "buyer_address",
        "purchase_order",
        "trade_term",
        "acceptance_criteria",
        "origin",
    ]
    source_id: Text
    locator: Text
    interpretation: Text
    resolution: Text
    effective_from: date
    effective_through: date
    state: Literal["active", "withdrawn"]

    @model_validator(mode="after")
    def dates(self):
        if self.effective_through < self.effective_from:
            raise ValueError("Invalid applicability period")
        return self


class Registration(Model):
    digest: str
    version: int


def register_reviewed_rule(rule: Rule, first: Proof, second: Proof) -> Registration:
    s = source(rule.source_id)
    if s.authority not in (
        "official_guidance",
        "official_regulation_snapshot",
        "official_form",
    ):
        raise ValueError("Reviewed blocking rules require official evidence")
    from .access import registry

    keys = registry("TRADE_RULE_REVIEWERS")
    if first.reviewer == second.reviewer or keys.get(first.reviewer) == keys.get(
        second.reviewer
    ):
        raise ValueError("Independent specialist keys required")
    for proof in (first, second):
        verify("TRADE_RULE_REVIEWERS", rule.model_dump(mode="json"), proof)
    digest = sha(canonical(rule.model_dump(mode="json")))
    with database() as db:
        prior = (
            db.execute(
                "SELECT MAX(version) FROM reviewed_rules WHERE id=?", (rule.rule_id,)
            ).fetchone()[0]
            or 0
        )
        if rule.version != prior + 1:
            raise ValueError("Stale rule revision")
        db.execute(
            "INSERT INTO reviewed_rules VALUES(?,?,?,?,?,?)",
            (
                rule.rule_id,
                rule.version,
                digest,
                rule.model_dump_json(),
                first.model_dump_json(),
                second.model_dump_json(),
            ),
        )
    return Registration(digest=digest, version=rule.version)


def applicable(db, o):
    today = datetime.now(timezone.utc).date()
    rules = []
    for row in db.execute(
        "SELECT r.* FROM reviewed_rules r WHERE version=(SELECT MAX(version) FROM reviewed_rules WHERE id=r.id) ORDER BY id"
    ):
        r = Rule.model_validate_json(row["body"])
        if (
            r.state == "active"
            and r.effective_from <= today <= r.effective_through
            and r.region in ("GLOBAL", o.destination)
            and o.kind in r.kinds
        ):
            rules.append((r, row["digest"]))
    return rules


def engine_version():
    from importlib.resources import files
    import hashlib

    digest = hashlib.sha256()
    for name in (
        "model.py",
        "rules.py",
        "render.py",
        "locale.py",
        "audit.py",
        "print_layout.py",
    ):
        digest.update(files("trade_document").joinpath(name).read_bytes())
    return digest.hexdigest()


def evaluate(db, o):
    active = applicable(db, o)
    findings = []
    for r, _ in active:
        value = (
            all(i.origin for i in o.items)
            if r.required_field == "origin"
            else getattr(o, r.required_field)
        )
        if not value:
            findings.append(
                Finding(
                    rule_id=r.rule_id,
                    source_id=r.source_id,
                    scope=r.region,
                    severity="block",
                    evidence=r.locator + " — " + r.interpretation,
                    resolution=r.resolution,
                )
            )
    beneficiary_version = None
    if o.beneficiary_ref:
        row = db.execute(
            "SELECT version FROM beneficiaries WHERE ref=? ORDER BY version DESC LIMIT 1",
            (o.beneficiary_ref,),
        ).fetchone()
        beneficiary_version = row[0] if row else None
    return sha(
        canonical(
            [engine_version(), beneficiary_version, *[digest for _, digest in active]]
        )
    ), findings
