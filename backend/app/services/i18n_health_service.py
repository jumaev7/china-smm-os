"""Internationalization health — locale key audit."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCALES_DIR = REPO_ROOT / "frontend" / "locales"
FRONTEND_SCAN_DIRS = (
    REPO_ROOT / "frontend" / "app",
    REPO_ROOT / "frontend" / "components",
    REPO_ROOT / "frontend" / "lib",
)
SUPPORTED = ("ru", "en", "zh")
T_KEY_PATTERN = re.compile(r"""t\(\s*['"]([a-zA-Z0-9_.]+)['"]""")

_missing_logged: set[str] = set()


def _flatten_keys(obj: dict[str, Any], prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys.update(_flatten_keys(value, path))
        elif isinstance(value, str):
            keys.add(path)
    return keys


def _load_locale(locale: str) -> dict[str, Any]:
    path = LOCALES_DIR / f"{locale}.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _scan_used_keys() -> set[str]:
    used: set[str] = set()
    for root in FRONTEND_SCAN_DIRS:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix not in {".tsx", ".ts"}:
                continue
            if "node_modules" in path.parts or path.name == "i18n.ts":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for match in T_KEY_PATTERN.finditer(text):
                used.add(match.group(1))
    return used


class I18nHealthService:
    @staticmethod
    def check() -> dict[str, Any]:
        base = _load_locale("ru")
        base_keys = _flatten_keys(base)
        missing_keys: dict[str, list[str]] = {}
        for locale in SUPPORTED:
            if locale == "ru":
                continue
            locale_keys = _flatten_keys(_load_locale(locale))
            missing = sorted(base_keys - locale_keys)
            if missing:
                missing_keys[locale] = missing

        used_keys = _scan_used_keys()
        all_locale_keys = set()
        for locale in SUPPORTED:
            all_locale_keys.update(_flatten_keys(_load_locale(locale)))

        unused_keys = sorted(all_locale_keys - used_keys)
        translated_keys_count = {
            locale: len(_flatten_keys(_load_locale(locale)))
            for locale in SUPPORTED
        }

        for locale, keys in missing_keys.items():
            for key in keys[:5]:
                log_key = f"{locale}:{key}"
                if log_key not in _missing_logged:
                    _missing_logged.add(log_key)
                    logger.warning("[I18N] missing key: %s (locale=%s)", key, locale)

        return {
            "missing_keys": missing_keys,
            "unused_keys": unused_keys,
            "translated_keys_count": translated_keys_count,
            "canonical_locale": "ru",
            "used_keys_count": len(used_keys),
        }
