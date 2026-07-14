"""Run the durable automation scheduler worker."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.workers.automation_scheduler_worker import main

if __name__ == "__main__":
    main()
