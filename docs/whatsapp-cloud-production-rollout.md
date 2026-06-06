# WhatsApp Cloud Production Rollout

This checklist describes how to move the current WhatsApp Cloud integration from Meta test mode to a real production WhatsApp Business number.

## Current Architecture Summary

- Meta WhatsApp Cloud API receives and sends WhatsApp messages through the official Graph API.
- Render runs the FastAPI backend and exposes the WhatsApp Cloud webhook.
- Inbound text messages are processed by the existing Claude pipeline.
- AI replies are sent through the Graph API `/messages` endpoint.
- Redis stores failed outbound sends in the WhatsApp Cloud outbox for manual inspection and retry.
- The health endpoint exposes safe configuration and outbox status:

```text
https://adab-ai-instagram-bot.onrender.com/whatsapp/cloud/health
```

## Production Prerequisites

Before switching to production, confirm:

- Meta Business verification status is complete or sufficient for the planned WhatsApp usage.
- The Meta app has access to the target WhatsApp Business Account.
- A real production phone number is available and can be attached to WhatsApp Business.
- The WhatsApp display name is approved.
- Payment and billing setup is complete if required by Meta for production messaging.
- A permanent system user token is generated.
- The token has the required permissions:
  - `business_management`
  - `whatsapp_business_management`
  - `whatsapp_business_messaging`

## Production Env Checklist

Required Render env vars:

```text
WHATSAPP_CLOUD_ACCESS_TOKEN=
WHATSAPP_CLOUD_PHONE_NUMBER_ID=
WHATSAPP_CLOUD_CLIENT_MAP=
WHATSAPP_CLOUD_DEFAULT_CLIENT_ID=
WHATSAPP_CLOUD_API_VERSION=v25.0
WHATSAPP_CLOUD_APP_SECRET=
REDIS_URL=
DATABASE_URL=
ANTHROPIC_API_KEY=
```

Notes:

- `WHATSAPP_CLOUD_CLIENT_MAP` should map the production `phone_number_id` to the internal `client_id`.
- Keep `WHATSAPP_CLOUD_DEFAULT_CLIENT_ID` as a fallback during rollout.
- `WHATSAPP_CLOUD_API_VERSION` should remain explicit, currently `v25.0`.
- `WHATSAPP_CLOUD_APP_SECRET` should stay configured so webhook signature verification remains enabled.
- Use the existing Claude env if the deployment uses a different configured Claude/Anthropic variable.
- `WHATSAPP_CLOUD_RECIPIENT_OVERRIDES` is test-mode only. It should be empty or removed in production.

Example mapping:

```text
WHATSAPP_CLOUD_CLIENT_MAP=1175403148986567:f17a14f4-124a-439a-b3ae-0911ea007037
```

## Step-by-Step Migration Plan

1. Create or attach the real WhatsApp Business phone number in Meta.
2. Confirm the production `phone_number_id`.
3. Generate a permanent system user token with the required permissions.
4. Add the production token to Render as `WHATSAPP_CLOUD_ACCESS_TOKEN`.
5. Add the production `phone_number_id` to Render as `WHATSAPP_CLOUD_PHONE_NUMBER_ID`.
6. Add the production `phone_number_id:client_id` pair to `WHATSAPP_CLOUD_CLIENT_MAP`.
7. Keep the test number env values documented separately outside the repo.
8. Ensure `WHATSAPP_CLOUD_RECIPIENT_OVERRIDES` is empty or removed.
9. Deploy the latest commit.
10. Open the health endpoint and confirm `ok=true`, `configured=true`, and `outbox_failed_count=0`.
11. Send an inbound test message from a real customer WhatsApp number.
12. Confirm the backend receives the inbound message.
13. Confirm Claude generates a reply.
14. Confirm the customer receives the reply through the production WhatsApp Business number.
15. Confirm `outbox_failed_count` remains `0`.
16. Monitor Render logs for webhook, send, and outbox warnings.

## Safety Rollback Plan

If production messaging fails:

1. Restore the previous Meta test-mode env values in Render.
2. Restore `WHATSAPP_CLOUD_RECIPIENT_OVERRIDES` only for test-mode recipients if needed.
3. Redeploy.
4. Check the health endpoint.
5. Run the outbox CLI and inspect failed sends.
6. Retry or preserve failed outbox items as needed.
7. Do not delete test config until production is stable for real conversations.

## Templates and the 24-Hour Window

WhatsApp has a customer service window:

- If the user writes first, the bot can reply with normal text inside the customer service window.
- If the business writes first or replies outside the service window, an approved WhatsApp template is required.
- Do not use marketing templates for normal support replies.
- Template send support should be added in a future PR as a separate feature.

## Multi-Client Model

Current env-based routing:

```text
WHATSAPP_CLOUD_CLIENT_MAP=phone_number_id:client_id
```

This is enough for rollout, but future production multi-tenant routing should move to DB-backed configuration with:

- `phone_number_id`
- `waba_id`
- `client_id`
- `display_name`
- `status`
- token reference or secret manager reference

## Operational Checks

Health:

```text
https://adab-ai-instagram-bot.onrender.com/whatsapp/cloud/health
```

List failed outbox items:

```bash
python -m app.scripts.whatsapp_cloud_outbox list
```

Retry one failed outbox item:

```bash
python -m app.scripts.whatsapp_cloud_outbox retry <item_id>
```

Expected healthy status:

```json
{
  "ok": true,
  "configured": true,
  "access_token_configured": true,
  "phone_number_id_configured": true,
  "client_id_configured": true,
  "client_map_configured": true,
  "recipient_overrides_configured": false,
  "redis_available": true,
  "outbox_failed_count": 0,
  "api_version": "v25.0"
}
```

## Security Notes

- Never commit tokens.
- Do not screenshot tokens.
- Rotate the permanent system user token if it is exposed.
- Keep `WHATSAPP_CLOUD_APP_SECRET` configured for webhook signature verification.
- Do not expose `reply_text` from outbox records publicly.
- Keep Render env access limited to trusted operators.

## Next Engineering Steps After Rollout

- DB-backed `phone_number_id -> client_id` mapping.
- WhatsApp template message support.
- Media and voice support.
- Admin-protected outbox API.
- Permanent token rotation process.
- Monitoring and alerts for webhook failures, Graph API send failures, and outbox growth.
