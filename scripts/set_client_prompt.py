#!/usr/bin/env python3
"""Update a client's system_prompt in the DB from a plain-text file.

Usage:
    python3 scripts/set_client_prompt.py <client_uuid> <path/to/prompt.txt>

Example:
    python3 scripts/set_client_prompt.py f17a14f4-124a-439a-b3ae-0911ea007037 prompts/adab_ai_agency.txt
"""
import asyncio
import os
import sys

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

load_dotenv()


async def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python3 scripts/set_client_prompt.py <client_id> <prompt_file>")
        sys.exit(1)

    client_id = sys.argv[1]
    prompt_path = sys.argv[2]

    if not os.path.exists(prompt_path):
        print(f"Error: file not found: {prompt_path}")
        sys.exit(1)

    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt = f.read()

    db_url = os.getenv("DIRECT_DATABASE_URL")
    if not db_url:
        print("Error: DIRECT_DATABASE_URL not set in .env")
        sys.exit(1)

    engine = create_async_engine(db_url, connect_args={"statement_cache_size": 0})
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE clients SET system_prompt = :prompt, updated_at = NOW() "
                "WHERE id = :id::uuid RETURNING id"
            ),
            {"prompt": prompt, "id": client_id},
        )
        if result.rowcount == 0:
            print(f"Error: client {client_id} not found")
            await engine.dispose()
            sys.exit(1)
    await engine.dispose()

    print(f"Updated client {client_id}: prompt {len(prompt)} chars")


asyncio.run(main())
