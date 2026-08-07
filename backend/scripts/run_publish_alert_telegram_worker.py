"""Run the publish-operator-alert Telegram delivery worker."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.workers.publish_alert_telegram_worker import main

if __name__ == "__main__":
    main()
