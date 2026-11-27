"""Human signing workstation. Check the exact preview bytes before using the private key."""

import argparse, base64, getpass, json, time
from pathlib import Path
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from .storage import canonical, sha
from .approval import Proof, Review, message
from .mapping import Mapping
from .shipments import Packet


def prepare(raw, reviewer, folder):
    if raw.get("purpose") == "trade.beneficiary.v1":
        from .beneficiaries import Change

        value = Change.model_validate(raw)
        checks = {}
        payload = canonical(value.model_dump(mode="json"))
        confirmation = value.reference
    elif raw.get("purpose") == "shipment.adjustment.v1":
        from .shipments import Adjustment

        value = Adjustment.model_validate(raw)
        checks = {}
        payload = canonical(value.model_dump(mode="json"))
        confirmation = value.reference
    elif raw.get("purpose") == "trade.rule.v1":
        from .rules import Rule

        value = Rule.model_validate(raw)
        checks = {}
        payload = canonical(value.model_dump(mode="json"))
        confirmation = value.rule_id
    elif raw.get("purpose") == "trade.template.mapping.v1":
        value = Mapping.model_validate(raw)
        checks = {"original.xlsx": value.digest}
        payload = canonical(value.model_dump(mode="json"))
        confirmation = value.digest
    elif raw.get("purpose") == "shipment.issue.v1":
        value = Packet.model_validate(raw)
        if value.expires <= time.time():
            raise ValueError("Expired packet")
        checks = value.preview_hashes
        payload = canonical(value.model_dump(mode="json"))
        confirmation = value.shipment_id
    else:
        value = Review.model_validate(raw)
        if value.binding.expires <= time.time() or value.snapshot.digest != sha(
            canonical(value.snapshot.order.model_dump(mode="json"))
        ):
            raise ValueError("Expired or inconsistent order packet")
        checks = {
            "document.pdf": value.binding.pdf,
            "document.xlsx": value.binding.workbook,
        }
        payload = message(value, reviewer)
        confirmation = value.snapshot.order.number
    for name, digest in checks.items():
        if Path(name).name != name or sha((folder / name).read_bytes()) != digest:
            raise ValueError("Preview hash mismatch")
    return payload, confirmation


def main():
    p = argparse.ArgumentParser()
    p.add_argument("packet", type=Path)
    p.add_argument("reviewer")
    p.add_argument("private_key", type=Path)
    p.add_argument("folder", type=Path)
    a = p.parse_args()
    raw = json.loads(a.packet.read_bytes())
    payload, confirmation = prepare(raw, a.reviewer, a.folder)
    print(json.dumps(raw, ensure_ascii=False, indent=2))
    if (
        input(f"After reviewing the listed files, enter {confirmation} to authorize: ")
        != confirmation
    ):
        raise SystemExit("Declined")
    key = load_pem_private_key(
        a.private_key.read_bytes(), getpass.getpass("Key passphrase: ").encode()
    )
    print(
        Proof(
            reviewer=a.reviewer, signature=base64.b64encode(key.sign(payload)).decode()
        ).model_dump_json()
    )
