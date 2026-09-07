"""Run the publish-retry-command claim/lease worker (3C.1C-B ownership only)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.workers.publish_retry_command_worker import main

if __name__ == "__main__":
    main()
