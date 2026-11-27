"""Optional tenant-scoped S3-compatible immutable archive for issued files."""

import base64, os
from pathlib import Path
from .storage import sha
from .access import identity


def archive(paths, client=None):
    bucket = os.environ.get("TRADE_ARCHIVE_BUCKET")
    if not bucket:
        return
    if client is None:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("TRADE_ARCHIVE_ENDPOINT"),
            config=Config(retries={"mode": "standard", "max_attempts": 4}),
        )
    person = identity.get()
    tenant = person.tenant if person else "local"
    for path in paths:
        p = Path(path)
        data = p.read_bytes()
        digest = sha(data)
        checksum = base64.b64encode(bytes.fromhex(digest)).decode()
        key = f"{tenant}/sha256/{digest}"
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ChecksumSHA256=checksum,
            Metadata={"sha256": digest},
        )
        meta = client.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")
        if meta.get("ChecksumSHA256") != checksum or meta["ContentLength"] != len(data):
            raise ValueError("Remote archive checksum mismatch")
