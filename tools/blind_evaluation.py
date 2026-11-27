"""Aggregate independently adjudicated, authorized blind cases from private JSONL."""

import argparse, json, math
from collections import Counter
from pathlib import Path
from typing import Literal
from pydantic import Field
from trade_document.model import Model, Text


class Case(Model):
    case_id: Text
    company: Text
    template_family: Text
    source_group: Text
    region: Text
    source_type: Literal["real", "synthetic"]
    rights_record: Text
    split: Literal["train", "blind"]
    reviewers: list[Text] = Field(min_length=2)
    eligible: bool
    released: bool
    correct: bool
    first_pass: bool
    manual_clarification: bool
    format_rework: bool
    fields: int = Field(ge=0)
    field_errors: int = Field(ge=0)
    critical_fields: int = Field(ge=0)
    critical_errors: int = Field(ge=0)
    failure_type: Text | None = None


def rate(k, n):
    return k / n if n else None


def wilson(k, n):
    if n == 0:
        return None
    p = k / n
    z = 1.95996398454
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [max(0, (center - radius) / denom), min(1, (center + radius) / denom)]


def evaluate(records):
    seen = set()
    groups = {key: set() for key in ("company", "template_family", "source_group")}
    for case in records:
        if case.case_id in seen or len(set(case.reviewers)) < 2:
            raise ValueError("Duplicate case or missing independent review")
        if (
            case.field_errors > case.fields
            or case.critical_errors > case.critical_fields
            or (
                case.first_pass
                and (not case.correct or not case.released or case.format_rework)
            )
        ):
            raise ValueError("Inconsistent adjudication")
        seen.add(case.case_id)
        if case.split == "train":
            for key in groups:
                groups[key].add(getattr(case, key))
    result = {}
    for kind in ("real", "synthetic"):
        rows = [c for c in records if c.split == "blind" and c.source_type == kind]
        if any(getattr(c, k) in groups[k] for c in rows for k in groups):
            raise ValueError(
                "Blind cohort shares a training company, template or source"
            )
        eligible = [c for c in rows if c.eligible]
        passed = sum(c.first_pass for c in eligible)
        released = [c for c in rows if c.released]
        errors = sum(not c.correct or not c.eligible for c in released)
        result[kind] = {
            "intakes": len(rows),
            "eligible": len(eligible),
            "first_pass_count": passed,
            "first_pass_rate": rate(passed, len(eligible)),
            "wilson_95": wilson(passed, len(eligible)),
            "completion_without_clarification": rate(
                sum(
                    c.released and c.correct and not c.manual_clarification
                    for c in rows
                ),
                len(rows),
            ),
            "clarification_rate": rate(
                sum(c.manual_clarification for c in rows), len(rows)
            ),
            "wrong_releases": errors,
            "wrong_release_rate": rate(errors, len(released)),
            "format_rework_rate": rate(sum(c.format_rework for c in rows), len(rows)),
            "field_accuracy": rate(
                sum(c.fields - c.field_errors for c in rows),
                sum(c.fields for c in rows),
            ),
            "released_critical_accuracy": rate(
                sum(c.critical_fields - c.critical_errors for c in released),
                sum(c.critical_fields for c in released),
            ),
            "regions": dict(Counter(c.region for c in rows)),
            "failure_types": dict(
                Counter(c.failure_type for c in rows if c.failure_type)
            ),
        }
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("manifest", type=Path)
    args = p.parse_args()
    print(
        json.dumps(
            evaluate(
                [
                    Case.model_validate_json(line)
                    for line in args.manifest.read_text().splitlines()
                    if line.strip()
                ]
            ),
            indent=2,
        )
    )
