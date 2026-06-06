from __future__ import annotations

import argparse
import asyncio

from app.services.whatsapp_cloud_outbox import (
    WhatsAppCloudOutboxItem,
    close_outbox_redis_client,
    list_outbox_items,
)
from app.services.whatsapp_cloud_outbox_retry import retry_outbox_item


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect and retry WhatsApp Cloud outbox items")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List failed WhatsApp Cloud outbox items")
    list_parser.add_argument("--limit", type=int, default=20)

    retry_parser = subparsers.add_parser("retry", help="Retry one failed WhatsApp Cloud outbox item")
    retry_parser.add_argument("item_id")

    args = parser.parse_args()

    asyncio.run(_run_command(args))


async def _run_command(args: argparse.Namespace) -> None:
    try:
        if args.command == "list":
            await _list_items(args.limit)
            return

        if args.command == "retry":
            ok = await retry_outbox_item(args.item_id)
            if ok:
                print(f"retry ok item_id={args.item_id}")
            else:
                print(f"retry failed item_id={args.item_id}")
    finally:
        await close_outbox_redis_client()


async def _list_items(limit: int) -> None:
    items = await list_outbox_items(limit=limit)
    if not items:
        print("no outbox items")
        return

    for item in items:
        print(format_outbox_item(item))


def format_outbox_item(item: WhatsAppCloudOutboxItem) -> str:
    return (
        f"id={item.id} "
        f"client_id={item.client_id} "
        f"wa_id={mask_phone(item.wa_id)} "
        f"send_to={mask_phone(item.send_to)} "
        f"phone_number_id={item.phone_number_id} "
        f"message_id={item.message_id or ''} "
        f"created_at={item.created_at} "
        f"attempts={item.attempts} "
        f"last_error={_shorten(item.last_error, 160)}"
    )


def mask_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) <= 4:
        return "***"
    return f"***{digits[-4:]}"


def _shorten(value: str, limit: int) -> str:
    normalized = value.replace("\n", " ").replace("\r", " ").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


if __name__ == "__main__":
    main()
