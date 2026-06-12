# WhatsApp Cloud API Text Processing

This document covers the text-only MVP for processing inbound WhatsApp Cloud API messages and replying through the official Meta Graph API.

## Required environment variables

Webhook verification:

```text
WHATSAPP_CLOUD_VERIFY_TOKEN=
```

Secure POST webhook signature verification:

```text
WHATSAPP_CLOUD_APP_SECRET=
```

Text processing and replies:

```text
WHATSAPP_CLOUD_ACCESS_TOKEN=
WHATSAPP_CLOUD_PHONE_NUMBER_ID=
WHATSAPP_CLOUD_DEFAULT_CLIENT_ID=
WHATSAPP_CLOUD_API_VERSION=v25.0
```

`WHATSAPP_CLOUD_API_VERSION` defaults to `v25.0` when missing.

Debounce and per-user processing lock:

```text
WHATSAPP_CLOUD_DEBOUNCE_SECONDS=3
WHATSAPP_CLOUD_LOCK_TTL_SECONDS=120
```

Inbound text messages from the same `client_id + wa_id` are buffered under:

```text
whatsapp_cloud:{client_id}:{wa_id}:pending
```

The worker waits 2-4 seconds, combines all pending texts for that user, sends one combined text to Claude, and sends one WhatsApp reply. A per-user lock prevents two concurrent workers for the same `client_id + wa_id`; the lock has a TTL so a crashed worker cannot block the user forever.

The app still starts if these variables are missing. Missing processing variables only stop WhatsApp Cloud message processing/reply sending and are logged without exposing tokens.

## Webhook URL

Use this callback URL in Meta Developers:

```text
https://adab-ai-instagram-bot.onrender.com/whatsapp/cloud/webhook
```

## Meta subscription

In Meta Developers:

1. Open the app with WhatsApp product enabled.
2. Go to **WhatsApp > Configuration**.
3. Verify the callback URL with `WHATSAPP_CLOUD_VERIFY_TOKEN`.
4. Subscribe to the **messages** webhook field.
5. Send a real WhatsApp text message to the connected Cloud API phone number.

## Test flow

1. Configure Render env vars listed above.
2. Deploy the PR.
3. In Meta, send a test text message to the Cloud API phone number.
4. Confirm Render receives `POST /whatsapp/cloud/webhook` with `200 OK`.
5. Confirm logs show safe metadata only: object, entry count, message existence, message type, ids, lengths, status.
6. Confirm the customer receives an AI reply from the official WhatsApp Cloud API number.
7. If Claude marks the lead as hot, confirm Telegram manager notification is sent.

## What this MVP supports

- Inbound WhatsApp Cloud API text messages.
- MVP client resolution through `WHATSAPP_CLOUD_DEFAULT_CLIENT_ID`.
- Existing client status check.
- Existing `whatsapp_system_prompt` fallback to `system_prompt`.
- Existing Claude response logic.
- Existing conversation/message/lead persistence.
- Existing Telegram hot lead notification.
- Outbound replies through `https://graph.facebook.com/{api_version}/{phone_number_id}/messages`.

## Unsupported behavior for now

- Media, voice, image, document, button, interactive, location, and other non-text messages are ignored.
- Delivery/read statuses are ignored.
- Phone-number-to-client mapping is not implemented yet.
- Multi-tenant Cloud API routing is not implemented yet.
- No retry queue is implemented for failed Graph API sends.

## Idempotency behavior

When Redis is configured, incoming WhatsApp message ids are marked with:

```text
whatsapp_cloud:processed:{message_id}
```

The key uses a 24-hour TTL. Duplicate message ids are skipped.

When Redis is unavailable or not configured, processing continues and a warning is logged. This keeps local/dev behavior simple, but duplicate Meta retries may be processed more than once without Redis.

## Baileys fallback

The existing internal Baileys-compatible endpoint remains available and unchanged:

```text
POST /whatsapp/message
```

This MVP does not remove or replace that flow.
