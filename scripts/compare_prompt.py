#!/usr/bin/env python3
"""Compare a client's system_prompt in the DB against a local .txt file.

Usage:
    python3 scripts/compare_prompt.py <client_uuid> <path/to/prompt.txt>

Example:
    python3 scripts/compare_prompt.py b763a385-06f4-4dbc-8828-41c9cf56c483 prompts/ansarik_balabaqsha.txt
"""
import asyncio
import difflib
import os
import sys

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

load_dotenv()


async def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python3 scripts/compare_prompt.py <client_id> <prompt_file>")
        sys.exit(1)

    client_id = sys.argv[1]
    prompt_path = sys.argv[2]

    if not os.path.exists(prompt_path):
        print(f"Error: file not found: {prompt_path}")
        sys.exit(1)

    with open(prompt_path, "r", encoding="utf-8") as f:
        file_text = f.read()

    db_url = os.getenv("DIRECT_DATABASE_URL")
    if not db_url:
        print("Error: DIRECT_DATABASE_URL not set in .env")
        sys.exit(1)

    engine = create_async_engine(db_url, connect_args={"statement_cache_size": 0})
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT business_name, system_prompt FROM clients WHERE id = CAST(:id AS UUID)"),
            {"id": client_id},
        )
        row = result.fetchone()
    await engine.dispose()

    if not row:
        print(f"Error: client {client_id} not found")
        sys.exit(1)

    business_name, db_text = row
    db_text = db_text or ""

    file_lines = file_text.splitlines(keepends=True)
    db_lines = db_text.splitlines(keepends=True)

    print(f"Client   : {business_name} ({client_id})")
    print(f"File     : {prompt_path}  ({len(file_text)} chars, {len(file_lines)} lines)")
    print(f"DB       : system_prompt  ({len(db_text)} chars, {len(db_lines)} lines)")
    print()

    diff = list(difflib.unified_diff(
        db_lines,
        file_lines,
        fromfile="DB (current)",
        tofile=f"FILE ({prompt_path})",
        lineterm="",
    ))

    if not diff:
        print("✓ No differences — file and DB are identical.")
    else:
        print(f"Differences found ({len(diff)} diff lines):")
        print("─" * 60)
        print("".join(diff))


asyncio.run(main())
