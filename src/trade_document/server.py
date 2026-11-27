import base64
import shutil
from uuid import uuid4
from typing import Annotated
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from .model import Model, Order, Text, Totals, calculate, issues
from .storage import Snapshot, current, database, home, save, sha
from .extract import Extraction, Source, Highlight, grounded, populate
from .approval import Proof, Review, authorize, request
from .render import TITLES, document_title, open_template, pdf, workbook
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
        from .access import identity, permit

        principal = identity.get()
        outcome = "ok"
        try:
            permit(name)
            return await super().call_tool(name, arguments)
        except Exception:
            outcome = "error"
            raise
        finally:
            if principal:
                with database() as db:
                    db.execute(
                        "INSERT INTO events(actor,tool,outcome) VALUES(?,?,?)",
                        (principal.actor, name, outcome),
                    )


mcp = TradeServer("Trade Document MCP", stateless_http=True, json_response=True)
from .remote import get_file_download, get_service_status

mcp.tool()(get_file_download)
mcp.tool()(get_service_status)
from .trade_fields import convert_measure

mcp.tool()(convert_measure)

from . import beneficiaries

mcp.tool()(beneficiaries.change_beneficiary)

from . import rules

mcp.tool()(rules.register_reviewed_rule)

from . import shipments

for tool in (
    shipments.create_shipment,
    shipments.check_credit_terms,
    shipments.adjust_shipment,
    shipments.get_shipment_preview,
    shipments.draft_shipping_instruction,
    shipments.revise_shipment,
    shipments.validate_shipment,
    shipments.preview_shipment,
    shipments.export_document_bundle,
    shipments.cross_check_documents,
    shipments.prepare_customs_support,
    shipments.draft_sales_contract,
):
    mcp.tool()(tool)

from . import mapping

for tool in (
    mapping.inspect_template,
    mapping.propose_template_mapping,
    mapping.confirm_template_mapping,
    mapping.validate_template,
):
    mcp.tool()(tool)

from . import knowledge

for name, fn in [
    ("list_jurisdiction_profiles", knowledge.profiles),
    ("get_source_reference", knowledge.source),
    ("search_knowledge", knowledge.search),
    ("resolve_document_requirements", knowledge.requirements),
]:
    mcp.tool(name=name)(fn)

Id = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
Version = Annotated[int, Field(ge=1, strict=True)]


class RuleEvidence(Model):
    source: knowledge.SourceRef
    rule: rules.Rule | None = None
    digest: str | None = None


@mcp.tool()
def get_rule_evidence(
    source_id: Text | None = None,
    rule_id: Text | None = None,
    version: Version | None = None,
) -> RuleEvidence:
    if rule_id:
        with database() as db:
            row = db.execute(
                "SELECT * FROM reviewed_rules WHERE id=? AND (? IS NULL OR version=?) ORDER BY version DESC LIMIT 1",
                (rule_id, version, version),
            ).fetchone()
            if not row:
                raise ValueError("Unknown rule revision")
            r = rules.Rule.model_validate_json(row["body"])
            return RuleEvidence(
                source=knowledge.source(r.source_id), rule=r, digest=row["digest"]
            )
    if not source_id:
        raise ValueError("Source or rule identifier required")
    return RuleEvidence(source=knowledge.source(source_id))


@mcp.tool()
def validate_jurisdiction(
    context: knowledge.Context, order_id: Id | None = None
) -> knowledge.Requirements:
    result = knowledge.requirements(context)
    if order_id:
        with database() as db:
            o = current(db, order_id).order
            if o.destination != context.destination:
                raise ValueError("Destination differs from draft")
            _, findings = rules.evaluate(db, o)
            result.findings.extend(findings)
            result.direct_issue = result.direct_issue and not findings
    return result


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
    idempotency_key: Text | None = None,
) -> Snapshot:
    """Create an immutable initial revision. Omit unknown commercial values."""
    with database() as db:
        payload = populate(order, sources, highlights or []) if sources else order
        digest = sha(payload.model_dump_json().encode())
        if idempotency_key:
            old = db.execute(
                "SELECT digest,id FROM idempotency WHERE key=?", (idempotency_key,)
            ).fetchone()
            if old:
                if old["digest"] != digest:
                    raise ValueError("Idempotency key reused with different payload")
                return current(db, old["id"], 1)
        result = save(db, payload)
        if idempotency_key:
            db.execute(
                "INSERT INTO idempotency VALUES(?,?,?)",
                (idempotency_key, digest, result.order_id),
            )
        return result


