"""Commercial Demo Factory Experience — tenant-accessible demo routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.commercial_demo import (
    DemoFactoryLoadResponse,
    DemoFactoryPackageId,
    DemoFactoryPackageList,
    DemoReadinessResponse,
    DemoTourResponse,
    ExecutiveDemoResponse,
    ExportGrowthStoryResponse,
    ProductPositioningResponse,
    ValueDemoResponse,
)
from app.services.commercial_demo_service import CommercialDemoService
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/commercial-demo", tags=["commercial-demo"])


@router.get("/packages", response_model=DemoFactoryPackageList)
async def list_demo_packages(
    _user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    return CommercialDemoService.list_packages()


@router.post("/packages/{package_id}/load", response_model=DemoFactoryLoadResponse)
async def load_demo_package(
    package_id: DemoFactoryPackageId,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await run_guarded(
            CommercialDemoService.load_factory_package(db, user.tenant_id, package_id),
            label="commercial_demo.load_package",
            timeout=30.0,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tour", response_model=DemoTourResponse)
async def get_demo_tour(
    _user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    return CommercialDemoService.get_tour()


@router.get("/export-growth-story", response_model=ExportGrowthStoryResponse)
async def get_export_growth_story(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        CommercialDemoService.get_export_growth_story(db, user.tenant_id),
        label="commercial_demo.export_growth_story",
    )


@router.get("/value-demo", response_model=ValueDemoResponse)
async def get_value_demo(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        CommercialDemoService.get_value_demo(db, user.tenant_id),
        label="commercial_demo.value_demo",
    )


@router.get("/executive-demo", response_model=ExecutiveDemoResponse)
async def get_executive_demo(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        CommercialDemoService.get_executive_demo(db, user.tenant_id),
        label="commercial_demo.executive_demo",
        timeout=25.0,
    )


@router.get("/positioning", response_model=ProductPositioningResponse)
async def get_product_positioning(
    _user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    return CommercialDemoService.get_product_positioning()


@router.get("/readiness", response_model=DemoReadinessResponse)
async def get_demo_readiness(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        CommercialDemoService.get_readiness_score(db, user.tenant_id),
        label="commercial_demo.readiness",
    )
