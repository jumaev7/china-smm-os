"""R1 no-behavior regression — registry schema must remain dormant.

Proves existing publish / retry paths do not create registry rows, do not
import the registry model into live services, and leave feature flags alone.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.core.config import settings
from app.models.publish_write_coordination_registry import (
    PublishWriteCoordinationRegistry,
)
from app.services import publish_resilience, publish_service
from app.services import publish_retry_command_executor as executor_mod
from app.services import publish_write_coordination as wc

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_NAME = "PublishWriteCoordinationRegistry"
REGISTRY_MODULE = "publish_write_coordination_registry"
REGISTRY_TABLE = "publish_write_coordination_registry"

# Live paths that must remain registry-unaware in R1.
LIVE_SERVICE_FILES = [
    BACKEND_ROOT / "app" / "services" / "publish_service.py",
    BACKEND_ROOT / "app" / "services" / "publish_resilience.py",
    BACKEND_ROOT / "app" / "services" / "publish_write_coordination.py",
    BACKEND_ROOT / "app" / "services" / "publish_retry_command_executor.py",
    BACKEND_ROOT / "app" / "services" / "publish_retry_command_claim_service.py",
    BACKEND_ROOT / "app" / "services" / "publish_retry_command_barrier_service.py",
    BACKEND_ROOT / "app" / "services" / "publish_retry_command_manual_resolution_service.py",
    BACKEND_ROOT / "app" / "services" / "publish_retry_command_service.py",
]


def _source_mentions_registry(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    hits = []
    for token in (REGISTRY_NAME, REGISTRY_MODULE, REGISTRY_TABLE):
        if token in src:
            hits.append(token)
    return hits


def test_feature_flag_unchanged_default_off():
    assert settings.PUBLISH_WRITE_COORDINATION_ENABLED is False
    assert wc.write_coordination_enabled() is False


def test_live_services_do_not_import_or_reference_registry():
    for path in LIVE_SERVICE_FILES:
        assert path.is_file(), f"missing {path}"
        hits = _source_mentions_registry(path)
        assert hits == [], f"{path.name} references registry tokens: {hits}"


def test_publish_service_module_has_no_registry_ast_import():
    src = (BACKEND_ROOT / "app" / "services" / "publish_service.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert REGISTRY_MODULE not in alias.name
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert REGISTRY_MODULE not in mod
            for alias in node.names:
                assert alias.name != REGISTRY_NAME


def test_publish_service_and_executor_callables_unchanged_surface():
    # Smoke: core entrypoints still exist; registry acquire APIs do not.
    assert hasattr(publish_service.PublishService, "publish_content")
    assert hasattr(publish_resilience.PublishResilienceService, "begin_attempt")
    assert not hasattr(wc, "acquire_write_authority")
    assert not hasattr(wc, "PublishWriteCoordinationRegistry")
    assert not hasattr(executor_mod, "acquire_write_authority")
    assert not hasattr(executor_mod, REGISTRY_NAME)


def test_registry_model_has_no_side_effect_helpers():
    forbidden = {
        "acquire",
        "acquire_write_authority",
        "mark_write_started",
        "record_success",
        "record_safe_failure",
        "record_ambiguous",
        "resolve_ambiguous",
        "supersede_for_new_intent",
        "release_or_expire",
    }
    members = {
        name
        for name, _ in inspect.getmembers(PublishWriteCoordinationRegistry)
        if not name.startswith("_")
    }
    assert forbidden.isdisjoint(members)


def test_existing_coordination_tests_do_not_construct_registry_rows():
    """Static proof: e2_2 fixture suite never creates registry rows."""
    e2_path = BACKEND_ROOT / "tests" / "test_publish_write_coordination_e2_2.py"
    src = e2_path.read_text(encoding="utf-8")
    assert REGISTRY_TABLE not in src
    assert REGISTRY_NAME not in src
    assert "build_logical_write_key" not in src


def test_build_logical_write_key_not_used_by_live_modules():
    """Pure helper may exist on the model module; live paths must not call it."""
    for path in LIVE_SERVICE_FILES:
        src = path.read_text(encoding="utf-8")
        assert "build_logical_write_key" not in src
