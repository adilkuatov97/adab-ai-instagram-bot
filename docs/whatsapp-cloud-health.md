# WhatsApp Cloud Health

Use this read-only endpoint to check WhatsApp Cloud configuration and failed-send outbox status from Render or a browser.

```text
GET /whatsapp/cloud/health
```

The endpoint always returns HTTP 200. Use the response fields to understand status.

## Fields

- `ok`: true when WhatsApp Cloud send configuration is ready and production-only safety checks pass.
- `configured`: true when required WhatsApp Cloud send configuration is present.
- `production`: true when `APP_ENV`, `ENVIRONMENT`, `APP_ENVIRONMENT`, or `NODE_ENV` is `production`, `prod`, or `live`.
- `production_ready`: true when `configured` is true and production-only safety checks pass.
- `access_token_configured`: true when `WHATSAPP_CLOUD_ACCESS_TOKEN` is set.
- `app_secret_configured`: true when `WHATSAPP_CLOUD_APP_SECRET` is set.
- `phone_number_id_configured`: true when `WHATSAPP_CLOUD_PHONE_NUMBER_ID` is set.
- `client_id_configured`: true when `WHATSAPP_CLOUD_DEFAULT_CLIENT_ID` or `WHATSAPP_CLOUD_CLIENT_MAP` is set.
- `client_map_configured`: true when `WHATSAPP_CLOUD_CLIENT_MAP` is set.
- `recipient_overrides_configured`: true when `WHATSAPP_CLOUD_RECIPIENT_OVERRIDES` is set.
- `redis_available`: true when Redis outbox count can be read.
- `outbox_failed_count`: number of failed outbox items, or null when Redis is unavailable.
- `api_version`: active WhatsApp Cloud API version.

## Healthy response

```json
{
  "ok": true,
  "configured": true,
  "production": true,
  "production_ready": true,
  "access_token_configured": true,
  "app_secret_configured": true,
  "phone_number_id_configured": true,
  "client_id_configured": true,
  "client_map_configured": true,
  "recipient_overrides_configured": false,
  "redis_available": true,
  "outbox_failed_count": 0,
  "api_version": "v25.0"
}
```

## Redis unavailable response

```json
{
  "ok": true,
  "configured": true,
  "production": false,
  "production_ready": true,
  "access_token_configured": true,
  "app_secret_configured": false,
  "phone_number_id_configured": true,
  "client_id_configured": true,
  "client_map_configured": false,
  "recipient_overrides_configured": false,
  "redis_available": false,
  "outbox_failed_count": null,
  "api_version": "v25.0"
}
```

## Security

The endpoint does not return access tokens, client ids, phone numbers, recipient override values, Redis URL, outbox contents, or `reply_text`.

In production, `ok` becomes `false` when either:

- `WHATSAPP_CLOUD_APP_SECRET` is missing, because webhook signature validation must fail closed.
- `WHATSAPP_CLOUD_RECIPIENT_OVERRIDES` is configured, because recipient overrides are test-mode only.
