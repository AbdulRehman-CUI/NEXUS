"""Serve the production Next build and the real guest API over one test HTTPS origin."""

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import uvicorn
from starlette.requests import Request
from starlette.responses import Response

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))

from nexus.config import Settings
from nexus.main import create_app
from nexus.provider_transport import ProviderTransport

FIRST_KEY = "fixture-model-key-12345"
NEXT_KEY = "fixture-replacement-key-67890"
MODELS = ["fixture/first", "fixture/second"]
OPENAI_MODEL = "fixture-openai-chat"


def provider(request):
    key = request.headers.get("authorization", "").removeprefix("Bearer ")
    if key not in {FIRST_KEY, NEXT_KEY}:
        return httpx.Response(401, json={"error": key})
    if request.url.path.endswith("/auth/key"):
        return httpx.Response(200, json={"data": {}})
    if request.url.path.endswith("/models"):
        if request.url.host == "api.openai.com":
            return httpx.Response(200, json={"data": [{"id": OPENAI_MODEL}]})
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": model,
                        "name": model,
                        "pricing": {"prompt": "0", "completion": "0"},
                    }
                    for model in MODELS
                ]
            },
        )
    body = json.loads(request.content)
    if "provider unavailable" in json.dumps(body):
        return httpx.Response(503, json={"error": f"provider private detail {key}"})
    model = body["model"]
    key_label = "replacement key" if key == NEXT_KEY else "first key"
    content = f"Fixture response from {model} using the {key_label}."
    if body["stream"]:
        delta = {"choices": [{"delta": {"content": content}, "finish_reason": "stop"}]}
        return httpx.Response(
            200, text=f"data: {json.dumps(delta)}\n\ndata: [DONE]\n\n"
        )
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--port", type=int, default=3443)
    parser.add_argument("--frontend-port", type=int, default=3000)
    args = parser.parse_args()

    # Keep all synthetic data within the test process's temporary directory.
    with TemporaryDirectory(prefix="nexus-guest-browser-") as data_dir:
        origin = f"https://127.0.0.1:{args.port}"
        api = create_app(
            Settings(
                _env_file=None,
                data_dir=data_dir,
                profile="server",
                guest_access=True,
                guest_session_secret="fixture-only-guest-session-secret",
                byok_master_key="bW1tbW1tbW1tbW1tbW1tbW1tbW1tbW1tbW1tbW1tbW0=",
                embedding_provider="hash",
                cors_origins=[origin],
                login_limit_per_minute=30,
                rate_limit_per_minute=10000,
            )
        )
        original = ProviderTransport.__init__

        def use_fixture_transport(transport, *args, **kwargs):
            original(transport, *args, **kwargs)
            transport.client_factory = lambda **options: httpx.Client(
                transport=httpx.MockTransport(provider), **options
            )

        ProviderTransport.__init__ = use_fixture_transport

        async def app(scope, receive, send):
            if (
                scope["type"] != "http"
                or scope["path"].startswith("/api/")
                or scope["path"] == "/health"
            ):
                await api(scope, receive, send)
                return
            request = Request(scope, receive)
            headers = {
                key: value
                for key, value in request.headers.items()
                if key == "rsc" or key.startswith("next-")
            }
            headers["accept-encoding"] = "identity"
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{args.frontend_port}"
            ) as frontend:
                result = await frontend.request(
                    request.method,
                    str(request.url.path)
                    + (f"?{request.url.query}" if request.url.query else ""),
                    headers=headers,
                )
            response = Response(
                result.content,
                status_code=result.status_code,
                headers={
                    key: value
                    for key, value in result.headers.items()
                    if key
                    not in {
                        "content-encoding",
                        "content-length",
                        "transfer-encoding",
                        "connection",
                    }
                },
            )
            await response(scope, receive, send)

        uvicorn.run(
            app,
            host="127.0.0.1",
            port=args.port,
            ssl_certfile=args.cert,
            ssl_keyfile=args.key,
            access_log=False,
        )


if __name__ == "__main__":
    main()
