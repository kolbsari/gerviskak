"""Unified LLM interface. All providers return raw text."""

import asyncio
from backend.config import MODELS_BY_ID, API_KEYS

_TIMEOUT = 60  # seconds
_MAX_TOKENS = 500
_TEMPERATURE = 1


async def get_response(model_id: str, messages: list[dict]) -> str:
    """Call the appropriate LLM and return the raw text response.

    messages: list of {"role": "user"|"assistant", "content": "..."} dicts.
    """
    model = MODELS_BY_ID[model_id]
    provider = model["provider"]

    if provider in ("openai", "deepseek", "groq"):
        return await _openai_compat(model, messages)
    elif provider == "anthropic":
        return await _anthropic(model, messages)
    elif provider == "google":
        return await _google(model, messages)
    elif provider == "mistral":
        return await _mistral(model, messages)
    else:
        raise ValueError(f"Unknown provider: {provider}")


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

async def _openai_compat(model: dict, messages: list[dict]) -> str:
    import openai

    provider = model["provider"]
    key_name = provider  # "openai", "deepseek", or "groq"
    api_key = API_KEYS[key_name]
    base_url = model.get("api_base")

    client = openai.AsyncOpenAI(
        api_key=api_key,
        **({"base_url": base_url} if base_url else {}),
        timeout=_TIMEOUT,
    )

    response = await client.chat.completions.create(
        model=model["model_string"],
        messages=messages,
        temperature=_TEMPERATURE,
        max_tokens=_MAX_TOKENS,
    )
    return response.choices[0].message.content or ""


async def _anthropic(model: dict, messages: list[dict]) -> str:
    import anthropic

    client = anthropic.AsyncAnthropic(
        api_key=API_KEYS["anthropic"],
        timeout=_TIMEOUT,
    )

    message = await client.messages.create(
        model=model["model_string"],
        max_tokens=_MAX_TOKENS,
        temperature=_TEMPERATURE,
        messages=messages,
    )
    return message.content[0].text if message.content else ""


async def _google(model: dict, messages: list[dict]) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=API_KEYS["google"])

    # Convert messages to Google's Content format
    contents = [
        types.Content(
            role="user" if m["role"] == "user" else "model",
            parts=[types.Part(text=m["content"])],
        )
        for m in messages
    ]

    # Run the synchronous call in a thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    response = await asyncio.wait_for(
        loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=model["model_string"],
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=_TEMPERATURE,
                    max_output_tokens=_MAX_TOKENS,
                ),
            ),
        ),
        timeout=_TIMEOUT,
    )
    return response.text or ""


async def _mistral(model: dict, messages: list[dict]) -> str:
    from mistralai import Mistral

    client = Mistral(api_key=API_KEYS["mistral"])

    loop = asyncio.get_event_loop()
    response = await asyncio.wait_for(
        loop.run_in_executor(
            None,
            lambda: client.chat.complete(
                model=model["model_string"],
                messages=messages,
                temperature=_TEMPERATURE,
                max_tokens=_MAX_TOKENS,
            ),
        ),
        timeout=_TIMEOUT,
    )
    return response.choices[0].message.content or ""
