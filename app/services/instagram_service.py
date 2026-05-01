import httpx


async def send_message(recipient_id: str, text: str, access_token: str) -> dict:
    url = "https://graph.instagram.com/v23.0/me/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload, headers=headers)
        print(f"INSTAGRAM SEND {r.status_code}: {r.text}")
        return r.json()
