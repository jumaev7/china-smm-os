"""Unit tests for NotificationService helpers."""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.notification_service import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


def test_page_size_defaults():
    assert DEFAULT_PAGE_SIZE == 20
    assert MAX_PAGE_SIZE == 100


def test_pages_calculation():
    total = 45
    page_size = 20
    pages = max(1, math.ceil(total / page_size))
    assert pages == 3

    total = 0
    pages = 0 if total == 0 else max(1, math.ceil(total / page_size))
    assert pages == 0
