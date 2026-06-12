# Meta WhatsApp App Review Checklist

Use this checklist before submitting the Meta app for WhatsApp Business Platform review.

## Readiness Status

- Business verification: required before broad production use.
- App mode: set to Live only after production env is complete.
- Privacy Policy URL: required and must describe message processing, storage, retention, and support contact.
- Terms URL: recommended for commercial SaaS/client automation.
- Data deletion: provide a deletion instruction page or callback if the app stores user data.
- Webhook callback URL: `https://adab-ai-instagram-bot.onrender.com/whatsapp/cloud/webhook`
- Webhook verify token: set in Meta and Render as `WHATSAPP_CLOUD_VERIFY_TOKEN`; do not disclose it in screenshots or tickets.
- App Secret: set in Render as `WHATSAPP_CLOUD_APP_SECRET`; production webhook POSTs fail closed without it.
- Production WABA and phone number: connected, approved display name, healthy phone number status.
- Payment method: configured if required by Meta for production messaging.
- Message templates: approved before business-initiated messages or replies outside the 24-hour customer service window.

## Required Permissions

- `whatsapp_business_messaging`: required to send and receive WhatsApp messages through Cloud API.
- `whatsapp_business_management`: required to manage/access WhatsApp Business Account assets and phone number configuration.
- `business_management`: use only if the app manages business assets or needs system-user/business asset access. Do not request it if not needed for the final submitted flow.

The WhatsApp Cloud flow must not depend on Instagram, Ads, or legacy Facebook Page permissions.

## Review Use Case

ADAB AI provides AI-assisted customer response automation for SMBs. The app receives inbound WhatsApp customer messages through the official WhatsApp Cloud API webhook, routes the message to the correct internal business client by `phone_number_id`, generates a short assistant reply, stores conversation/lead context, optionally notifies a manager, and sends the reply back through the official Graph API `/messages` endpoint.

## Reviewer Test Steps

1. Open the submitted app in Meta Developers.
2. Confirm the WhatsApp product is configured with the callback URL above.
3. Confirm the `messages` webhook field is subscribed.
4. Send a WhatsApp text message to the connected test or production business number.
5. Confirm the webhook returns HTTP 200 quickly.
6. Confirm the backend replies through WhatsApp Cloud API.
7. Confirm no tokens, full webhook payloads, message body dumps, Redis URL, or outbox contents appear in logs.
8. Confirm `/whatsapp/cloud/health` returns `ok=true` and does not expose secrets or phone numbers.

## Screencast Outline

1. Show Meta WhatsApp webhook callback URL and `messages` subscription.
2. Show Render env names only, with values hidden.
3. Show `/whatsapp/cloud/health` returning safe readiness flags.
4. Send a WhatsApp message from a reviewer/test phone.
5. Show the user receiving the automated reply.
6. Show safe server logs with metadata only.

## Must Be True Before Submission

- `APP_ENV=production`
- `WHATSAPP_CLOUD_APP_SECRET` configured.
- `WHATSAPP_CLOUD_RECIPIENT_OVERRIDES` empty or removed.
- `WHATSAPP_CLOUD_CLIENT_MAP` maps every production `phone_number_id` to the correct internal `client_id`.
- `WHATSAPP_CLOUD_ACCESS_TOKEN` is a production system-user token with only required permissions.
- `.env` is not tracked by git.
- Data deletion and privacy policy text are published outside the repo.
