"""Extensible export architecture for Factory Growth Center reports."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.growth_center import (
    ExportFormat,
    GrowthCenterDashboardResponse,
    GrowthCenterExportFormatInfo,
    GrowthCenterExportRequest,
    GrowthCenterExportResponse,
)

logger = logging.getLogger(__name__)
MARKER = "[Growth Center Export]"


class GrowthCenterExportProvider(ABC):
    """Base contract for Growth Center report exporters."""

    format: ExportFormat
    label: str
    mime_type: str
    description: str

    @abstractmethod
    async def export(
        self,
        db: AsyncSession,
        tenant_id: UUID | None,
        dashboard: GrowthCenterDashboardResponse,
        options: GrowthCenterExportRequest,
    ) -> GrowthCenterExportResponse:
        """Generate export artifact. Subclasses implement PDF/Excel generation."""


class GrowthCenterPdfExporter(GrowthCenterExportProvider):
    format = "pdf"
    label = "PDF Executive Report"
    mime_type = "application/pdf"
    description = "Executive summary PDF with KPIs, market insights, and opportunities."

    async def export(
        self,
        db: AsyncSession,
        tenant_id: UUID | None,
        dashboard: GrowthCenterDashboardResponse,
        options: GrowthCenterExportRequest,
    ) -> GrowthCenterExportResponse:
        logger.info(
            "%s PDF export requested tenant=%s locale=%s (stub)",
            MARKER,
            tenant_id,
            options.locale,
        )
        return GrowthCenterExportResponse(
            format="pdf",
            status="not_implemented",
            message=(
                "PDF export architecture is ready. Implement GrowthCenterPdfExporter.export "
                "using proposal_export_service patterns (reportlab/weasyprint)."
            ),
            filename=f"growth-center-report-{dashboard.generated_at.date()}.pdf",
        )


class GrowthCenterExcelExporter(GrowthCenterExportProvider):
    format = "excel"
    label = "Excel Workbook"
    mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    description = "Multi-sheet workbook with KPIs, distributions, and opportunity list."

    async def export(
        self,
        db: AsyncSession,
        tenant_id: UUID | None,
        dashboard: GrowthCenterDashboardResponse,
        options: GrowthCenterExportRequest,
    ) -> GrowthCenterExportResponse:
        logger.info(
            "%s Excel export requested tenant=%s locale=%s (stub)",
            MARKER,
            tenant_id,
            options.locale,
        )
        return GrowthCenterExportResponse(
            format="excel",
            status="not_implemented",
            message=(
                "Excel export architecture is ready. Implement GrowthCenterExcelExporter.export "
                "using openpyxl or xlsxwriter with sheet builders per dashboard section."
            ),
            filename=f"growth-center-report-{dashboard.generated_at.date()}.xlsx",
        )


class GrowthCenterExportService:
    """Registry and orchestrator for Growth Center report exports."""

    _providers: dict[ExportFormat, GrowthCenterExportProvider]

    def __init__(self) -> None:
        self._providers = {
            "pdf": GrowthCenterPdfExporter(),
            "excel": GrowthCenterExcelExporter(),
        }

    def register_provider(self, provider: GrowthCenterExportProvider) -> None:
        self._providers[provider.format] = provider

    def list_formats(self) -> list[GrowthCenterExportFormatInfo]:
        return [
            GrowthCenterExportFormatInfo(
                format=provider.format,
                label=provider.label,
                mime_type=provider.mime_type,
                available=False,
                description=provider.description,
            )
            for provider in self._providers.values()
        ]

    def get_provider(self, fmt: ExportFormat) -> GrowthCenterExportProvider:
        provider = self._providers.get(fmt)
        if not provider:
            raise ValueError(f"Unsupported export format: {fmt}")
        return provider

    async def export(
        self,
        db: AsyncSession,
        tenant_id: UUID | None,
        dashboard: GrowthCenterDashboardResponse,
        fmt: ExportFormat,
        options: GrowthCenterExportRequest | None = None,
    ) -> GrowthCenterExportResponse:
        provider = self.get_provider(fmt)
        return await provider.export(
            db,
            tenant_id,
            dashboard,
            options or GrowthCenterExportRequest(),
        )


growth_center_export_service = GrowthCenterExportService()
