"""Run the V0.1 engineering checks and record evidence for the checked-out commit."""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True
    ).strip()


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, choices=("3.11", "3.12"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    actual = f"{sys.version_info.major}.{sys.version_info.minor}"
    if actual != args.python:
        parser.error(f"Expected Python {args.python}, got {actual}")
    if git("status", "--porcelain", "--untracked-files=normal"):
        parser.error("Verification requires a clean checkout")

    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error("Evidence directory must be outside the checkout")
    output.mkdir(parents=True, exist_ok=False)
    evidence = {
        "commit": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "lock_sha256": sha256(ROOT / "requirements.lock"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "steps": {},
        "sample_sha256": {},
        "passed": False,
    }
    try:
        checks = {
            "pytest": ["-m", "pytest", "-q"],
            "synthetic-smoke": ["tools/evaluate.py"],
            "demo": ["tools/demo.py", str(output / "samples")],
        }
        for name, command in checks.items():
            print(f"Python {actual} | {name}", flush=True)
            log = output / f"{name}.log"
            with log.open("wb") as stream:
                proc = subprocess.run(
                    [sys.executable, *command], cwd=ROOT, stdout=stream,
                    stderr=subprocess.STDOUT, check=False,
                )
            evidence["steps"][name] = {
                "exit_code": proc.returncode, "log": log.name, "sha256": sha256(log),
            }
            if proc.returncode:
                print(log.read_text(errors="replace"), file=sys.stderr)
                return 1

        samples = output / "samples"
        kinds = ("standard-pi", "product-image-pi", "sample-pi", "sample-order")
        expected = [samples / f"{kind}.{ext}" for kind in kinds for ext in ("pdf", "xlsx")]
        if any(not path.is_file() or not path.stat().st_size for path in expected):
            raise RuntimeError("Demo did not produce all four XLSX/PDF pairs")
        evidence["sample_sha256"] = {path.name: sha256(path) for path in expected}
        evidence["passed"] = True
        print(f"Passed on {evidence['commit']} | {output}")
        return 0
    finally:
        evidence["finished_utc"] = datetime.now(timezone.utc).isoformat()
        (output / "verification.json").write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
