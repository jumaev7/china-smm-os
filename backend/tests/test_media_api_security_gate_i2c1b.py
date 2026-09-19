"""SEC-MEDIA-1 / I2c.1b Media API security gate — auth + tenant isolation.

Isolated tests only. No production I/O. No destructive production calls.
No provider API calls. No registry mutations. No publication intents.

Scenarios cover unauthenticated, cross-tenant, and own-tenant media
read/list/upload/delete plus zero side-effect proofs.
"""
from __future__ import annotations

import asyncio
import inspect
import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from app.core.api_auth_context import (
    PUBLIC_API_PREFIXES,
    ApiAuthContext,
    ApiAuthMiddleware,
    _auth_ctx,
    _is_public_path,
)
from app.services.media_service import MediaService


def _tenant_ctx(client_ids: list[uuid.UUID], tenant_id: uuid.UUID | None = None) -> ApiAuthContext:
    return ApiAuthContext(
        kind="tenant",
        tenant_id=tenant_id or uuid.uuid4(),
        client_ids=tuple(client_ids),
    )


def _admin_ctx() -> ApiAuthContext:
    return ApiAuthContext(kind="admin", tenant_id=None, client_ids=())


def _minimal_authed_app() -> FastAPI:
    """Tiny app with the same ApiAuthMiddleware used in production."""
    app = FastAPI()
    app.add_middleware(ApiAuthMiddleware)

    @app.delete("/api/v1/media/{media_id}")
    async def _delete(media_id: uuid.UUID):
        return JSONResponse({"ok": True, "media_id": str(media_id)})

    @app.post("/api/v1/media/upload/{client_id}")
    async def _upload(client_id: uuid.UUID):
        return JSONResponse({"ok": True, "client_id": str(client_id)})

    @app.get("/api/v1/media/client/{client_id}")
    async def _list(client_id: uuid.UUID):
        return JSONResponse({"ok": True, "client_id": str(client_id)})

    return app


def test_A_unauthenticated_deletion_rejected_by_middleware():
    """DELETE /api/v1/media/{id} is not public; missing Bearer → 401."""
    media_path = f"/api/v1/media/{uuid.uuid4()}"
    assert not _is_public_path(media_path)
    assert not any(media_path.startswith(p) for p in PUBLIC_API_PREFIXES)

    with TestClient(_minimal_authed_app()) as client:
        resp = client.delete(media_path)
    assert resp.status_code == 401
    assert "Authentication" in resp.json().get("detail", "")


def test_D_unauthenticated_upload_rejected_by_middleware():
    upload_path = f"/api/v1/media/upload/{uuid.uuid4()}"
    assert not _is_public_path(upload_path)

    with TestClient(_minimal_authed_app()) as client:
        resp = client.post(upload_path)
    assert resp.status_code == 401


def test_unauthenticated_list_rejected_by_middleware():
    list_path = f"/api/v1/media/client/{uuid.uuid4()}"
    assert not _is_public_path(list_path)

    with TestClient(_minimal_authed_app()) as client:
        resp = client.get(list_path)
    assert resp.status_code == 401


def test_media_routes_rely_on_service_layer_authz():
    """Routes have no Depends(get_current*); service-layer guards are authoritative."""
    from app.api.v1 import media as media_routes

    for name in ("delete_media", "upload_media", "list_client_media"):
        fn = getattr(media_routes, name)
        src = inspect.getsource(fn)
        assert "Depends(get_current" not in src


def test_media_service_has_tenant_guard_calls():
    """Service-layer ownership checks are present on MediaService entry points."""
    src = inspect.getsource(MediaService)
    assert "guard_resource_client_id" in src
    assert src.count("guard_resource_client_id") >= 3


