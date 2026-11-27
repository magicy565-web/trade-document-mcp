"""Versioned evidence lookup. Registry notes are advisory until independently approved."""

import json
from importlib.resources import files
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import Field
from .model import Model, Text


def read(path):
    return json.loads(
        files("trade_knowledge").joinpath(*path.split("/")).read_text(encoding="utf8")
    )


class SourceRef(Model):
    id: str
    region: str
    title: str
    publisher: str
    url: str
    authority: str
    training_status: str
    notes: str
    checked_at: str


class Results(Model):
    sources: list[SourceRef]


def sources():
    return [
        SourceRef(**{k: s[k] for k in SourceRef.model_fields})
        for s in read("corpus/registry.json")["sources"]
    ]


def source(source_id: str) -> SourceRef:
    for s in sources():
        if s.id == source_id:
            return s
    raise ValueError("Unknown source")


def search(query: Text) -> Results:
    terms = query.casefold().split()
    return Results(
        sources=[
            s
            for s in sources()
            if all(t in s.model_dump_json().casefold() for t in terms)
        ]
    )


class Context(Model):
    destination: Annotated[str, Field(pattern="^[A-Z]{2}$")]
    purpose: Literal[
        "commercial_pi", "sample_pi", "customs_support", "customs_substitute"
    ] = "commercial_pi"
    declared_value: Annotated[Decimal, Field(gt=0)] | None = None
    valuation_currency: str | None = None
    valuation_evidence: Text | None = None


class Finding(Model):
    rule_id: str
    source_id: str | None
    scope: str
    severity: Literal["review", "block"]
    evidence: str
    resolution: str


class Requirements(Model):
    region: str
    version: str
    review_only: bool
    direct_issue: bool
    findings: list[Finding]


class Profiles(Model):
    regions: list[str]
    version: str


def profiles() -> Profiles:
    data = read("pi-standard.json")
    return Profiles(
        regions=[p["region"] for p in data["profiles"]] + ["DE", "FR"],
        version=data["version"],
    )


def requirements(context: Context) -> Requirements:
    data = read("pi-standard.json")
    region = {"DE": "EU", "FR": "EU"}.get(context.destination, context.destination)
    applicable = [p for p in data["profiles"] if p["region"] == region]
    findings = []
    for p in applicable:
        relevant = context.purpose in p["purpose"] or "context" in p["purpose"]
        if not relevant:
            continue
        for sid in p["sources"]:
            s = source(sid)
            findings.append(
                Finding(
                    rule_id=f"reference.{sid}",
                    source_id=sid,
                    scope=context.purpose,
                    severity="review",
                    evidence=s.notes,
                    resolution="Review source applicability and current edition.",
                )
            )
    if not applicable:
        findings.append(
            Finding(
                rule_id="product.unknown-region",
                source_id=None,
                scope=context.destination,
                severity="review",
                evidence="No reviewed profile",
                resolution="Route local requirements to a specialist.",
            )
        )
    if context.purpose == "customs_support" and not all(
        (context.declared_value, context.valuation_currency, context.valuation_evidence)
    ):
        findings.append(
            Finding(
                rule_id="product.valuation",
                source_id=None,
                scope=context.purpose,
                severity="block",
                evidence="Product policy requires a separately supported valuation",
                resolution="Provide declared value, currency and valuation evidence.",
            )
        )
    if context.purpose == "customs_substitute":
        findings.append(
            Finding(
                rule_id="product.no-importer-declaration",
                source_id="US-CFR-141" if region == "US" else None,
                scope=context.purpose,
                severity="block",
                evidence="Importer declaration is outside supported issuance",
                resolution="Refer declaration to authorized importer.",
            )
        )
    return Requirements(
        region=region,
        version=data["version"],
        review_only=True,
        direct_issue=context.purpose in ("commercial_pi", "sample_pi"),
        findings=findings,
    )
