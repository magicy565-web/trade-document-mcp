"""Run on the reviewer's own machine with a private, encrypted Ed25519 PEM."""

import argparse
import base64
import getpass
import time
from pathlib import Path
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from .approval import Proof, Review, message
from .model import calculate
from .storage import canonical, sha


def main():
    p = argparse.ArgumentParser()
    p.add_argument("request", type=Path)
    p.add_argument("reviewer")
    p.add_argument("private_key", type=Path)
    p.add_argument("--preview-dir", type=Path, required=True)
    args = p.parse_args()
    review = Review.model_validate_json(args.request.read_bytes())
    snap = review.snapshot
    if sha(canonical(snap.order.model_dump(mode="json"))) != snap.digest:
        raise SystemExit("Invalid review packet")
    if review.binding.expires <= time.time():
        raise SystemExit("Expired review packet")
    for name, digest in (
        ("document.xlsx", review.binding.workbook),
        ("document.pdf", review.binding.pdf),
    ):
        path = args.preview_dir / name
        if not path.is_file() or sha(path.read_bytes()) != digest:
            raise SystemExit(f"Preview hash mismatch: {name}")
    print(review.binding.model_dump_json(indent=2))
    print(snap.model_dump_json(indent=2))
    print(calculate(snap.order).model_dump_json(indent=2))
    if (
        input(
            "Confirm all prices, fees, terms, beneficiary and final issue. Type document number: "
        )
        != snap.order.number
    ):
        raise SystemExit("Declined")
    key = load_pem_private_key(
        args.private_key.read_bytes(),
        password=getpass.getpass("Private key passphrase: ").encode(),
    )
    signature = key.sign(message(review, args.reviewer))
    print(
        Proof(
            reviewer=args.reviewer, signature=base64.b64encode(signature).decode()
        ).model_dump_json()
    )


if __name__ == "__main__":
    main()
