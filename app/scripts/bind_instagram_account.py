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
    parser.add_argument("--account-name", default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the update. Without this flag the command only validates and prints the planned change.",
    )
    args = parser.parse_args()

    try:
        _validate_args(args.client_id, args.instagram_account_id)
        asyncio.run(
            _run(
                args.client_id,
                args.instagram_account_id,
                account_name=args.account_name,
                apply=args.apply,
            )
        )
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


async def _run(
    client_id: str,
    instagram_account_id: str,
    *,
    account_name: str | None,
    apply: bool,
) -> None:
    if async_session_factory is None:
        raise RuntimeError("database is not configured")

    async with async_session_factory() as db:
        client = await client_service.get_by_id(db, client_id)
        if client is None:
            raise RuntimeError(f"client not found client_id={client_id}")

        existing = await client_service.get_instagram_account_binding(db, instagram_account_id)
        if existing is not None and str(existing.client_id) != client_id:
            raise RuntimeError(
                "instagram_account_id is already bound to another client "
                f"client_id={existing.client_id}"
            )
        legacy_existing = await client_service.get_legacy_client_by_instagram_account_id(
            db,
            instagram_account_id,
        )
        if legacy_existing is not None and str(legacy_existing.id) != client_id:
            raise RuntimeError(
                "instagram_account_id is already used by another legacy client "
                f"client_id={legacy_existing.id}"
            )

        if not apply:
            print(
                "dry_run=true "
                f"client_id={client_id} "
                f"legacy_instagram_account_id={client.instagram_account_id} "
                f"binding_exists={existing is not None} "
                f"instagram_account_id={instagram_account_id} "
                f"account_name={account_name or ''}"
            )
            return

        updated = await client_service.bind_instagram_account_id(
            db,
            client_id,
            instagram_account_id,
            account_name=account_name,
        )
        if updated is None:
            raise RuntimeError(f"client not found client_id={client_id}")

        print(
            "updated=true "
            f"client_id={updated.id} "
            f"instagram_account_id={instagram_account_id} "
            f"account_name={account_name or ''}"
        )


if __name__ == "__main__":
    main()
