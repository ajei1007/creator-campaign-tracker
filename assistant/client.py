import httpx
from django.conf import settings

SYSTEM_PROMPT = (
    "You are a help assistant embedded in the admin of a creator-campaign "
    "management tool. Staff ask you what a form field means or how to fill it "
    "out. Answer ONLY from the field reference provided below. If the reference "
    "does not cover the question, say you don't have that information rather than "
    "guessing. Keep answers to a few sentences, concrete and practical.\n\n"
    "Field reference:\n{context}"
)


class AssistantError(Exception):
    pass


def ask(question, context):
    if not settings.GROQ_API_KEY:
        raise AssistantError("The assistant is not configured (no API key set).")

    payload = {
        "model": settings.GROQ_MODEL,
        "temperature": 0.2,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
            {"role": "user", "content": question},
        ],
    }
    headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}"}
    try:
        resp = httpx.post(
            f"{settings.GROQ_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except httpx.TimeoutException as exc:
        raise AssistantError("The assistant timed out. Please try again.") from exc
    except httpx.HTTPStatusError as exc:
        raise AssistantError(
            f"The assistant service returned an error ({exc.response.status_code})."
        ) from exc
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise AssistantError("The assistant is temporarily unavailable.") from exc
