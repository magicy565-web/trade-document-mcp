import base64
import shutil
from uuid import uuid4
from typing import Annotated
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from .model import Model, Order, Text, Totals, calculate, issues
from .storage import Snapshot, current, database, home, save, sha
from .extract import Extraction, Source, Highlight, grounded, populate
from .approval import Proof, Review, authorize, basis, request, template_version
from .render import TITLES, open_template, pdf, workbook
from .finance import registered
from .resolution import FieldResolution, resolve
from .audit import Audit, inspect_files


class TradeServer(FastMCP):
    async def list_tools(self):
        specs = await super().list_tools()
        for spec in specs:
            spec.inputSchema["additionalProperties"] = False
        return specs

    async def call_tool(self, name, arguments):
        spec = next((t for t in await self.list_tools() if t.name == name), None)
        if spec and set(arguments or {}) - spec.inputSchema["properties"].keys():
            raise ValueError("Unknown tool argument")
        return await super().call_tool(name, arguments)


mcp = TradeServer("Trade Document MCP")
from . import knowledge

for name, fn in [
    ("list_jurisdiction_profiles", knowledge.profiles),
    ("get_rule_evidence", knowledge.source),
    ("get_source_reference", knowledge.source),
    ("search_knowledge", knowledge.search),
    ("resolve_document_requirements", knowledge.requirements),
    ("validate_jurisdiction", knowledge.requirements),
]:
    mcp.tool(name=name)(fn)

Id = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
Version = Annotated[int, Field(ge=1, strict=True)]


class Validation(Model):
    valid: bool
    findings: list[str]


class Template(Model):
    id: str
    name: str


class Templates(Model):
    templates: list[Template]


class Artifact(Model):
    artifact_id: str
    order_id: str
    version: int
    preview: bool
    xlsx_path: str
    pdf_path: str
    audit: Audit


@mcp.tool()
def create_order_draft(
    order: Order,
    sources: list[Source] | None = None,
    highlights: list[Highlight] | None = None,
) -> Snapshot:
    """Create an immutable initial revision. Omit unknown commercial values."""
    with database() as db:
        return save(
            db, populate(order, sources, highlights or []) if sources else order
        )


@mcp.tool()
def extract_order_information(
    sources: list[Source], highlights: list[Highlight] | None = None
) -> Extraction:
    """Extract labeled chat lines and CSV quotation/product rows with source evidence."""
    return grounded(sources, highlights or [])


@mcp.tool()
def update_order_draft(
    order_id: Id,
    expected_version: Version,
    order: Order | None = None,
    resolutions: Annotated[list[FieldResolution], Field(min_length=1, max_length=200)]
    | None = None,
) -> Snapshot:
    """Replace an order or propose evidenced field resolutions on its current revision."""
    if (order is None) == (resolutions is None):
        raise ValueError("Supply either the full order or field resolutions")
    with database() as db:
        previous = current(db, order_id)
        if previous.version != expected_version:
            raise ValueError("Stale version")
        revision = order if order is not None else resolve(previous.order, resolutions)
        return save(db, revision, order_id, expected_version)


@mcp.tool()
def get_order_draft(order_id: Id, version: Version | None = None) -> Snapshot:
    """Read a current or archived revision."""
    with database() as db:
        return current(db, order_id, version)


@mcp.tool()
def calculate_order(order_id: Id) -> Totals:
    """Calculate explicit charges and rounded line totals in the selected currency."""
    return calculate(get_order_draft(order_id).order)


@mcp.tool()
def validate_order(order_id: Id) -> Validation:
    """Report missing fields and commercial inconsistencies."""
    with database() as db:
        o = current(db, order_id).order
        errors = issues(o, registered(db))
        if (
            o.template_id
            and not db.execute(
                "SELECT 1 FROM templates WHERE id=?", (o.template_id,)
            ).fetchone()
        ):
            errors.append("Unknown enterprise template")
        return Validation(valid=not errors, findings=errors)


@mcp.tool()
def register_template(
    name: Text, xlsx_base64: Annotated[str, Field(max_length=2000000)]
) -> Template:
    """Identify section anchors in a compatible enterprise XLSX and register its immutable hash."""
    data = base64.b64decode(xlsx_base64, validate=True)
    open_template(data)
    tid = sha(data)
    with database() as db:
        db.execute("INSERT OR IGNORE INTO templates VALUES(?,?,?)", (tid, name, data))
        name = db.execute("SELECT name FROM templates WHERE id=?", (tid,)).fetchone()[0]
    return Template(id=tid, name=name)


