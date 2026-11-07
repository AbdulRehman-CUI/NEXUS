"""Bounded local server readiness for CI and manual browser checks."""

import time

import httpx

for _ in range(120):
    try:
        with httpx.Client(timeout=2, trust_env=False) as client:
            client.get("http://127.0.0.1:8000/health").raise_for_status()
            client.get("http://127.0.0.1:3000").raise_for_status()
        break
    except httpx.HTTPError:
        time.sleep(0.5)
else:
    raise SystemExit(
        "Local API/web did not become ready within the bounded startup window."
    )
