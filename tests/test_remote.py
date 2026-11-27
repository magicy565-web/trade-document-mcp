import asyncio, time, json, hashlib, socket, threading
import httpx, uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from trade_document.remote import create_app


def test_network_tenant_roles_and_download(monkeypatch, order):
    import os

    for name in list(os.environ):
        if name.lower().endswith("_proxy"):
            monkeypatch.delenv(name)
    config = {}
    for token, tenant, role in [
        ("alpha", "acme", "editor"),
        ("beta", "next", "editor"),
        ("read", "acme", "viewer"),
    ]:
        config[hashlib.sha256(token.encode()).hexdigest()] = {
            "tenant": tenant,
            "actor": token,
            "role": role,
            "expires": int(time.time()) + 600,
        }
    monkeypatch.setenv("TRADE_HTTP_IDENTITIES", json.dumps(config))
    app = create_app()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    host = f"http://127.0.0.1:{port}"
    service = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(
        target=service.run, kwargs={"sockets": [sock]}, daemon=True
    )
    thread.start()
    try:
        for _ in range(120):
            if service.started:
                break
            time.sleep(0.025)
        assert httpx.get(host + "/mcp").status_code == 401

        async def call(token, name, args):
            async with (
                streamablehttp_client(
                    host + "/mcp", headers={"Authorization": "Bearer " + token}
                ) as (r, w, _),
                ClientSession(r, w) as c,
            ):
                await c.initialize()
                return await c.call_tool(name, args)

        def run(token, name, args):
            return asyncio.run(call(token, name, args))

        args = {
            "order": order.model_dump(mode="json"),
            "idempotency_key": "external-order-17",
        }
        one = run("alpha", "create_order_draft", args)
        assert not one.isError, one.content
        s = one.structuredContent
        assert run("alpha", "create_order_draft", args).structuredContent == s
        assert run("read", "create_order_draft", args).isError
        assert run("beta", "get_order_draft", {"order_id": s["order_id"]}).isError
        a = run(
            "alpha",
            "preview_document",
            {"order_id": s["order_id"], "expected_version": 1},
        ).structuredContent
        ticket = run(
            "alpha",
            "get_file_download",
            {"artifact_id": a["artifact_id"], "file": "document.pdf"},
        ).structuredContent
        assert (
            httpx.get(
                host + ticket["path"], headers={"Authorization": "Bearer beta"}
            ).status_code
            == 404
        )
        response = httpx.get(
            host + ticket["path"], headers={"Authorization": "Bearer alpha"}
        )
        assert response.content.startswith(b"%PDF")
        req = run(
            "alpha",
            "request_approval",
            {"order_id": s["order_id"], "expected_version": 1},
        ).structuredContent
        url = host + "/reviews/" + req["request_id"]
        assert (
            httpx.get(url, headers={"Authorization": "Bearer beta"}).status_code == 404
        )
        assert (
            "Excel preview"
            in httpx.get(url, headers={"Authorization": "Bearer alpha"}).text
        )
        assert (
            httpx.post(
                url, headers={"Authorization": "Bearer read"}, json={}
            ).status_code
            == 403
        )
    finally:
        service.should_exit = True
        thread.join(timeout=10)
        sock.close()