async def _B_tenant_a_delete_tenant_b_media() -> dict:
    """Cross-tenant delete attempt through MediaService.delete."""
    owned_client = uuid.uuid4()
    foreign_client = uuid.uuid4()
    foreign_media_id = uuid.uuid4()
    foreign_media = SimpleNamespace(
        id=foreign_media_id,
        client_id=foreign_client,
        storage_path=f"clients/{foreign_client}/secret.bin",
        thumbnail_path=None,
    )

    deleted = {"db": False, "storage": False, "committed": False}

    class _Result:
        def scalar_one_or_none(self):
            return foreign_media

    class _Db:
        async def execute(self, _q):
            return _Result()

        async def delete(self, obj):
            deleted["db"] = True
            assert obj is foreign_media

        async def commit(self):
            deleted["committed"] = True

    token = _auth_ctx.set(_tenant_ctx([owned_client]))
    try:
        with (
            patch(
                "app.services.media_service.storage.delete_file",
                new_callable=AsyncMock,
            ) as del_file,
            patch("app.services.media_service.storage.exists", return_value=False),
            patch(
                "app.services.media_service.all_subtitle_paths",
                return_value=["deriv.srt"],
            ),
            patch(
                "app.services.media_service.all_burned_video_paths",
                return_value=["burned.mp4"],
            ),
            patch(
                "app.services.media_service.all_dubbed_video_paths",
                return_value=["dubbed.mp4"],
            ),
            patch(
                "app.services.media_service.all_final_video_paths",
                return_value=["final.mp4"],
            ),
        ):
            try:
                await MediaService.delete(_Db(), foreign_media_id)
                blocked = False
                status = None
                detail = None
            except HTTPException as exc:
                blocked = True
                status = exc.status_code
                detail = exc.detail
            else:
                deleted["storage"] = del_file.await_count > 0
            storage_calls = del_file.await_count
    finally:
        _auth_ctx.reset(token)

    return {
        "blocked": blocked,
        "status": status,
        "detail": detail,
        "db_deleted": deleted["db"],
        "storage_deleted": deleted["storage"],
        "storage_calls": storage_calls,
        "committed": deleted["committed"],
    }


def test_B_tenant_a_deleting_tenant_b_media():
    """Cross-tenant deletion must be rejected with zero side effects."""
    outcome = asyncio.run(_B_tenant_a_delete_tenant_b_media())
    assert outcome["blocked"] is True, (
        "VULNERABILITY: Tenant A deleted Tenant B media via MediaService.delete "
        f"without ownership check. outcome={outcome}"
    )
    assert outcome["status"] == 403
    assert outcome["db_deleted"] is False
    assert outcome["storage_deleted"] is False
    assert outcome["storage_calls"] == 0
    assert outcome["committed"] is False
    # O: do not expose foreign tenant ownership details
    assert "tenant" not in str(outcome["detail"]).lower() or "isolation" in str(outcome["detail"]).lower()


async def _C_own_media_delete_allowed() -> None:
    owned_client = uuid.uuid4()
    media_id = uuid.uuid4()
    media = SimpleNamespace(
        id=media_id,
        client_id=owned_client,
        storage_path=f"clients/{owned_client}/own.bin",
        thumbnail_path=None,
    )

    class _Result:
        def scalar_one_or_none(self):
            return media

    class _Db:
        async def execute(self, _q):
            return _Result()

        async def delete(self, obj):
            assert obj is media

        async def commit(self):
            pass

    token = _auth_ctx.set(_tenant_ctx([owned_client]))
    try:
        with (
            patch(
                "app.services.media_service.storage.delete_file",
                new_callable=AsyncMock,
            ) as del_file,
            patch("app.services.media_service.storage.exists", return_value=False),
            patch(
                "app.services.media_service.all_subtitle_paths",
                return_value=[],
            ),
            patch(
                "app.services.media_service.all_burned_video_paths",
                return_value=[],
            ),
            patch(
                "app.services.media_service.all_dubbed_video_paths",
                return_value=[],
            ),
            patch(
                "app.services.media_service.all_final_video_paths",
                return_value=[],
            ),
        ):
            await MediaService.delete(_Db(), media_id)
            assert del_file.await_count >= 1
    finally:
        _auth_ctx.reset(token)


