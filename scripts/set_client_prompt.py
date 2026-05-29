#!/usr/bin/env python3
"""Update a client's system_prompt (or whatsapp_system_prompt) in the DB from a plain-text file.

Usage:
    python3 scripts/set_client_prompt.py <client_uuid> <path/to/prompt.txt>
    python3 scripts/set_client_prompt.py --whatsapp <client_uuid> <path/to/prompt.txt>

Examples:
    python3 scripts/set_client_prompt.py f17a14f4-124a-439a-b3ae-0911ea007037 prompts/adab_ai_agency.txt
    python3 scripts/set_client_prompt.py --whatsapp f17a14f4-124a-439a-b3ae-0911ea007037 prompts/adab_ai_agency_whatsapp.txt
"""
import asyncio
import os
import sys

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

load_dotenv()


async def main() -> None:
    args = sys.argv[1:]

    use_whatsapp = False
    if args and args[0] == "--whatsapp":
        use_whatsapp = True
        args = args[1:]

    if len(args) != 2:
        print("Usage: python3 scripts/set_client_prompt.py [--whatsapp] <client_id> <prompt_file>")
        sys.exit(1)

    client_id, prompt_path = args

    if not os.path.exists(prompt_path):
        print(f"Error: file not found: {prompt_path}")
        sys.exit(1)

    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt = f.read()

    db_url = os.getenv("DIRECT_DATABASE_URL")
    if not db_url:
        print("Error: DIRECT_DATABASE_URL not set in .env")
        sys.exit(1)

    column = "whatsapp_system_prompt" if use_whatsapp else "system_prompt"
    engine = create_async_engine(db_url, connect_args={"statement_cache_size": 0})
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                f"UPDATE clients SET {column} = :prompt, updated_at = NOW() "
                "WHERE id = CAST(:client_id AS UUID) RETURNING id"
            ),
            {"prompt": prompt, "client_id": client_id},
        )
        not_found = result.rowcount == 0
    await engine.dispose()

    if not_found:
        print(f"Error: client {client_id} not found")
        sys.exit(1)

    print(f"Updated client {client_id}: {column} = {len(prompt)} chars")


asyncio.run(main())
