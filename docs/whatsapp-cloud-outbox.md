# WhatsApp Cloud Outbox

This is a Redis-backed foundation for failed WhatsApp Cloud outbound sends.

## What it does

When Claude generates a reply but `send_whatsapp_cloud_text()` fails, the app stores a failed outbox item in Redis. This preserves enough data for manual inspection and future retry tooling.

Successful sends do not create outbox items.

## Redis keys

Failed item index:

```text
whatsapp_cloud:outbox:failed:zset
```

Failed item payload:

```text
whatsapp_cloud:outbox:failed:item:{id}
```

The initial sorted set score is the outbox item creation timestamp in milliseconds. Failed manual retries update the score to the current timestamp so recently retried failures appear first.

## Stored fields

Each item stores:

- `id`
- `client_id`
- `wa_id`
- `send_to`
- `phone_number_id`
- `message_id`
- `reply_text`
- `created_at`
- `last_error`
- `attempts`

`reply_text` is stored for future retry, but it must not be printed in logs.

## How to inspect later

Use the helper functions in `app/services/whatsapp_cloud_outbox.py`:

- `load_outbox_item(item_id)`
- `list_outbox_items(limit=20)`

Manual Redis inspection can also read the sorted set and item keys above.

You can also use the CLI:

```bash
python -m app.scripts.whatsapp_cloud_outbox list
python -m app.scripts.whatsapp_cloud_outbox retry <item_id>
```

The `list` command prints safe metadata only and does not print `reply_text`.

## Retry behavior

On retry success:

- the message is sent via the official WhatsApp Cloud API
- the outbox item key is deleted
- the item id is removed from `whatsapp_cloud:outbox:failed:zset`

On retry failure:

- the item remains in Redis
- `attempts` is incremented
- `last_error` is updated with a safe string capped at 500 characters
- the sorted set score is updated to the current timestamp so recently retried failures appear first

## Limitations

- No automatic retry worker yet.
- No admin UI yet.
- If Redis is missing or unavailable, the webhook processing does not crash, but the failed send is not persisted.
