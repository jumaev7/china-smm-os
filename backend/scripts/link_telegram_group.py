"""
Link a Telegram group chat ID to an existing CRM client (tenant intake group).

Usage:
  python scripts/link_telegram_group.py --client-id <uuid> --chat-id -1001234567890
  python scripts/link_telegram_group.py --client-id <uuid> --chat-id -1001234567890 --title "My Group"
  python scripts/link_telegram_group.py --list-clients
  python scripts/link_telegram_group.py --list-groups

Clears the same telegram_group_id from auto-created placeholder clients so ingestion
routes to the linked tenant client.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.client import Client


async def list_clients() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Client).order_by(Client.company_name))
        for c in result.scalars().all():
            print(
                f"{c.id} | {c.company_name} | tenant={c.tenant_id} "
                f"| tg_group={c.telegram_group_id} | mode={c.telegram_workflow_mode}"
            )


async def list_groups() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Client).where(Client.telegram_group_id.isnot(None)).order_by(Client.telegram_group_id)
        )
        for c in result.scalars().all():
            print(
                f"chat={c.telegram_group_id} | {c.company_name} ({c.id}) "
                f"| tenant={c.tenant_id} | mode={c.telegram_workflow_mode}"
            )


async def link_group(
    *,
    client_id: UUID,
    chat_id: str,
    title: str | None,
    workflow_mode: str,
    clear_placeholders: bool,
) -> None:
    chat_id = chat_id.strip()
    async with AsyncSessionLocal() as db:
        client = await db.get(Client, client_id)
        if not client:
            raise SystemExit(f"Client not found: {client_id}")

        if clear_placeholders:
            result = await db.execute(
                select(Client).where(
                    Client.telegram_group_id == chat_id,
                    Client.id != client_id,
                )
            )
            for other in result.scalars().all():
                print(f"Clearing telegram_group_id from placeholder: {other.company_name} ({other.id})")
                other.telegram_group_id = None
                other.telegram_group_title = None

        client.telegram_group_id = chat_id
        if title:
            client.telegram_group_title = title.strip()
        client.telegram_workflow_mode = workflow_mode

        await db.commit()
        print(
            f"Linked chat_id={chat_id} -> client '{client.company_name}' ({client.id})\n"
            f"  tenant_id={client.tenant_id}\n"
            f"  workflow_mode={client.telegram_workflow_mode}\n"
            f"  title={client.telegram_group_title}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Link Telegram group to CRM client")
    parser.add_argument("--client-id", type=str, help="CRM client UUID")
    parser.add_argument("--chat-id", type=str, help="Telegram group chat ID (e.g. -1001234567890)")
    parser.add_argument("--title", type=str, default=None, help="Group title for display")
    parser.add_argument(
        "--mode",
        type=str,
        default="auto_create_from_media",
        choices=["auto_create_from_media", "admin_controlled_buffer"],
    )
    parser.add_argument("--no-clear-placeholders", action="store_true")
    parser.add_argument("--list-clients", action="store_true")
    parser.add_argument("--list-groups", action="store_true")
    args = parser.parse_args()

    if args.list_clients:
        asyncio.run(list_clients())
        return
    if args.list_groups:
        asyncio.run(list_groups())
        return

    if not args.client_id or not args.chat_id:
        parser.error("--client-id and --chat-id are required (or use --list-clients / --list-groups)")

    asyncio.run(
        link_group(
            client_id=UUID(args.client_id),
            chat_id=args.chat_id,
            title=args.title,
            workflow_mode=args.mode,
            clear_placeholders=not args.no_clear_placeholders,
        )
    )


if __name__ == "__main__":
    main()
