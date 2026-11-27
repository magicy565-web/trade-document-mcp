"""Offline operational commands for a single private tenant store."""

import argparse, json, shutil, sqlite3, tempfile, os
from pathlib import Path
from .storage import sha


def checksums(root):
    return {
        p.relative_to(root).as_posix(): sha(p.read_bytes())
        for p in root.rglob("*")
        if p.is_file() and p != root / "manifest.json"
    }


def copy_store(source, destination, restore=False):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if (
        destination.exists()
        or source in destination.parents
        or not (source / "orders.sqlite").is_file()
    ):
        raise ValueError("Use an existing tenant store and a new separate destination")
    if any(p.is_symlink() for p in source.rglob("*")):
        raise ValueError("Store must contain regular archive files")
    if restore and json.loads((source / "manifest.json").read_text()) != checksums(
        source
    ):
        raise ValueError("Backup digest mismatch")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        staged = Path(temp) / "store"
        staged.mkdir(mode=0o700)
        guard = sqlite3.connect(source / "orders.sqlite", timeout=30)
        src = sqlite3.connect(source / "orders.sqlite")
        dst = sqlite3.connect(staged / "orders.sqlite")
        try:
            guard.execute("BEGIN IMMEDIATE")
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite integrity check failed")
            for folder in ("shipping", "artifacts"):
                if (source / folder).exists():
                    shutil.copytree(source / folder, staged / folder)
            if restore:
                for sid, body in dst.execute(
                    "SELECT id,body FROM shipment_issues"
                ).fetchall():
                    record = json.loads(body)
                    record["files"] = [
                        str(
                            destination
                            / "shipping"
                            / Path(p).parent.name
                            / Path(p).name
                        )
                        for p in record["files"]
                    ]
                    dst.execute(
                        "UPDATE shipment_issues SET body=? WHERE id=?",
                        (json.dumps(record), sid),
                    )
                dst.execute("DELETE FROM downloads")
                dst.commit()
        finally:
            dst.close()
            src.close()
            guard.close()
        if not restore:
            (staged / "manifest.json").write_text(
                json.dumps(checksums(staged), indent=2)
            )
        os.rename(staged, destination)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["backup", "restore"])
    p.add_argument("source", type=Path)
    p.add_argument("destination", type=Path)
    a = p.parse_args()
    copy_store(a.source, a.destination, a.action == "restore")
