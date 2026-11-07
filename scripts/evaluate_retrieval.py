"""No-cloud retrieval benchmark; see --help for model and storage options."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from nexus.evaluate import main

if __name__ == "__main__":
    main()
