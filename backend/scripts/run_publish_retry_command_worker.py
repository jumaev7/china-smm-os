"""Run the publish-retry-command worker (D2-B1 none-stop / B2b1-A staging fake)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.workers.publish_retry_command_worker import main

if __name__ == "__main__":
    main()
