# Instagram Client Binding

Instagram webhook routing uses the webhook `entry.id` as the Meta Instagram account id:

```python
account_id = entry.get("id")
client = await client_service.get_by_instagram_id(db, account_id)
```

That value must match `clients.instagram_account_id`. If Render logs show:

```text
CLIENT_RESOLVED source=none account_id=17841400368456767
```

then no client row currently has:

```text
instagram_account_id=17841400368456767
```

## Safe CLI

Dry run first:

```bash
venv/bin/python -m app.scripts.bind_instagram_account \
  --client-id f17a14f4-124a-439a-b3ae-0911ea007037 \
  --instagram-account-id 17841400368456767
```

Apply only after the dry run shows the expected current and new id:

```bash
venv/bin/python -m app.scripts.bind_instagram_account \
  --client-id f17a14f4-124a-439a-b3ae-0911ea007037 \
  --instagram-account-id 17841400368456767 \
  --apply
```

The command refuses to update if the Instagram account id is already bound to another client.

## Manual SQL

Use this only from a trusted DB console. It does not print or require any tokens.

```sql
BEGIN;

SELECT id, business_name, instagram_account_id
FROM clients
WHERE id = 'f17a14f4-124a-439a-b3ae-0911ea007037'
   OR instagram_account_id = '17841400368456767'
FOR UPDATE;

UPDATE clients
SET instagram_account_id = '17841400368456767',
    updated_at = NOW()
WHERE id = 'f17a14f4-124a-439a-b3ae-0911ea007037'
  AND NOT EXISTS (
    SELECT 1
    FROM clients
    WHERE instagram_account_id = '17841400368456767'
      AND id <> 'f17a14f4-124a-439a-b3ae-0911ea007037'
  );

COMMIT;
```

Verify:

```sql
SELECT id, business_name, instagram_account_id, status
FROM clients
WHERE id = 'f17a14f4-124a-439a-b3ae-0911ea007037';
```

Expected result:

```text
instagram_account_id = 17841400368456767
status = active
```

## Schema Limitation

Current schema supports one Instagram account id per client:

```text
clients.instagram_account_id UNIQUE NOT NULL
```

Risk: if one business needs several Instagram accounts/pages routed to the same client, the current schema cannot represent it. Minimal future fix: add a `client_channels` or `client_instagram_accounts` table with `client_id`, `instagram_account_id`, `status`, `created_at`, and a unique index on `instagram_account_id`.
