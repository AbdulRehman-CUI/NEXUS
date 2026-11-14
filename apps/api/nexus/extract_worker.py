"""Disposable parser process. No network/tool capability is exposed to document content."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

from .extraction import ExtractionRejected, NeedsOCR, extract, parser_output_limit


def parse_request(raw):
    if len(raw) > 16_384:
        return {"status": "invalid_request"}
    try:
        body = json.loads(raw.decode("utf-8"))
        path = Path(body.pop("path"))
        extension = body.pop("extension")
        limit = parser_output_limit(body["max_chars"])
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        return {"status": "invalid_request"}
    try:
        passages = extract(path, extension, **body)
        serialized = json.dumps(
            {"status": "ok", "passages": [asdict(p) for p in passages]}, ensure_ascii=False
        )
        if len(serialized) > limit:
            return {"status": "output_limit"}
        return serialized
    except NeedsOCR as error:
        return {"status": "needs_ocr", "message": str(error)[:500]}
    except ExtractionRejected as error:
        return {"status": "rejected", "message": str(error)[:500]}
    except ImportError:
        return {"status": "dependency_missing"}
    except Exception:
        return {"status": "parser_failed"}


def main():
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
        resource.setrlimit(resource.RLIMIT_CPU, (300, 300))
    except ImportError:
        pass  # Windows uses the parent wall timeout; this is process isolation, not a full OS sandbox.
    response = parse_request(sys.stdin.buffer.read(16_385))
    serialized = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
    sys.stdout.buffer.write(serialized.encode("utf-8"))


if __name__ == "__main__":
    main()
