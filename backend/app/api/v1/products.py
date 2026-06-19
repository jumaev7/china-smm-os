from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.product import (
    ProductCreate,
    ProductImportResponse,
    ProductListResponse,
    ProductMatchLeadResponse,
    ProductResponse,
    ProductUpdate,
)
from app.services.product_catalog_service import ProductCatalogService

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=ProductListResponse)
async def list_products(
    client_id: UUID | None = None,
    category: str | None = None,
    search: str | None = None,
    active: bool | None = True,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ProductCatalogService.list_products(
            db,
            client_id=client_id,
            category=category,
            search=search,
            active=active,
            skip=skip,
            limit=limit,
        ),
        label="products.list",
    )


@router.post("", response_model=ProductResponse, status_code=201)
async def create_product(
    body: ProductCreate,
    db: AsyncSession = Depends(get_db),
):
    return await ProductCatalogService.create_product(db, body)


@router.post("/import", response_model=ProductImportResponse)
async def import_products(
    client_id: UUID = Form(...),
    source_type: str = Form(...),
    file: UploadFile | None = File(None),
    catalog_text: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ProductCatalogService.import_catalog(
            db,
            client_id=client_id,
            source_type=source_type,
            file=file,
            catalog_text=catalog_text,
        ),
        label="products.import",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/match-lead/{lead_id}", response_model=ProductMatchLeadResponse)
async def match_lead_products(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ProductCatalogService.match_lead(db, lead_id),
        label="products.match_lead",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/categories/list")
async def list_product_categories(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    categories = await ProductCatalogService.list_categories(db, client_id=client_id)
    return {"categories": categories}


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await ProductCatalogService.get_product(db, product_id)


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: UUID,
    body: ProductUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await ProductCatalogService.update_product(db, product_id, body)


@router.delete("/{product_id}", status_code=204)
async def delete_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    await ProductCatalogService.delete_product(db, product_id)
