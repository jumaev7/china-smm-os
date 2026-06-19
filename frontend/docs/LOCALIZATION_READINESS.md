# Localization Readiness Report — RU/ZH Business Localization v2

Generated: 2026-06-08

## Summary

| Metric | Value |
|--------|-------|
| Scoped locale keys (en) | ~450+ |
| New v2 namespaces | `systemStatus.*`, `production.*`, extended `dashboard.*` |
| Priority pages fully wired (UI labels) | 12 + sidebar |
| Pipeline stage maps localized | buyer-acquisition-engine, revenue-engine |
| Missing ru/zh keys (scoped) | 0 |

## Pages checked

1. `/dashboard`
2. `/executive-copilot`
3. `/factory-platform`
4. `/customer-portal-v2`
5. `/real-factory-pilot`
6. `/pilot-sales-demo`
7. `/pilot-launch-validation`
8. `/buyer-acquisition-engine`
9. `/revenue-engine`
10. `/deal-room`
11. `/production-deployment`
12. Sidebar navigation (`DashboardShell.tsx`)
13. `/pilot-execution` — route not present (N/A)

## Hardcoded labels fixed (v2)

- Dashboard: Sales Agent Recommendations, Lead Intelligence, Hot/Qualified/Nurturing/Cold/Inactive, View all, Open, system status (Running/Configured), 20+ module widgets
- Executive copilot: KPI bar, widget panels, section headers 2–6, quick links
- Factory platform: performance KPIs, revenue/buyer panels, catalog headers
- Customer portal v2: dashboard KPIs, table headers, opportunity sections
- Real factory pilot: sections 2–8, readiness panels
- Pilot sales demo / launch validation: metrics, section headers, hints
- Buyer acquisition engine: `PIPELINE_LABELS` → `buyer.stage*`
- Revenue engine: `STAGE_LABELS` → `revenue.stage*`
- Deal room: workspace panels (overview, pipeline, buyer, revenue, risk, documents, timeline)
- Production deployment: full page (was 100% English)

## RU terminology improvements (v2)

| Before | After |
|--------|-------|
| Дашборд | Панель управления |
| Копилот руководителя | AI-помощник руководителя |
| Сделочная комната | Центр сделок |
| Движок выручки (nav) | Аналитика выручки |
| Пилотная продажа | Презентация для продаж |
| Валидация пилотного… | Проверка готовности |
| Production Deployment | Подготовка к запуску |
| Hot/Qualified/Cold… | Горячие / Квалифицированные / Холодные / … |
| Running/Configured | Работает / Настроен |

## ZH terminology improvements (v2)

| Before | After |
|--------|-------|
| 仪表盘 | 管理总览 |
| 高管副驾驶 | AI经营助手 |
| 交易室 | 交易中心 |
| 收入引擎 | 收益分析中心 |
| 买家获取引擎 | 买家开发中心 |
| 线索情报 | 线索分析 |
| 试点发布验证 | 试点验证 |
| 生产部署 | 生产部署准备 |
| 流水线 | 销售管道 |
| Hot/Qualified… | 高意向 / 已筛选 / 培育中 / … |

## Remaining untranslated labels (non-blocking)

- Backend `safety_notice` strings (API payload, English)
- Dynamic AI briefing content and recommendation titles from API
- CRM/buyer-intelligence standalone pages (not in v2 priority list)
- Marketplace widget KPI label "Open" (English enum from API context)
- Country names, company names, deal titles (data, not UI chrome)
- Some English product names kept in EN mode by design (CRM, WhatsApp, Telegram)

## Files changed

- `frontend/lib/uiLabels.ts` (new)
- `frontend/locales/en.json`, `ru.json`, `zh.json`
- `frontend/app/(dashboard)/dashboard/page.tsx`
- `frontend/app/(dashboard)/executive-copilot/page.tsx`
- `frontend/app/(dashboard)/factory-platform/page.tsx`
- `frontend/app/(dashboard)/customer-portal-v2/page.tsx`
- `frontend/app/(dashboard)/real-factory-pilot/page.tsx`
- `frontend/app/(dashboard)/pilot-sales-demo/page.tsx`
- `frontend/app/(dashboard)/pilot-launch-validation/page.tsx`
- `frontend/app/(dashboard)/buyer-acquisition-engine/page.tsx`
- `frontend/app/(dashboard)/revenue-engine/page.tsx`
- `frontend/app/(dashboard)/deal-room/page.tsx`
- `frontend/app/(dashboard)/production-deployment/page.tsx`
- `PROJECT_STATUS.md`

## Verification

- `docker compose up -d --build` — OK (postgres, backend, frontend)
- `NODE_ENV=production npm run build` in frontend container — OK, 94 routes
- TypeScript strict check — pass
- RU/ZH priority pages — UI chrome localized; no obvious English on widget headers/KPIs
