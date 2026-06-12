# WhatsApp Cloud API Webhook Setup

This document describes the first official WhatsApp Cloud API webhook foundation for the Adab AI Instagram Bot backend.

## Meta Developer settings

In Meta Developers:

1. Open the app that has the WhatsApp product enabled.
2. Go to **WhatsApp > Configuration**.
3. Set the callback URL:

```text
https://adab-ai-instagram-bot.onrender.com/whatsapp/cloud/webhook
```

4. Set the verify token to the same value configured in Render as:

```text
WHATSAPP_CLOUD_VERIFY_TOKEN
```

5. Save and verify the callback URL.

## Environment variables

Required for webhook verification:

```text
WHATSAPP_CLOUD_VERIFY_TOKEN=
```

Required in production for secure webhook delivery verification:

```text
WHATSAPP_CLOUD_APP_SECRET=
```

Optional for future outbound Cloud API replies:

```text
WHATSAPP_CLOUD_ACCESS_TOKEN=
WHATSAPP_CLOUD_PHONE_NUMBER_ID=
WHATSAPP_CLOUD_DEFAULT_CLIENT_ID=
WHATSAPP_CLOUD_API_VERSION=v25.0
```

The app still starts when these variables are missing. In production, POST `/whatsapp/cloud/webhook` rejects requests until `WHATSAPP_CLOUD_APP_SECRET` is configured.

## Subscribe to messages

After callback verification succeeds:

1. In **WhatsApp > Configuration**, open webhook fields.
2. Subscribe to the **messages** webhook field.
3. Send a test WhatsApp message to the connected Cloud API phone number.
4. Confirm the backend logs only safe metadata such as object name, entry count, whether messages exist, and message type.

## What this PR does

- Adds `GET /whatsapp/cloud/webhook` for Meta webhook verification.
- Adds `POST /whatsapp/cloud/webhook` for safe receive and background text processing.
- Verifies `x-hub-signature-256`; production rejects POST requests if `WHATSAPP_CLOUD_APP_SECRET` is missing.
- Logs only safe metadata.
- Routes inbound text messages to the configured client and sends replies through the official Cloud API.
- Keeps existing Baileys/internal `POST /whatsapp/message` behavior unchanged.

## What this PR does not do yet

- Does not change Instagram webhook behavior.
- Does not support templates for outbound messages outside the 24-hour customer service window.
- Does not support WhatsApp media/voice messages yet.
- Does not move `phone_number_id -> client_id` routing into the database yet.

## Next step

Process inbound text messages from WhatsApp Cloud API, map them to a client/business, call Claude with the WhatsApp prompt, persist the conversation, notify managers for hot leads, and send replies via the official Cloud API.

For the current text-processing MVP, see [WhatsApp Cloud API Text Processing](./whatsapp-cloud-api-processing.md).