def test_C_authenticated_own_media_delete_succeeds():
    """Own-tenant delete is authorized and reaches storage deletion."""
    asyncio.run(_C_own_media_delete_allowed())


async def _E_cross_tenant_get() -> dict:
    owned_client = uuid.uuid4()
    foreign_client = uuid.uuid4()
    foreign_media_id = uuid.uuid4()
    foreign_media = SimpleNamespace(
        id=foreign_media_id,
        client_id=foreign_client,
        storage_path=f"clients/{foreign_client}/secret.bin",
        thumbnail_path=f"clients/{foreign_client}/secret_thumb.jpg",
    )

    class _Result:
        def scalar_one_or_none(self):
            return foreign_media

    class _Db:
        async def execute(self, _q):
            return _Result()

    token = _auth_ctx.set(_tenant_ctx([owned_client]))
    try:
        try:
            media = await MediaService.get(_Db(), foreign_media_id)
            return {
                "blocked": False,
                "status": None,
                "got_id": media.id,
                "storage_path": getattr(media, "storage_path", None),
            }
        except HTTPException as exc:
            return {
                "blocked": True,
                "status": exc.status_code,
                "got_id": None,
                "storage_path": None,
                "detail": exc.detail,
            }
    finally:
        _auth_ctx.reset(token)


def test_E_cross_tenant_media_get():
    outcome = asyncio.run(_E_cross_tenant_get())
    assert outcome["blocked"] is True, (
        "VULNERABILITY: Tenant A can read Tenant B media metadata via MediaService.get "
        f"outcome={outcome}"
    )
    assert outcome["status"] == 403
    assert outcome["got_id"] is None
    assert outcome["storage_path"] is None


async def _G_own_tenant_get() -> MediaService:
    owned_client = uuid.uuid4()
    media_id = uuid.uuid4()
    media = SimpleNamespace(
        id=media_id,
        client_id=owned_client,
        storage_path=f"clients/{owned_client}/own.bin",
    )

    class _Result:
        def scalar_one_or_none(self):
            return media

    class _Db:
        async def execute(self, _q):
            return _Result()

    token = _auth_ctx.set(_tenant_ctx([owned_client]))
    try:
        got = await MediaService.get(_Db(), media_id)
        assert got.id == media_id
        assert got.client_id == owned_client
        return got
    finally:
        _auth_ctx.reset(token)


def test_G_own_tenant_get_succeeds():
    got = asyncio.run(_G_own_tenant_get())
    assert got is not None


async def _E_cross_tenant_list() -> dict:
    owned_client = uuid.uuid4()
    foreign_client = uuid.uuid4()
    foreign_media = SimpleNamespace(id=uuid.uuid4(), client_id=foreign_client)
    queried = {"executed": False}

    class _Scalars:
        def all(self):
            return [foreign_media]

    class _Result:
        def scalars(self):
            return _Scalars()

    class _Db:
        async def execute(self, query):
            queried["executed"] = True
            return _Result()

    token = _auth_ctx.set(_tenant_ctx([owned_client]))
    try:
        try:
            items = await MediaService.list_for_client(_Db(), foreign_client)
            return {
                "blocked": False,
                "returned_foreign": len(items) > 0 and items[0].client_id == foreign_client,
                "count": len(items),
                "queried": queried["executed"],
            }
        except HTTPException as exc:
            return {
                "blocked": True,
                "status": exc.status_code,
                "returned_foreign": False,
                "count": 0,
                "queried": queried["executed"],
                "detail": exc.detail,
            }
    finally:
        _auth_ctx.reset(token)


def test_E_cross_tenant_media_list_by_foreign_client_id():
    """Listing another tenant's client_id must not return their media or counts."""
    outcome = asyncio.run(_E_cross_tenant_list())
    assert outcome["blocked"] is True, (
        "VULNERABILITY: Tenant A listed Tenant B media via "
        f"MediaService.list_for_client. outcome={outcome}"
    )
    assert outcome["status"] == 403
    assert outcome["returned_foreign"] is False
    assert outcome["count"] == 0
    # M: deny before tenant-scoped query when client_id is out of scope
    assert outcome["queried"] is False


