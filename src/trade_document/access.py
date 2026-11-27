import json, os
from contextvars import ContextVar
from .model import Model


class Identity(Model):
    tenant: str
    actor: str
    role: str
    expires: int


identity = ContextVar("trade_identity", default=None)


def registry(name):
    principal = identity.get()
    if principal is None:
        return json.loads(os.environ.get(name, "{}"))
    policies = json.loads(os.environ.get("TRADE_TENANT_POLICIES", "{}"))
    return policies.get(principal.tenant, {}).get(name, {})


def permit(tool):
    principal = identity.get()
    if principal is None:
        return
    read = {
        "get_order_draft",
        "list_templates",
        "list_jurisdiction_profiles",
        "get_rule_evidence",
        "get_source_reference",
        "search_knowledge",
        "resolve_document_requirements",
        "validate_jurisdiction",
        "audit_document",
        "calculate_order",
        "validate_order",
        "validate_template",
        "validate_shipment",
        "cross_check_documents",
        "get_shipment_preview",
        "get_file_download",
        "get_service_status",
        "compare_template_output",
        "visual_audit",
    }
    admin = {
        "register_template",
        "confirm_template_mapping",
        "register_reviewed_rule",
        "change_beneficiary",
    }
    if principal.role == "viewer" and tool not in read:
        raise ValueError("Read-only principal")
    if tool in admin and principal.role != "admin":
        raise ValueError("Template administrator role required")
