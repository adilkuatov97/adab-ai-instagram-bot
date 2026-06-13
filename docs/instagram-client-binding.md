# Instagram Client Binding

Instagram webhook routing uses Meta webhook `entry.id` as the Instagram account id:

```python
account_id = entry.get("id")
client = await client_service.get_by_instagram_id(db, account_id)
```

Production routing now uses `client_instagram_accounts.instagram_account_id`.
The legacy `clients.instagram_account_id` field remains as a fallback only for backward compatibility.

## Current Schema

Primary binding table:

```text
client_instagram_accounts
- id
- client_id
- instagram_account_id
- account_name
- status
- created_at
- updated_at
```

`instagram_account_id` is unique, so one Meta Instagram account can be bound to only one client.
One client can have multiple Instagram accounts.

## Check Current Bindings

```sql
SELECT
  cia.instagram_account_id,
  cia.account_name,
  cia.status AS binding_status,
  c.id AS client_id,
  c.business_name,
  c.status AS client_status
FROM client_instagram_accounts cia
JOIN clients c ON c.id = cia.client_id
ORDER BY c.business_name, cia.created_at;
```

Check legacy values that were backfilled by the migration:

```sql
SELECT id, business_name, instagram_account_id, status
FROM clients
ORDER BY business_name;
```

## Bind Adab AI Agency

Dry run:

```bash
venv/bin/python -m app.scripts.bind_instagram_account \
  --client-id f17a14f4-124a-439a-b3ae-0911ea007037 \
  --instagram-account-id 17841479977199535 \
  --account-name "Adab AI Agency"
```

Apply:

```bash
venv/bin/python -m app.scripts.bind_instagram_account \
  --client-id f17a14f4-124a-439a-b3ae-0911ea007037 \
  --instagram-account-id 17841479977199535 \
  --account-name "Adab AI Agency" \
  --apply
```

## Bind Бот садик

First find the садик client id:

```sql
SELECT id, business_name, instagram_account_id, status
FROM clients
WHERE business_name ILIKE '%сад%'
   OR business_name ILIKE '%sad%'
   OR notes ILIKE '%сад%';
```

Then bind the Meta Instagram account id from Render logs:

```bash
venv/bin/python -m app.scripts.bind_instagram_account \
  --client-id <sadik-client-id> \
  --instagram-account-id 17841400368456767 \
  --account-name "Бот садик"
```

Apply after the dry run is correct:

```bash
venv/bin/python -m app.scripts.bind_instagram_account \
  --client-id <sadik-client-id> \
  --instagram-account-id 17841400368456767 \
  --account-name "Бот садик" \
  --apply
```

## Manual SQL

Use this only from a trusted DB console. It adds a binding and does not overwrite `clients.instagram_account_id`.

```sql
INSERT INTO client_instagram_accounts (
  id,
  client_id,
  instagram_account_id,
  account_name,
  status
)
VALUES (
  gen_random_uuid(),
  '<client-id>',
  '<instagram-account-id>',
  '<account-name>',
  'active'
)
ON CONFLICT (instagram_account_id) DO UPDATE
SET account_name = EXCLUDED.account_name,
    status = 'active',
    updated_at = NOW()
WHERE client_instagram_accounts.client_id = EXCLUDED.client_id;
```

If the `ON CONFLICT` update affects 0 rows, that Instagram account id is already bound to another client.

## Expected Result

The two accounts can coexist:

```text
17841479977199535 -> Adab AI Agency
17841400368456767 -> Бот садик
```

After binding, Render should stop logging:

```text
CLIENT_RESOLVED source=none account_id=17841400368456767
```
