"""Privileged operator CLI for dual-signed beneficiary changes."""

import argparse
import base64
import getpass
import json
import os
from pathlib import Path
from typing import Annotated, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pydantic import Field

from .approval import Proof
from .model import Model, Text
from .storage import canonical, database, sha


class BeneficiaryChange(Model):
    purpose: Literal["trade.beneficiary.v1"] = "trade.beneficiary.v1"
    reference: Text
    version: Annotated[int, Field(gt=0, strict=True)]
    instructions: Text
    verification_record: Text
    status: Literal["active", "revoked"]


def registered(db):
    values = json.loads(os.environ.get("TRADE_DOC_BENEFICIARIES", "{}"))
    rows = db.execute("""
        SELECT b.body FROM beneficiaries b
        WHERE version=(SELECT MAX(version) FROM beneficiaries WHERE ref=b.ref)
    """)
    for row in rows:
        entry = BeneficiaryChange.model_validate_json(row["body"])
        if entry.status == "active":
            values[entry.reference] = entry.instructions
        else:
            values.pop(entry.reference, None)
    return values


def change_beneficiary(
    change: BeneficiaryChange, verifier: Proof, authorizer: Proof
) -> str:
    payload = canonical(change.model_dump(mode="json"))
    keys = []
    for proof, role in (
        (verifier, "TRADE_FINANCE_VERIFIERS"),
        (authorizer, "TRADE_FINANCE_AUTHORIZERS"),
    ):
        public = json.loads(os.environ.get(role, "{}")).get(proof.reviewer)
        if not public:
            raise ValueError("Registered finance signer required")
        try:
            key = base64.b64decode(public, validate=True)
            Ed25519PublicKey.from_public_bytes(key).verify(
                base64.b64decode(proof.signature, validate=True), payload
            )
        except (ValueError, InvalidSignature) as error:
            raise ValueError("Invalid finance signature") from error
        keys.append(key)
    if verifier.reviewer == authorizer.reviewer or keys[0] == keys[1]:
        raise ValueError("Two independent finance signers required")
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
            "INSERT INTO beneficiaries VALUES (?,?,?,?,?)",
            (
                change.reference,
                change.version,
                change.model_dump_json(),
                verifier.model_dump_json(),
                authorizer.model_dump_json(),
            ),
        )
    return sha(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    signer = commands.add_parser("sign")
    signer.add_argument("packet", type=Path)
    signer.add_argument("reviewer")
    signer.add_argument("private_key", type=Path)
    apply = commands.add_parser("apply")
    apply.add_argument("packet", type=Path)
    apply.add_argument("verification_proof", type=Path)
    apply.add_argument("authorization_proof", type=Path)
    args = parser.parse_args()
    change = BeneficiaryChange.model_validate_json(args.packet.read_bytes())
    if args.command == "apply":
        print(
            change_beneficiary(
                change,
                Proof.model_validate_json(args.verification_proof.read_bytes()),
                Proof.model_validate_json(args.authorization_proof.read_bytes()),
            )
        )
        return
    import sys

    print(change.model_dump_json(indent=2), file=sys.stderr)
    print(
        f"After reviewing the independent verification record, type {change.reference}: ",
        file=sys.stderr,
        end="",
        flush=True,
    )
    if sys.stdin.readline().strip() != change.reference:
        raise SystemExit("Declined")
    key = load_pem_private_key(
        args.private_key.read_bytes(),
        password=getpass.getpass("Private key passphrase: ").encode(),
    )
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("Ed25519 private key required")
    signature = key.sign(canonical(change.model_dump(mode="json")))
    print(
        Proof(
            reviewer=args.reviewer, signature=base64.b64encode(signature).decode()
        ).model_dump_json()
    )
