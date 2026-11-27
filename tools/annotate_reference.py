"""Index a reviewed reference annotation in private storage, retaining its exact source."""

import argparse, json, hashlib
from pathlib import Path
from typing import Annotated, Literal
from pydantic import Field, model_validator
from pypdf import PdfReader
from trade_document.types import Model, Text
from trade_document.knowledge import source


class Annotation(Model):
    source_id: Text
    source_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    field: Text
    reviewer: Text
    rights_record: Text
    scope: Literal["private_reference", "private_evaluation"]
    locator: Text
    page: Annotated[int, Field(gt=0)] | None = None
    box: tuple[float, float, float, float] | None = None
    note: Text

    @model_validator(mode="after")
    def coordinates(self):
        if self.box and (
            not self.page
            or not (
                0 <= self.box[0] < self.box[2] <= 1
                and 0 <= self.box[1] < self.box[3] <= 1
            )
        ):
            raise ValueError("Expected page and normalized bounding box")
        return self


def ingest(annotation, data_dir):
    source(annotation.source_id)
    events = [
        json.loads(l)
        for l in (data_dir / "acquisition.jsonl").read_text().splitlines()
        if l.strip()
    ]
    record = next(
        (
            r
            for r in events
            if r.get("id") == annotation.source_id
            and r.get("sha256") == annotation.source_sha256
            and r.get("status") == "downloaded_review_only"
        ),
        None,
    )
    if not record or Path(record["file"]).name != record["file"]:
        raise ValueError("Missing acquired reference")
    path = data_dir / record["file"]
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != annotation.source_sha256:
            raise ValueError("Source integrity mismatch")
        if path.suffix == ".pdf":
            pdf = PdfReader(path)
            if not annotation.page or annotation.page > len(pdf.pages):
                raise ValueError("Annotation page outside source")
        elif annotation.page or annotation.box:
            raise ValueError("Use section locator for HTML")
    except Exception as e:
        with (data_dir / "quarantine.jsonl").open("a") as f:
            f.write(
                json.dumps({"source_id": annotation.source_id, "reason": str(e)}) + "\n"
            )
        raise
    with (data_dir / "annotations.jsonl").open("a") as f:
        f.write(annotation.model_dump_json() + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("annotation", type=Path)
    p.add_argument("raw_directory", type=Path)
    a = p.parse_args()
    ingest(Annotation.model_validate_json(a.annotation.read_bytes()), a.raw_directory)
