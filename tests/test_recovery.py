import pytest
from trade_document import server
from trade_document.storage import home
from trade_document.operations import copy_store


def test_restore_and_corruption(order, tmp_path, monkeypatch):
    s = server.create_order_draft(order)
    a = server.preview_document(s.order_id, 1)
    backup = tmp_path / "backup"
    restored = tmp_path / "restored"
    copy_store(home(), backup)
    copy_store(backup, restored, True)
    monkeypatch.setenv("TRADE_DOC_HOME", str(restored))
    assert server.audit_document(a.artifact_id).passed
    (backup / "artifacts" / a.artifact_id / "document.pdf").write_text("changed")
    with pytest.raises(ValueError, match="digest"):
        copy_store(backup, tmp_path / "invalid", True)


def test_publication_rolls_back_on_archive_failure(order, monkeypatch):
    import base64, json
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from trade_document.approval import Proof, message
    from trade_document import objects

    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv(
        "TRADE_DOC_REVIEWERS",
        json.dumps(
            {"qa": base64.b64encode(key.public_key().public_bytes_raw()).decode()}
        ),
    )
    s = server.create_order_draft(order)
    server.preview_document(s.order_id, 1)
    p = server.request_approval(s.order_id, 1)
    proof = Proof(
        reviewer="qa", signature=base64.b64encode(key.sign(message(p, "qa"))).decode()
    )

    def fail(paths):
        raise OSError("Simulated object store outage")

    monkeypatch.setattr(objects, "archive", fail)
    with pytest.raises(OSError):
        server.generate_document(p.request_id, proof)
    assert server.get_order_draft(s.order_id).approval_status == "awaiting_review"
    monkeypatch.setattr(objects, "archive", lambda paths: None)
    assert server.generate_document(p.request_id, proof).audit.passed


def test_object_archive_confirms_checksum(monkeypatch, tmp_path):
    import base64, hashlib
    from trade_document.objects import archive

    monkeypatch.setenv("TRADE_ARCHIVE_BUCKET", "fixture")
    path = tmp_path / "document.pdf"
    path.write_bytes(b"test content")

    class Store:
        objects = {}

        def put_object(self, **record):
            self.objects[record["Key"]] = record["Body"]

        def head_object(self, **request):
            value = self.objects[request["Key"]]
            return {
                "ContentLength": len(value),
                "ChecksumSHA256": base64.b64encode(
                    hashlib.sha256(value).digest()
                ).decode(),
            }

    store = Store()
    archive([path], store)
    assert len(store.objects) == 1
