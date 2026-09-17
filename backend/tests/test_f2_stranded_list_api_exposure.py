"""F2 — stranded list API exposure safety.

PUBLISH_RETRY_STRANDED_LIST_API_ENABLED defaults false. When disabled,
GET /retry-commands/stranded returns HTTP 404 without detector calls,
stranded SELECTs, alert writes, or commits. Independent of alert surfacing.
Does not alter GET /{id} or POST /{id}/resolve.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.schemas.publishing import (
    PublishRetryCommandResolveRequest,
    StrandedRetryCommandListResponse,
)
from app.services.publish_retry_command_manual_resolution_service import (
    ACTION_MARK_AMBIGUOUS,
    PublishRetryCommandManualResolutionService,
)
from app.services.publish_retry_command_stranded_detector import (
    PublishRetryCommandStrandedDetector,
)

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.production.yml"
PUBLISHING_API = "app.api.v1.publishing"


def _stranded_list_payload(*, alert_enabled: bool = False, total: int = 0):
    return {
        "items": [],
        "total": total,
        "page": 1,
        "page_size": 20,
        "quiet_period": {
            "lease_seconds": 180,
            "drain_seconds": 60,
            "provider_slack_seconds": 300,
            "safety_buffer_seconds": 120,
            "quiet_period_seconds": 600,
            "formula": "x",
            "heuristic_only": True,
            "authorizes_provider_write": False,
        },
        "alert_surfacing_enabled": alert_enabled,
        "alerts_created": 0,
        "alerts_updated": 0,
        "phase_e": "stranded_post_barrier",
        "read_only_commands": True,
    }


# ── A / B / N — flag defaults + compose pin ──────────────────────────────────


def test_a_list_api_flag_defaults_false():
    assert (
        type(settings).model_fields[
            "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED"
        ].default
        is False
    )
    assert settings.PUBLISH_RETRY_STRANDED_LIST_API_ENABLED is False


def test_b_explicit_false_returns_404(monkeypatch):
    monkeypatch.setattr(settings, "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED", False)
    from app.api.v1 import publishing as pub

    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    detector = AsyncMock(
        side_effect=AssertionError("detector must not run when list API disabled"),
    )

    async def _run():
        with patch.object(
            PublishRetryCommandStrandedDetector, "list_stranded", detector,
        ):
            with pytest.raises(HTTPException) as exc:
                await pub.list_stranded_retry_commands(
                    page=1,
                    page_size=20,
                    tenant_id=uuid.uuid4(),
                    db=db,
                    user=SimpleNamespace(tenant_id=uuid.uuid4(), id=uuid.uuid4()),
                    admin=None,
                )
            assert exc.value.status_code == 404
            assert "Not found" in str(exc.value.detail)

    asyncio.run(_run())
    detector.assert_not_awaited()
    db.execute.assert_not_called()
    db.commit.assert_not_awaited()


def test_n_production_compose_pins_list_api_false():
    text_src = COMPOSE.read_text(encoding="utf-8")
    assert "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED" in text_src
    assert "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED:-false" in text_src
    assert "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED:-true" not in text_src


def test_n_compose_resolved_default_is_false():
    """Prefer docker compose config when available; else static pin proof."""
    if not shutil.which("docker"):
        pytest.skip("docker not available for compose config check")

    env = {
        **os.environ,
        "DATABASE_URL": "postgresql://u:p@localhost/db",
        "SECRET_KEY": "x",
        "ADMIN_SECRET_KEY": "x",
        "TENANT_SECRET_KEY": "x",
        "S3_BUCKET": "b",
        "S3_ENDPOINT_URL": "http://localhost",
        "S3_ACCESS_KEY": "k",
        "S3_SECRET_KEY": "s",
        "OPENAI_API_KEY": "k",
        "TELEGRAM_BOT_TOKEN": "t",
        "TELEGRAM_ADMIN_ID": "1",
        "TELEGRAM_WEBHOOK_SECRET": "s",
        "META_APP_ID": "1",
        "META_APP_SECRET": "s",
        "LISTENING_META_WEBHOOK_VERIFY_TOKEN": "t",
        "POSTGRES_PASSWORD": "p",
    }
    # Ensure ambient env cannot force the flag true for this resolution.
    env.pop("PUBLISH_RETRY_STRANDED_LIST_API_ENABLED", None)

    try:
        proc = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE), "config"],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"docker compose config unavailable: {exc}")

    if proc.returncode != 0:
        pytest.skip(f"docker compose config failed: {proc.stderr}")

    out = proc.stdout
    assert "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED" in out
    # Resolved value must be the string false (compose YAML).
    assert "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED: \"false\"" in out or (
        "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED: false" in out
    )
    assert "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED: \"true\"" not in out
    assert "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED: true" not in out


# ── C / D / E / F — disabled: zero detector / SELECT / alert / commit ────────


def test_cde_f_disabled_zero_detector_select_alert_commit(monkeypatch):
    monkeypatch.setattr(settings, "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED", False)
    monkeypatch.setattr(settings, "PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED", True)
    from app.api.v1 import publishing as pub

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=AssertionError("no stranded SELECT when list API disabled"),
    )
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    detector = AsyncMock(
        side_effect=AssertionError("detector must not run when list API disabled"),
    )
    alert = AsyncMock(
        side_effect=AssertionError("alert path must not run when list API disabled"),
    )
    resolve_scope = MagicMock(
        side_effect=AssertionError("scope resolve must not run when list API disabled"),
    )

    async def _run():
        with (
            patch.object(
                PublishRetryCommandStrandedDetector, "list_stranded", detector,
            ),
            patch.object(pub, "_resolve_scope", resolve_scope),
            patch(
                "app.services.publish_operator_alert_service"
                ".PublishOperatorAlertService.upsert_stranded_post_barrier_alert",
                alert,
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await pub.list_stranded_retry_commands(
                    page=1,
                    page_size=20,
                    tenant_id=uuid.uuid4(),
                    db=db,
                    user=SimpleNamespace(
                        tenant_id=uuid.uuid4(), id=uuid.uuid4(), role="owner",
                    ),
                    admin=None,
                )
            assert exc.value.status_code == 404
            # No command identifiers / tenant payload in disabled response.
            detail = str(exc.value.detail).lower()
            assert "command" not in detail
            assert "tenant" not in detail
            assert "stranded" not in detail

    asyncio.run(_run())
    detector.assert_not_awaited()
    resolve_scope.assert_not_called()
    alert.assert_not_awaited()
    db.execute.assert_not_called()
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


# ── G / H / I / J — enabled auth + tenant isolation ──────────────────────────


def test_g_enabled_authorized_tenant_returns_existing_shape(monkeypatch):
    monkeypatch.setattr(settings, "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED", False)
    from app.api.v1 import publishing as pub

    tenant_id = uuid.uuid4()
    payload = _stranded_list_payload(alert_enabled=False, total=2)
    db = AsyncMock()
    db.commit = AsyncMock()

    async def _run():
        with (
            patch.object(pub, "_resolve_scope", return_value=tenant_id) as scope,
            patch.object(
                PublishRetryCommandStrandedDetector,
                "list_stranded",
                AsyncMock(return_value=payload),
            ) as detector,
        ):
            result = await pub.list_stranded_retry_commands(
                page=1,
                page_size=20,
                tenant_id=None,
                db=db,
                user=SimpleNamespace(tenant_id=tenant_id, id=uuid.uuid4(), role="owner"),
                admin=None,
            )
            scope.assert_called_once()
            detector.assert_awaited_once()
            kwargs = detector.await_args.kwargs
            assert kwargs["tenant_id"] == tenant_id
            return result

    result = asyncio.run(_run())
    assert isinstance(result, StrandedRetryCommandListResponse)
    assert result.total == 2
    assert result.alert_surfacing_enabled is False
    assert result.phase_e == "stranded_post_barrier"
    db.commit.assert_not_awaited()


def test_h_enabled_unauthorized_preserves_access_denial(monkeypatch):
    monkeypatch.setattr(settings, "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED", True)
    from app.api.v1 import publishing as pub

    db = AsyncMock()
    detector = AsyncMock()

    async def _run():
        with patch.object(
            PublishRetryCommandStrandedDetector, "list_stranded", detector,
        ):
            with pytest.raises(HTTPException) as exc:
                await pub.list_stranded_retry_commands(
                    page=1,
                    page_size=20,
                    tenant_id=uuid.uuid4(),
                    db=db,
                    user=None,
                    admin=None,
                )
            assert exc.value.status_code == 401

    asyncio.run(_run())
    detector.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_i_enabled_cross_tenant_no_leakage(monkeypatch):
    monkeypatch.setattr(settings, "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED", True)
    from app.api.v1 import publishing as pub

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    db = AsyncMock()
    detector = AsyncMock()

    async def _run():
        with patch.object(
            PublishRetryCommandStrandedDetector, "list_stranded", detector,
        ):
            with pytest.raises(HTTPException) as exc:
                await pub.list_stranded_retry_commands(
                    page=1,
                    page_size=20,
                    tenant_id=tenant_b,
                    db=db,
                    user=SimpleNamespace(
                        tenant_id=tenant_a, id=uuid.uuid4(), role="owner",
                    ),
                    admin=None,
                )
            assert exc.value.status_code == 403

    asyncio.run(_run())
    detector.assert_not_awaited()


def test_j_enabled_admin_without_tenant_id_rejected(monkeypatch):
    monkeypatch.setattr(settings, "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED", True)
    from app.api.v1 import publishing as pub

    db = AsyncMock()
    detector = AsyncMock()

    async def _run():
        with patch.object(
            PublishRetryCommandStrandedDetector, "list_stranded", detector,
        ):
            with pytest.raises(HTTPException) as exc:
                await pub.list_stranded_retry_commands(
                    page=1,
                    page_size=20,
                    tenant_id=None,
                    db=db,
                    user=None,
                    admin=SimpleNamespace(id=uuid.uuid4(), role="platform_admin"),
                )
            assert exc.value.status_code == 400
            assert "tenant_id" in str(exc.value.detail)

    asyncio.run(_run())
    detector.assert_not_awaited()


# ── K / L — sibling routes unchanged ─────────────────────────────────────────


def test_k_get_by_id_behavior_unchanged():
    """GET /retry-commands/{id} has no list-API gate and keeps auth/tenant path."""
    from app.api.v1 import publishing as pub

    src = inspect.getsource(pub.get_publish_retry_command)
    assert "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED" not in src
    assert "_require_stranded_list_api_enabled" not in src
    assert "_resolve_scope" in src

    command_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    command = SimpleNamespace(
        id=command_id,
        tenant_id=tenant_id,
        status="queued",
        original_attempt_id=uuid.uuid4(),
        resulting_attempt_id=None,
        content_id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        platform="facebook",
        destination_id="dest",
        idempotency_key="k",
        source="admin",
        created_at=None,
        updated_at=None,
        claimed_at=None,
        lease_owner=None,
        lease_expires_at=None,
        provider_write_started_at=None,
        provider_outcome=None,
        finished_at=None,
        failure_code=None,
        failure_message=None,
    )
    db = AsyncMock()

    async def _run():
        with (
            patch.object(pub, "_resolve_scope", return_value=tenant_id),
            patch(
                "app.services.publish_retry_command_service"
                ".PublishRetryCommandService.get_command",
                AsyncMock(return_value=command),
            ) as get_cmd,
            patch(
                "app.api.v1.publishing.serialize_retry_command",
                return_value={"id": str(command_id), "status": "queued"},
            ),
        ):
            result = await pub.get_publish_retry_command(
                command_id=command_id,
                tenant_id=None,
                db=db,
                user=SimpleNamespace(tenant_id=tenant_id, id=uuid.uuid4()),
                admin=None,
            )
            get_cmd.assert_awaited_once()
            return result

    result = asyncio.run(_run())
    assert result["status"] == "queued"


def test_l_resolve_remains_disabled_under_false_e2_flags(monkeypatch):
    monkeypatch.setattr(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED", False)
    monkeypatch.setattr(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", False)
    # List flag must not unlock resolve.
    monkeypatch.setattr(settings, "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED", True)

    from app.api.v1 import publishing as pub

    src = inspect.getsource(pub.resolve_publish_retry_command)
    assert "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED" not in src

    db = AsyncMock()

    async def _run():
        with pytest.raises(HTTPException) as exc:
            await PublishRetryCommandManualResolutionService.resolve(
                db,
                command_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                action=ACTION_MARK_AMBIGUOUS,
                confirm_permanent_resolution=True,
                operator_reason="stranded review",
                actor_id=uuid.uuid4(),
            )
        assert exc.value.status_code == 403
        db.execute.assert_not_called()

    asyncio.run(_run())


# ── M — list vs alert flag independence ──────────────────────────────────────


def test_m_list_and_alert_flags_independent(monkeypatch):
    from app.api.v1 import publishing as pub

    # 1) List false + alert true → still 404, no alert writes.
    monkeypatch.setattr(settings, "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED", False)
    monkeypatch.setattr(settings, "PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED", True)
    db = AsyncMock()
    db.commit = AsyncMock()
    detector = AsyncMock()

    async def _disabled():
        with patch.object(
            PublishRetryCommandStrandedDetector, "list_stranded", detector,
        ):
            with pytest.raises(HTTPException) as exc:
                await pub.list_stranded_retry_commands(
                    page=1,
                    page_size=20,
                    tenant_id=uuid.uuid4(),
                    db=db,
                    user=None,
                    admin=MagicMock(),
                )
            assert exc.value.status_code == 404

    asyncio.run(_disabled())
    detector.assert_not_awaited()
    db.commit.assert_not_awaited()

    # 2) List true + alert false → read-only listing (no commit).
    monkeypatch.setattr(settings, "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED", False)
    payload = _stranded_list_payload(alert_enabled=False)
    db2 = AsyncMock()
    db2.commit = AsyncMock()

    async def _readonly():
        with (
            patch.object(pub, "_resolve_scope", return_value=uuid.uuid4()),
            patch.object(
                PublishRetryCommandStrandedDetector,
                "list_stranded",
                AsyncMock(return_value=payload),
            ),
        ):
            result = await pub.list_stranded_retry_commands(
                page=1,
                page_size=20,
                tenant_id=uuid.uuid4(),
                db=db2,
                user=None,
                admin=MagicMock(),
            )
            return result

    result = asyncio.run(_readonly())
    assert result.alert_surfacing_enabled is False
    db2.commit.assert_not_awaited()

    # 3) List true + alert true → existing commit-on-write behavior preserved.
    monkeypatch.setattr(settings, "PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED", True)
    write_payload = dict(_stranded_list_payload(alert_enabled=True))
    write_payload["alerts_created"] = 1
    db3 = AsyncMock()
    db3.commit = AsyncMock()

    async def _alert_on():
        with (
            patch.object(pub, "_resolve_scope", return_value=uuid.uuid4()),
            patch.object(
                PublishRetryCommandStrandedDetector,
                "list_stranded",
                AsyncMock(return_value=write_payload),
            ),
        ):
            await pub.list_stranded_retry_commands(
                page=1,
                page_size=20,
                tenant_id=uuid.uuid4(),
                db=db3,
                user=None,
                admin=MagicMock(),
            )

    asyncio.run(_alert_on())
    db3.commit.assert_awaited_once()

    # Enabling list must not imply alert default becomes true.
    assert (
        type(settings).model_fields[
            "PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED"
        ].default
        is False
    )


# ── O / route order / no provider or execution ───────────────────────────────


def test_o_no_provider_or_retry_execution_in_gate():
    from app.api.v1 import publishing as pub

    src = inspect.getsource(pub.list_stranded_retry_commands)
    gate_src = inspect.getsource(pub._require_stranded_list_api_enabled)
    combined = src + gate_src
    for bad in (
        "PublishRetryCommandExecutor",
        "PublishRetryCommandClaimService",
        "execute_command",
        "begin_attempt",
        "publish_content",
        "httpx",
    ):
        assert bad not in combined


def test_stranded_literal_route_registered_before_dynamic_id():
    from app.api.v1 import publishing as pub

    src = Path(pub.__file__).read_text(encoding="utf-8")
    stranded_idx = src.index('/retry-commands/stranded"')
    by_id_idx = src.index('/retry-commands/{command_id}"')
    resolve_idx = src.index('/retry-commands/{command_id}/resolve"')
    assert stranded_idx < by_id_idx < resolve_idx
    assert "_require_stranded_list_api_enabled()" in src


def test_gate_helper_is_404_not_auth_bypass():
    from app.api.v1 import publishing as pub

    # Enabled path still uses shared scope (JWT/tenant); gate only hides when off.
    list_src = inspect.getsource(pub.list_stranded_retry_commands)
    assert "_require_stranded_list_api_enabled()" in list_src
    assert "_resolve_scope(user, admin, tenant_id)" in list_src
    # Gate precedes scope so disabled never resolves tenant / queries.
    assert list_src.index("_require_stranded_list_api_enabled()") < list_src.index(
        "_resolve_scope(user, admin, tenant_id)"
    )

    with patch.object(settings, "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED", False):
        with pytest.raises(HTTPException) as exc:
            pub._require_stranded_list_api_enabled()
        assert exc.value.status_code == 404

    with patch.object(settings, "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED", True):
        pub._require_stranded_list_api_enabled()  # no raise


def test_default_false_does_not_alter_other_flag_defaults():
    fields = type(settings).model_fields
    assert fields["PUBLISH_RETRY_STRANDED_LIST_API_ENABLED"].default is False
    assert fields["PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED"].default is False
    assert fields["PUBLISH_RETRY_STRANDED_SCANNER_ENABLED"].default is False
    assert fields["PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED"].default is False
    assert fields["PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED"].default is False
    assert fields["PUBLISH_WRITE_COORDINATION_ENABLED"].default is False
    assert fields["PUBLISH_WRITE_COORDINATION_SHADOW"].default is False
    assert fields["PUBLISH_RETRY_COMMANDS_ENABLED"].default is False
    assert fields["PUBLISH_RETRY_COMMAND_CLAIM_ENABLED"].default is False
    assert fields["PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED"].default is False
