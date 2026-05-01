import httpx
from groq import AsyncGroq


async def transcribe_audio(audio_url: str, groq_api_key: str) -> str | None:
    if not groq_api_key:
        print("GROQ: api key not provided, skipping transcription")
        return None
    print(f"TRANSCRIBING AUDIO: {audio_url}")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(audio_url)
            r.raise_for_status()
            audio_bytes = r.content
        groq_client = AsyncGroq(api_key=groq_api_key)
        transcription = await groq_client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=("audio.ogg", audio_bytes),
        )
        text = transcription.text.strip()
        print(f"TRANSCRIPTION RESULT: {text}")
        return text if text else None
    except Exception as e:
        print(f"GROQ ERROR: {type(e).__name__}: {e}")
        return None
