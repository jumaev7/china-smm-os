"""Market Intelligence — service layer for future trade data integrations."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.business_matching import BusinessMatchingTrendPoint
from app.schemas.buyer_crm import DistributionItem


class MarketIntelligenceService:
    """Placeholder service architecture for external trade data (no integrations yet)."""

    @staticmethod
    async def get_trade_data_summary(
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        country: str | None = None,
        industry: str | None = None,
    ) -> dict:
        return {
            "status": "placeholder",
            "message": "Trade data integration pending",
            "country": country,
            "industry": industry,
            "tenant_scoped": tenant_id is not None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    async def get_import_export_statistics(
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        country: str | None = None,
    ) -> dict:
        return {
            "status": "placeholder",
            "imports_usd": None,
            "exports_usd": None,
            "period": "latest",
            "country": country,
            "note": "Connect external trade API for live statistics",
        }

    @staticmethod
    async def get_industry_trends(
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        limit: int = 6,
    ) -> list[BusinessMatchingTrendPoint]:
        """Return synthetic trend points until external data is connected."""
        now = datetime.now(timezone.utc)
        points: list[BusinessMatchingTrendPoint] = []
        for i in range(limit):
            month = now.month - (limit - 1 - i)
            year = now.year
            while month <= 0:
                month += 12
                year -= 1
            points.append(BusinessMatchingTrendPoint(
                period=f"{year:04d}-{month:02d}",
                count=max(0, 3 + i * 2 + (i % 3)),
            ))
        return points

    @staticmethod
    async def get_market_demand_analysis(
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        product_category: str | None = None,
        country: str | None = None,
    ) -> dict:
        return {
            "status": "placeholder",
            "demand_index": None,
            "growth_rate_pct": None,
            "product_category": product_category,
            "country": country,
            "recommendation": "Enable market data provider for demand forecasting",
        }

    @staticmethod
    async def get_top_markets(
        db: AsyncSession,
        tenant_id: UUID | None,
    ) -> list[DistributionItem]:
        """Static Central Asia focus until live data is available."""
        return [
            DistributionItem(label="Uzbekistan", count=42),
            DistributionItem(label="Kazakhstan", count=38),
            DistributionItem(label="Kyrgyzstan", count=22),
            DistributionItem(label="Tajikistan", count=15),
            DistributionItem(label="Turkmenistan", count=11),
        ]
