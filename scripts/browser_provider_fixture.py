"""Loopback-only Ollama protocol fixture for CI; no model or external provider calls."""
import json
import time

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()
MODEL = "nexus-browser-fixture"


@app.get("/api/tags")
def tags():
    return {"models": [{"name": MODEL, "context_window": 8192}]}


@app.post("/api/show")
def show():
    return {"capabilities": ["completion"], "details": {"family": "test-fixture"}}


@app.post("/api/chat")
def chat(body: dict):
    prompt = json.loads(body["messages"][-1]["content"])
    evidence = prompt["evidence"]
    answer = "\n\n".join(f"{item['excerpt']} [{item['citation_id']}]" for item in evidence)
    final = {"done": True, "prompt_eval_count": 40, "eval_count": 12}
    if not body.get("stream"):
        return {**final, "message": {"role": "assistant", "content": answer}}

    def pieces():
        # Give the browser a visible provisional state before completing the protocol.
        yield json.dumps({"done": False, "message": {"content": answer}}) + "\n"
        time.sleep(0.5)
        yield json.dumps({**final, "message": {"content": ""}}) + "\n"

    return StreamingResponse(pieces(), media_type="application/x-ndjson")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=11434, access_log=False)
