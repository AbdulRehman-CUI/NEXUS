"""Disposable parser process. No network/tool capability is exposed to document content."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

from .extraction import NeedsOCR, extract


def main():
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
        resource.setrlimit(resource.RLIMIT_CPU, (300, 300))
    except ImportError:
        pass  # Windows uses the parent wall timeout; this is process isolation, not a full OS sandbox.
    body = json.loads(sys.stdin.read(4096))
    try:
        passages = extract(Path(body.pop("path")), **body)
        output = {"passages": [asdict(p) for p in passages]}
    except NeedsOCR as error:
        output = {"needs_ocr": True, "error": str(error)}
    except ValueError as error:
        output = {"error": str(error)[:500]}
    except Exception:
        output = {"error": "Document parser failed. Export a valid text document and retry."}
    sys.stdout.write(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