@mcp.tool()
def extract_order_information(
    sources: list[Source], highlights: list[Highlight] | None = None
) -> Extraction:
    """Extract labeled chat lines and CSV quotation/product rows with source evidence."""
    return grounded(sources, highlights or [])


@mcp.tool()
def update_order_draft(
    order_id: Id, expected_version: Version, order: Order
) -> Snapshot:
    """Replace the full order using optimistic concurrency. Every revision voids prior approval."""
    with database() as db:
        return save(db, order, order_id, expected_version)


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
        errors = issues(o, beneficiaries.verified(db)) + [
            f.resolution for f in rules.evaluate(db, o)[1]
        ]
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
            row = db.execute(
                "SELECT content FROM templates WHERE id=?", (o.template_id,)
            ).fetchone()
            if not row:
                raise ValueError("Unknown enterprise template")
            template = row[0]
        title = document_title(o, preview)
        enterprise = bool(
            db.execute(
                "SELECT 1 FROM template_reviews WHERE id=?", (o.template_id,)
            ).fetchone()
        )
        incomplete = False
        if preview:
            try:
                calculate(o)
            except ValueError:
                incomplete = True
        if incomplete:
            from . import pending

            pending.write(o, x, p)
            report = pending.inspect(o, x, p)
        else:
            workbook(o, title, x, template, enterprise)
            if enterprise:
                from .print_layout import convert

                convert(x, p)
            else:
                pdf(o, title, p, snap.version)
            report = inspect_files(o, x, p, title, enterprise)
        if not report.passed:
            raise ValueError("Artifact audit failed: " + " | ".join(report.findings))
        if not preview:
            from .objects import archive

            archive([x, p])
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
            db.execute(
                "INSERT INTO preview_rules VALUES(?,?)", (aid, rules.evaluate(db, o)[0])
            )
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
    """Write review files; incomplete drafts retain unknowns as Pending."""
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
        duplicate = db.execute(
            """SELECT 1 FROM artifacts a JOIN versions v ON a.order_id=v.id AND a.version=v.version
          WHERE a.preview=0 AND a.order_id<>? AND json_extract(v.body,'$.kind')=? AND json_extract(v.body,'$.number')=?""",
            (snap.order_id, snap.order.kind, snap.order.number),
        ).fetchone()
        if duplicate:
            raise ValueError("Document number already issued")
        prior = db.execute(
            "SELECT id FROM artifacts WHERE order_id=? AND version=? AND preview=0",
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
        incomplete = False
        if row["preview"]:
            try:
                calculate(snap.order)
            except ValueError:
                incomplete = True
        if incomplete:
            from . import pending

            report = pending.inspect(snap.order, x, p)
        else:
            report = inspect_files(
                snap.order,
                x,
                p,
                document_title(snap.order, bool(row["preview"])),
                bool(
                    db.execute(
                        "SELECT 1 FROM template_reviews WHERE id=?",
                        (snap.order.template_id,),
                    ).fetchone()
                ),
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


from .print_layout import LayoutReport, pagereport


@mcp.tool()
def visual_audit(artifact_id: Id) -> LayoutReport:
    """Inspect physical PDF page boxes and empty pages in a verified bundle."""
    with database() as db:
        a = check(db, artifact_id)
        if not a.audit.passed:
            raise ValueError("Artifact failed integrity check")
        report = pagereport(a.pdf_path)
        report.preview_only = a.preview
        return report


@mcp.tool()
def compare_template_output(artifact_id: Id) -> Audit:
    """Verify the archived workbook and PDF against their template-bound order."""
    return audit_document(artifact_id)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
