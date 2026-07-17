"""Brand Profile verification for Governed AI Content Adaptation.

Draft create/update, publish immutable versions, version history, wrong-tenant
404, field limits, and secret-pattern blocking.

Run from backend/:  python scripts/verify_brand_profiles.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["AI_PLATFORM_ENABLED"] = "true"
os.environ["AI_DEFAULT_PROVIDER"] = "mock"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


def main() -> int:
    import asyncio

    return asyncio.run(_run())


def _status_code(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None)


async def _run() -> int:
    from app.core.config import settings
    from app.core.database import (
        AsyncSessionLocal,
        ensure_content_optimizer_schema,
        ensure_governed_ai_schema,
        ensure_intelligence_schema,
        ensure_platform_event_bus_schema,
        ensure_publishing_intelligence_schema,
    )
    from app.models.tenant import Tenant, TenantUser
    from app.services.ai_content.brand_profile_service import (
        BrandProfileService,
        MAX_COMPANY_NAME,
        MAX_DESCRIPTION,
    )
    from app.services.auth_service import hash_password
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )

    settings.AI_PLATFORM_ENABLED = True
    settings.AI_DEFAULT_PROVIDER = "mock"

    await ensure_platform_event_bus_schema()
    await ensure_intelligence_schema()
    await ensure_publishing_intelligence_schema()
    await ensure_content_optimizer_schema()
    await ensure_governed_ai_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(id=uuid4(), company_name=f"Brand A {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Brand B {stamp}", status="active", plan="trial")
        user_a = TenantUser(
            id=uuid4(),
            tenant_id=tenant_a.id,
            email=f"brand-a-{stamp}@example.com",
            password_hash=hash_password("test1234"),
            role="owner",
            status="active",
        )
        db.add_all([tenant_a, tenant_b])
        await db.commit()
        db.add(user_a)
        await db.commit()

        profile = await BrandProfileService.create_profile(
            db,
            tenant_a.id,
            name=f"Draft Brand {stamp}",
            draft={
                "locale": "en",
                "company_name": "Acme Steel",
                "company_description": "Export manufacturer",
                "audience_description": "B2B buyers",
                "tone_traits": ["professional"],
                "preferred_terms": ["export-ready"],
                "forbidden_terms": ["cheap"],
            },
            created_by=user_a.id,
        )
        await db.commit()
        record("draft_create", profile.status == "draft" and profile.draft_version == 1)

        updated = await BrandProfileService.update_draft(
            db,
            tenant_a.id,
            profile.id,
            draft={
                "locale": "en",
                "company_name": "Acme Steel Co",
                "company_description": "Export manufacturer updated",
                "tone_traits": ["professional", "clear"],
            },
            expected_draft_version=1,
        )
        await db.commit()
        record("draft_update", updated.draft_version == 2, str(updated.draft_version))
        record(
            "draft_company_name_updated",
            (updated.draft_payload or {}).get("company_name") == "Acme Steel Co",
        )

        v1 = await BrandProfileService.publish(db, tenant_a.id, profile.id, created_by=user_a.id)
        await db.commit()
        record("publish_v1", v1.version == 1 and v1.company_name == "Acme Steel Co")
        immutable_name = v1.company_name
        immutable_id = v1.id

        # Update draft and publish again — v1 must stay immutable
        await BrandProfileService.update_draft(
            db,
            tenant_a.id,
            profile.id,
            draft={
                "locale": "en",
                "company_name": "Acme Steel Renamed",
                "company_description": "New description",
                "tone_traits": ["bold"],
            },
        )
        v2 = await BrandProfileService.publish(db, tenant_a.id, profile.id, created_by=user_a.id)
        await db.commit()
        record("publish_v2", v2.version == 2 and v2.company_name == "Acme Steel Renamed")

        still_v1 = await BrandProfileService.get_version(
            db, tenant_a.id, profile.id, immutable_id,
        )
        record(
            "publish_immutable_v1",
            still_v1.company_name == immutable_name and still_v1.version == 1,
        )

        versions = await BrandProfileService.list_versions(db, tenant_a.id, profile.id)
        record("version_history_count", len(versions) == 2, str(len(versions)))
        record(
            "version_history_ordered",
            [v.version for v in versions] == [2, 1],
            str([v.version for v in versions]),
        )

        wrong_tenant = False
        try:
            await BrandProfileService.get_profile(db, tenant_b.id, profile.id)
        except Exception as exc:
            wrong_tenant = _status_code(exc) == 404
        record("wrong_tenant_profile_404", wrong_tenant)

        wrong_version = False
        try:
            await BrandProfileService.get_version(db, tenant_b.id, profile.id, v2.id)
        except Exception as exc:
            wrong_version = _status_code(exc) == 404
        record("wrong_tenant_version_404", wrong_version)

        # Field limits
        too_long = False
        try:
            await BrandProfileService.create_profile(
                db,
                tenant_a.id,
                name=f"Long {stamp}",
                draft={
                    "locale": "en",
                    "company_name": "X" * (MAX_COMPANY_NAME + 5),
                    "company_description": "ok",
                },
            )
        except Exception:
            too_long = True
        record("field_limit_company_name", too_long)

        too_long_desc = False
        try:
            await BrandProfileService.update_draft(
                db,
                tenant_a.id,
                profile.id,
                draft={
                    "locale": "en",
                    "company_name": "Ok",
                    "company_description": "Y" * (MAX_DESCRIPTION + 10),
                },
            )
        except Exception:
            too_long_desc = True
        record("field_limit_description", too_long_desc)

        # Secret patterns blocked
        secret_blocked = False
        try:
            await BrandProfileService.create_profile(
                db,
                tenant_a.id,
                name=f"Secret {stamp}",
                draft={
                    "locale": "en",
                    "company_name": "Acme",
                    "company_description": "Our api_key is sk-abcdefghijklmnopqrstuvwxyz123456",
                },
            )
        except Exception as exc:
            code = _status_code(exc)
            detail = getattr(exc, "detail", None)
            if code == 422 or (
                isinstance(detail, dict) and "SAFETY" in str(detail.get("code", "")).upper()
            ):
                secret_blocked = True
            elif "secret" in str(exc).lower() or "SAFETY" in str(exc):
                secret_blocked = True
        record("secret_patterns_blocked", secret_blocked)

        password_blocked = False
        try:
            await BrandProfileService.create_profile(
                db,
                tenant_a.id,
                name=f"Pwd {stamp}",
                draft={
                    "locale": "en",
                    "company_name": "Acme",
                    "company_description": "password: hunter2",
                },
            )
        except Exception:
            password_blocked = True
        record("password_pattern_blocked", password_blocked)

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
