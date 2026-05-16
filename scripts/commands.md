# Полезные команды

## Переменные
```bash
BASE_URL="https://adab-ai-instagram-bot.onrender.com"
ADMIN_KEY="_3SiU7s2Wej-9q1sI8y3zJ6d_dWIO4ZCNeZh6dyDPQk"
CLIENT_ID="b763a385-06f4-4dbc-8828-41c9cf56c483"
```

---

## Кэш

### Очистить кэш разговоров клиента
```bash
curl -s -X DELETE "$BASE_URL/admin/flush-cache/$CLIENT_ID" \
  -H "x-admin-key: $ADMIN_KEY"
```

---

## Клиенты

### Список всех клиентов
```bash
curl -s "$BASE_URL/admin/clients" \
  -H "x-admin-key: $ADMIN_KEY" | python3 -m json.tool
```

### Получить клиента по ID
```bash
curl -s "$BASE_URL/admin/clients/$CLIENT_ID" \
  -H "x-admin-key: $ADMIN_KEY" | python3 -m json.tool
```

### Создать клиента
```bash
curl -s -X POST "$BASE_URL/admin/clients" \
  -H "x-admin-key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "business_name": "Название бизнеса",
    "owner_email": "email@example.com",
    "instagram_account_id": "123456789",
    "instagram_access_token": "TOKEN",
    "whatsapp_link": "https://wa.me/77XXXXXXXXX",
    "telegram_manager_chat_id": "123456789",
    "status": "active"
  }' | python3 -m json.tool
```

### Обновить клиента (например, промт)
```bash
curl -s -X PATCH "$BASE_URL/admin/clients/$CLIENT_ID" \
  -H "x-admin-key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"system_prompt": "Новый промт..."}' | python3 -m json.tool
```

### Деактивировать клиента
```bash
curl -s -X DELETE "$BASE_URL/admin/clients/$CLIENT_ID" \
  -H "x-admin-key: $ADMIN_KEY"
```

---

## Лиды и разговоры

### Лиды клиента
```bash
curl -s "$BASE_URL/admin/clients/$CLIENT_ID/leads" \
  -H "x-admin-key: $ADMIN_KEY" | python3 -m json.tool
```

### Разговоры клиента
```bash
curl -s "$BASE_URL/admin/clients/$CLIENT_ID/conversations" \
  -H "x-admin-key: $ADMIN_KEY" | python3 -m json.tool
```

---

## Статистика

### Общая статистика
```bash
curl -s "$BASE_URL/admin/stats" \
  -H "x-admin-key: $ADMIN_KEY" | python3 -m json.tool
```

---

## Здоровье сервера

```bash
curl -s "$BASE_URL/health"
```

---

## Промт — обновить из файла

```bash
PROMPT=$(cat prompts/ansarik_balabaqsha.txt)
curl -s -X PATCH "$BASE_URL/admin/clients/$CLIENT_ID" \
  -H "x-admin-key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"system_prompt\": $(echo "$PROMPT" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" \
  | python3 -m json.tool
```
