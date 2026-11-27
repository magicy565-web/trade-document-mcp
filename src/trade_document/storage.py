import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .model import Model, Order


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def home():
    path = Path(os.environ.get("TRADE_DOC_HOME", ".trade-doc")).resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


@contextmanager
def database():
    db = sqlite3.connect(home() / "orders.sqlite", timeout=20)
    db.row_factory = sqlite3.Row
    try:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS versions(id TEXT, version INTEGER, body TEXT, digest TEXT,
          created TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(id,version));
        CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, order_id TEXT, version INTEGER,
          digest TEXT, reviewer TEXT, proof TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, order_id TEXT, version INTEGER,
          request_id TEXT, preview INTEGER, workbook TEXT, pdf TEXT);
        CREATE TABLE IF NOT EXISTS shipments(id TEXT,ver INTEGER,body TEXT,PRIMARY KEY(id,ver));
        CREATE TABLE IF NOT EXISTS ship_reviews(id TEXT PRIMARY KEY,body TEXT);
        CREATE TABLE IF NOT EXISTS shipment_issues(id TEXT PRIMARY KEY,body TEXT,challenge TEXT,reviewer TEXT,signature TEXT);
        CREATE TABLE IF NOT EXISTS template_reviews(id TEXT PRIMARY KEY,original BLOB,mapping TEXT,reviewer TEXT,signature TEXT);
        CREATE TABLE IF NOT EXISTS bindings(id TEXT PRIMARY KEY, body TEXT);
        CREATE TABLE IF NOT EXISTS templates(id TEXT PRIMARY KEY, name TEXT, content BLOB);
        """)
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    finally:
        db.close()


class Snapshot(Model):
    order_id: str
    version: int
    digest: str
    order: Order
    approval_status: str = "draft"


def current(db, oid, version=None):
    rows = db.execute(
        "SELECT * FROM versions WHERE id=? AND (? IS NULL OR version=?) ORDER BY version DESC LIMIT 1",
        (oid, version, version),
    ).fetchone()
    if rows is None:
        raise ValueError("Unknown order or version")
    latest = db.execute(
        "SELECT MAX(version) FROM versions WHERE id=?", (oid,)
    ).fetchone()[0]
    state = db.execute(
        "SELECT MAX(reviewer IS NOT NULL) FROM requests WHERE order_id=? AND version=?",
        (oid, rows["version"]),
    ).fetchone()[0]
    status = (
        "superseded"
        if rows["version"] < latest
        else {None: "draft", 0: "awaiting_review", 1: "issued"}[state]
    )
    return Snapshot(
        order_id=oid,
        version=rows["version"],
        digest=rows["digest"],
        approval_status=status,
        order=Order.model_validate_json(rows["body"]),
    )


def save(db, order, oid=None, expected=None):
    version = 1
    if oid is None:
        oid = uuid4().hex
    else:
        if current(db, oid).version != expected:
            raise ValueError("Stale version")
        version = expected + 1
    body = canonical(order.model_dump(mode="json"))
    db.execute(
        "INSERT INTO versions(id,version,body,digest) VALUES(?,?,?,?)",
        (oid, version, body.decode(), sha(body)),
    )
    return current(db, oid)
