from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from app.db.database import async_session_factory
from app.services import client_service


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bind a Meta Instagram webhook entry.id to an internal client"
    )
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--instagram-account-id", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the update. Without this flag the command only validates and prints the planned change.",
    )
    args = parser.parse_args()

    try:
        _validate_args(args.client_id, args.instagram_account_id)
        asyncio.run(_run(args.client_id, args.instagram_account_id, apply=args.apply))
    except ValueError as exc:
        print(f"invalid input: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


def _validate_args(client_id: str, instagram_account_id: str) -> None:
    try:
        uuid.UUID(client_id)
    except ValueError as exc:
        raise ValueError("client-id must be a UUID") from exc

    if not instagram_account_id.strip():
        raise ValueError("instagram-account-id is required")
    if not instagram_account_id.isdigit():
        raise ValueError("instagram-account-id must contain digits only")


async def _run(client_id: str, instagram_account_id: str, *, apply: bool) -> None:
    if async_session_factory is None:
        raise RuntimeError("database is not configured")

    async with async_session_factory() as db:
        client = await client_service.get_by_id(db, client_id)
        if client is None:
            raise RuntimeError(f"client not found client_id={client_id}")

        existing = await client_service.get_by_instagram_id(db, instagram_account_id)
        if existing is not None and str(existing.id) != client_id:
            raise RuntimeError(
                "instagram_account_id is already bound to another client "
                f"client_id={existing.id}"
            )

        if not apply:
            print(
                "dry_run=true "
                f"client_id={client_id} "
                f"current_instagram_account_id={client.instagram_account_id} "
                f"new_instagram_account_id={instagram_account_id}"
            )
            return

        updated = await client_service.bind_instagram_account_id(
            db,
            client_id,
            instagram_account_id,
        )
        if updated is None:
            raise RuntimeError(f"client not found client_id={client_id}")

        print(
            "updated=true "
            f"client_id={updated.id} "
            f"instagram_account_id={updated.instagram_account_id}"
        )


if __name__ == "__main__":
    main()
