"""Acquire allowlisted public reference documents into ignored local review storage.

No training approval or public redistribution is implied. No third-party content is executed.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen, HTTPRedirectHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "knowledge" / "corpus"
LIMIT = 30 * 1024 * 1024

class SameHostRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urlparse(req.full_url)
        new = urlparse(newurl)
        if new.scheme != "https" or old.hostname != new.hostname:
            raise ValueError("Cross-host/insecure redirect; verify URL and update registry")
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def acquire(source, output):
    url = source["url"]
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Expected a registered HTTPS URL")
    if not re.fullmatch(r"[A-Z0-9-]+", source["id"]):
        raise ValueError("Invalid source id")
    ext = source["format"]
    if ext not in ("pdf", "html"):
        raise ValueError("Unsupported format")
    opener = build_opener(SameHostRedirect())
    with opener.open(Request(url, headers={"User-Agent": "TradeDocumentReference/0.1"}), timeout=30) as response:
        data = response.read(LIMIT + 1)
        mime = response.headers.get_content_type()
        final_url = response.geturl()
    if not data or len(data) > LIMIT:
        raise ValueError("Empty or oversized document")
    if ext == "pdf" and not data.startswith(b"%PDF-"):
        raise ValueError("Expected PDF bytes; refused HTML/error response")
    if ext == "html" and (mime not in ("text/html", "application/xhtml+xml") or b"<" not in data[:4096]):
        raise ValueError("Expected HTML document")
    digest = hashlib.sha256(data).hexdigest()
    target = output / (source["id"] + "-" + digest[:16] + "." + ext)
    target.write_bytes(data)
    return {
        "id": source["id"], "url": url, "final_url": final_url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "bytes": len(data), "sha256": digest, "content_type": mime,
        "file": target.name, "status": "downloaded_review_only",
        "training_status": "not_approved"
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--id", action="append", default=[])
    parser.add_argument("--acknowledge-local-reference-rights", action="store_true")
    args = parser.parse_args()
    sources = json.loads((CORPUS / "registry.json").read_text(encoding="utf-8"))["sources"]
    indexed = {s["id"]: s for s in sources}
    if args.list:
        for s in sources:
            print(s["id"], s["format"], s["download_policy"], s["url"])
        return 0
    if not args.id or any(i not in indexed for i in args.id):
        parser.error("Choose explicit registered source IDs; use --list")
    output = CORPUS / ".raw"
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    manifest = output / "acquisition.jsonl"
    failed = 0
    for sid in dict.fromkeys(args.id):
        source = indexed[sid]
        policy = source["download_policy"]
        try:
            if policy == "restricted" or policy not in ("review", "open_reference"):
                raise ValueError("Excluded from this pipeline")
            if policy == "review" and not args.acknowledge_local_reference_rights:
                raise ValueError("Verify lawful local reference rights before fetching")
            record = acquire(source, output)
        except Exception as error:
            failed += 1
            record = {"id": sid, "status": "failed", "error": str(error),
                      "retrieved_at": datetime.now(timezone.utc).isoformat(),
                      "training_status": "not_approved"}
        with manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(sid, record["status"], record.get("sha256", record.get("error", "")))
    return int(failed != 0)

if __name__ == "__main__":
    raise SystemExit(main())