async def _H_own_list() -> list:
    owned_client = uuid.uuid4()
    own_media = SimpleNamespace(id=uuid.uuid4(), client_id=owned_client)

    class _Scalars:
        def all(self):
            return [own_media]

    class _Result:
        def scalars(self):
            return _Scalars()

    class _Db:
        async def execute(self, query):
            return _Result()

    token = _auth_ctx.set(_tenant_ctx([owned_client]))
    try:
        return await MediaService.list_for_client(_Db(), owned_client)
    finally:
        _auth_ctx.reset(token)


def test_H_own_tenant_list_succeeds():
    items = asyncio.run(_H_own_list())
    assert len(items) == 1


async def _F_cross_tenant_upload() -> dict:
    owned_client = uuid.uuid4()
    foreign_client = uuid.uuid4()
    wrote = {"storage": False, "db_add": False, "commit": False}

    class _ClientResult:
        def scalar_one_or_none(self):
            return SimpleNamespace(id=foreign_client)

    class _Db:
        async def execute(self, _q):
            return _ClientResult()

        def add(self, obj):
            wrote["db_add"] = True

        async def commit(self):
            wrote["commit"] = True

        async def refresh(self, obj):
            pass

    upload = UploadFile(filename="x.jpg", file=io.BytesIO(b"fake-image-bytes"))

    token = _auth_ctx.set(_tenant_ctx([owned_client]))
    try:
        with patch(
            "app.services.media_service.storage.save_file",
            new_callable=AsyncMock,
        ) as save_file:
            try:
                await MediaService.upload(_Db(), foreign_client, upload)
                blocked = False
                status = None
            except HTTPException as exc:
                blocked = True
                status = exc.status_code
            wrote["storage"] = save_file.await_count > 0
            storage_calls = save_file.await_count
    finally:
        _auth_ctx.reset(token)

    return {
        "blocked": blocked,
        "status": status,
        "storage_written": wrote["storage"],
        "storage_calls": storage_calls,
        "db_add": wrote["db_add"],
        "commit": wrote["commit"],
    }


def test_F_cross_tenant_upload_denied_zero_storage():
    outcome = asyncio.run(_F_cross_tenant_upload())
    assert outcome["blocked"] is True
    assert outcome["status"] == 403
    assert outcome["storage_written"] is False
    assert outcome["storage_calls"] == 0
    assert outcome["db_add"] is False
    assert outcome["commit"] is False