@mcp.tool()
def list_templates() -> Templates:
    """List built-in document types and registered workbook layouts."""
    with database() as db:
        return Templates(
            templates=[Template(id=k, name=v) for k, v in TITLES.items()]
            + [
                Template(id=r[0], name=r[1])
                for r in db.execute("SELECT id,name FROM templates ORDER BY name,id")
            ]
        )


def emit(db, snap, preview, rid=None):
    aid = uuid4().hex
    root = home() / "artifacts" / aid
    root.mkdir(parents=True)
    x, p = root / "document.xlsx", root / "document.pdf"
    try:
        template = None
        o = snap.order
        if o.template_id:
            template_version(db, o)
            row = db.execute(
                "SELECT content FROM templates WHERE id=?", (o.template_id,)
            ).fetchone()
            if not row:
                raise ValueError("Unknown enterprise template")
            template = row[0]
        title = ("DRAFT - " if preview else "") + TITLES[o.kind]
        workbook(o, title, x, template, draft=preview)
        pdf(o, title, p, snap.version, draft=preview)
        report = inspect_files(o, x, p, title, draft=preview)
        if not report.passed:
            raise ValueError("Artifact audit failed: " + " | ".join(report.findings))
        db.execute(
            "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)",
            (
                aid,
                snap.order_id,
                snap.version,
                rid,
                preview,
                sha(x.read_bytes()),
                sha(p.read_bytes()),
            ),
        )
        if preview:
            db.execute("INSERT INTO preview_basis VALUES (?, ?)", (aid, basis()))
        return Artifact(
            artifact_id=aid,
            order_id=snap.order_id,
            version=snap.version,
            preview=preview,
            xlsx_path=str(x),
            pdf_path=str(p),
            audit=report,
        )
    except BaseException:
        shutil.rmtree(root)
        raise


@mcp.tool()
def preview_document(order_id: Id, expected_version: Version) -> Artifact:
    """Write order previews with explicit Pending values for unknown amounts."""
    with database() as db:
        snap = current(db, order_id)
        if snap.version != expected_version:
            raise ValueError("Stale version")
        return emit(db, snap, True)


@mcp.tool()
def request_approval(order_id: Id, expected_version: Version) -> Review:
    """Issue a challenge for a separate human reviewer after validation and preview."""
    with database() as db:
        snap = current(db, order_id)
        if snap.version != expected_version:
            raise ValueError("Stale version")
        if not db.execute(
            "SELECT 1 FROM artifacts WHERE order_id=? AND version=? AND preview=1",
            (order_id, expected_version),
        ).fetchone():
            raise ValueError("Preview current revision first")
        return request(db, snap)


@mcp.tool()
def generate_document(request_id: Id, proof: Proof) -> Artifact:
    """Verify detached reviewer signature and release audited English XLSX and PDF."""
    with database() as db:
        snap = authorize(db, request_id, proof)
        prior = db.execute(
            "SELECT id FROM artifacts WHERE order_id=? AND version=? AND preview=0 ORDER BY rowid LIMIT 1",
            (snap.order_id, snap.version),
        ).fetchone()
        if prior:
            artifact = check(db, prior[0])
            if not artifact.audit.passed:
                raise ValueError("Archived issuance failed integrity check")
            return artifact
        return emit(db, snap, False, request_id)


def check(db, aid):
    row = db.execute("SELECT * FROM artifacts WHERE id=?", (aid,)).fetchone()
    if not row:
        raise ValueError("Unknown artifact")
    snap = current(db, row["order_id"], row["version"])
    x = home() / "artifacts" / aid / "document.xlsx"
    p = x.with_suffix(".pdf")
    if not all(
        f.is_file() and sha(f.read_bytes()) == row[k]
        for f, k in [(x, "workbook"), (p, "pdf")]
    ):
        report = Audit(passed=False, findings=["Archived files missing or changed"])
    else:
        report = inspect_files(
            snap.order,
            x,
            p,
            ("DRAFT - " if row["preview"] else "") + TITLES[snap.order.kind],
            draft=bool(row["preview"]),
        )
    return Artifact(
        artifact_id=aid,
        order_id=snap.order_id,
        version=snap.version,
        preview=bool(row["preview"]),
        xlsx_path=str(x),
        pdf_path=str(p),
        audit=report,
    )


@mcp.tool()
def audit_document(artifact_id: Id) -> Audit:
    """Inspect both archived files against their immutable source revision and hashes."""
    with database() as db:
        return check(db, artifact_id).audit


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
