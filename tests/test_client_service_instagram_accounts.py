from __future__ import annotations

import unittest
import uuid

from app.db.models import Client, ClientInstagramAccount
from app.services import client_service


class ClientServiceInstagramAccountsTest(unittest.IsolatedAsyncioTestCase):
    async def test_instagram_account_id_resolves_via_new_table(self):
        client = _client()
        db = _FakeDb([_FakeResult(client)])

        resolved = await client_service.get_by_instagram_id(db, "17841400368456767")

        self.assertIs(resolved, client)
        self.assertEqual(len(db.executed), 1)

    async def test_instagram_account_id_fallback_via_clients_field_still_works(self):
        client = _client(instagram_account_id="17841479977199535")
        db = _FakeDb([_FakeResult(None), _FakeResult(client)])

        resolved = await client_service.get_by_instagram_id(db, "17841479977199535")

        self.assertIs(resolved, client)
        self.assertEqual(len(db.executed), 2)

    async def test_bind_instagram_account_conflict_detection(self):
        target_client = _client(client_id=uuid.uuid4())
        other_client_id = uuid.uuid4()
        existing_binding = ClientInstagramAccount(
            client_id=other_client_id,
            instagram_account_id="17841400368456767",
            status="active",
        )
        db = _FakeDb([_FakeResult(target_client), _FakeResult(existing_binding)])

        with self.assertRaises(ValueError):
            await client_service.bind_instagram_account_id(
                db,
                str(target_client.id),
                "17841400368456767",
                account_name="Бот садик",
            )

        self.assertEqual(db.added, [])
        self.assertEqual(db.commit_count, 0)

    async def test_unknown_instagram_account_id_returns_none_safely(self):
        db = _FakeDb([_FakeResult(None), _FakeResult(None)])

        resolved = await client_service.get_by_instagram_id(db, "unknown")

        self.assertIsNone(resolved)
        self.assertEqual(len(db.executed), 2)


class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeDb:
    def __init__(self, results: list[_FakeResult]):
        self.results = list(results)
        self.executed = []
        self.added = []
        self.commit_count = 0
        self.refresh_count = 0

    async def execute(self, statement):
        self.executed.append(statement)
        if not self.results:
            raise AssertionError("unexpected execute call")
        return self.results.pop(0)

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, value):
        self.refresh_count += 1


def _client(
    *,
    client_id: uuid.UUID | None = None,
    instagram_account_id: str = "legacy-account",
) -> Client:
    return Client(
        id=client_id or uuid.uuid4(),
        business_name="Adab AI Agency",
        owner_email="owner@example.com",
        instagram_account_id=instagram_account_id,
        instagram_access_token_encrypted="encrypted",
        status="active",
    )