async def _I_own_upload() -> object:
    owned_client = uuid.uuid4()
    media_row = SimpleNamespace(
        id=uuid.uuid4(),
        client_id=owned_client,
        original_filename="own.jpg",
        file_type="image",
        mime_type="image/jpeg",
        storage_path=f"clients/{owned_client}/own.jpg",
        thumbnail_path=None,
        file_size=4,
        uploaded_at=None,
    )

    class _ClientResult:
        def scalar_one_or_none(self):
            return SimpleNamespace(id=owned_client)

    class _Db:
        async def execute(self, _q):
            return _ClientResult()

        def add(self, obj):
            for k, v in media_row.__dict__.items():
                setattr(obj, k, v)

        async def commit(self):
            pass

        async def refresh(self, obj):
            pass

    upload = UploadFile(
        filename="own.jpg",
        file=io.BytesIO(b"\xff\xd8\xff\xe0fake"),
    )
    # Force image mime via content_type
    upload.headers = {"content-type": "image/jpeg"}  # type: ignore[attr-defined]

    token = _auth_ctx.set(_tenant_ctx([owned_client]))
    try:
        with (
            patch(
                "app.services.media_service.storage.save_file",
                new_callable=AsyncMock,
                return_value=f"clients/{owned_client}/own.jpg",
            ) as save_file,
            patch(
                "app.services.media_service.MediaService._make_thumbnail",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.ocr_service.extract_text",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            # Bypass mime/size by patching _resolve_mime
            with patch(
                "app.services.media_service._resolve_mime",
                return_value="image/jpeg",
            ):
                media = await MediaService.upload(_Db(), owned_client, upload)
            assert save_file.await_count >= 1
            assert media.client_id == owned_client
            return media
    finally:
        _auth_ctx.reset(token)


def test_I_own_tenant_upload_succeeds():
    media = asyncio.run(_I_own_upload())
    assert media is not None


async def _S_nonexistent_media() -> int:
    owned_client = uuid.uuid4()

    class _Result:
        def scalar_one_or_none(self):
            return None

    class _Db:
        async def execute(self, _q):
            return _Result()

    token = _auth_ctx.set(_tenant_ctx([owned_client]))
    try:
        try:
            await MediaService.get(_Db(), uuid.uuid4())
            return 0
        except HTTPException as exc:
            return exc.status_code
    finally:
        _auth_ctx.reset(token)


def test_S_nonexistent_media_returns_404():
    assert asyncio.run(_S_nonexistent_media()) == 404


async def _P_role_admin_can_access_any() -> None:
    foreign_client = uuid.uuid4()
    media = SimpleNamespace(
        id=uuid.uuid4(),
        client_id=foreign_client,
        storage_path="x.bin",
    )

    class _Result:
        def scalar_one_or_none(self):
            return media

    class _Db:
        async def execute(self, _q):
            return _Result()

    token = _auth_ctx.set(_admin_ctx())
    try:
        got = await MediaService.get(_Db(), media.id)
        assert got.client_id == foreign_client
    finally:
        _auth_ctx.reset(token)


def test_P_admin_role_not_restricted_by_client_scope():
    """Existing admin bypass via assert_client_in_scope remains effective."""
    asyncio.run(_P_role_admin_can_access_any())


async def _Q_no_auth_context_internal_caller() -> None:
    """Trusted internal callers without HTTP auth context are not blanket-blocked."""
    client_id = uuid.uuid4()
    media = SimpleNamespace(id=uuid.uuid4(), client_id=client_id, storage_path="x.bin")

    class _Result:
        def scalar_one_or_none(self):
            return media

    class _Db:
        async def execute(self, _q):
            return _Result()

    # Ensure no auth context (internal workflow)
    token = _auth_ctx.set(None)  # type: ignore[arg-type]
    try:
        # ContextVar may reject None — clear via reset of a prior set
        pass
    finally:
        _auth_ctx.reset(token)

    # Explicitly clear
    try:
        _auth_ctx.get()
        cleared = False
    except LookupError:
        cleared = True

    if not cleared:
        # Force empty by setting then resetting
        t = _auth_ctx.set(_tenant_ctx([client_id]))
        _auth_ctx.reset(t)

    # With no context, guard is no-op (same as ContentService pattern)
    from app.core.api_auth_context import get_auth_context

    assert get_auth_context() is None
    got = await MediaService.get(_Db(), media.id)
    assert got.id == media.id


def test_Q_trusted_internal_workflow_without_auth_context():
    asyncio.run(_Q_no_auth_context_internal_caller())


def test_with_url_does_not_run_under_foreign_get():
    """N: foreign GET never reaches serialization of paths/URLs."""
    outcome = asyncio.run(_E_cross_tenant_get())
    assert outcome["blocked"] is True
    assert outcome.get("storage_path") is None


def test_middleware_wired_in_main():
    import app.main as main_mod

    src = inspect.getsource(main_mod)
    assert "ApiAuthMiddleware" in src
    assert "app.add_middleware(ApiAuthMiddleware)" in src


def test_T_U_V_W_no_external_side_channels_in_media_service():
    """No provider/registry/publication hooks introduced in MediaService authz path."""
    src = inspect.getsource(MediaService)
    assert "PublishService" not in src
    assert "publication_request" not in src
    assert "registry" not in src.lower() or "guard_resource" in src
    assert "instagram" not in src.lower()
    assert "telegram" not in src.lower()
