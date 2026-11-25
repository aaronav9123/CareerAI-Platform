"""
llm.py
------
One small wrapper around an LLM API, used by the Resume Improver and the Mock
Interview. Nothing else in the app depends on it: when no key is configured,
`is_configured()` is False and those features fall back to rule-based logic.

Configure in .env (see .env.example):

  Anthropic :  ANTHROPIC_API_KEY=...            (LLM_MODEL optional)
  OpenAI-compatible (OpenAI, Groq, Gemini's OpenAI endpoint, Ollama...):
               LLM_API_KEY=...  LLM_BASE_URL=https://api.groq.com/openai/v1
               LLM_MODEL=llama-3.3-70b-versatile
"""

import json

import requests

from config import env

TIMEOUT = 45


class LLMError(Exception):
    pass


def provider():
    if env("ANTHROPIC_API_KEY"):
        return "anthropic"
    if env("LLM_API_KEY") or env("OPENAI_API_KEY"):
        return "openai"
    return None


def is_configured():
    return provider() is not None


def label():
    p = provider()
    if p == "anthropic":
        return f"Claude ({env('LLM_MODEL', 'claude-sonnet-5-5')})"
    if p == "openai":
        return env("LLM_MODEL", "gpt-4o-mini")
    return None


def complete(system, user, max_tokens=1500, temperature=0.4):
    p = provider()
    if p is None:
        raise LLMError("No LLM API key configured.")
    try:
        if p == "anthropic":
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": env("ANTHROPIC_API_KEY"),
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": env("LLM_MODEL", "claude-sonnet-5-5"),
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json().get("content", []))

        base = env("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        key = env("LLM_API_KEY") or env("OPENAI_API_KEY")
        r = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
            json={
                "model": env("LLM_MODEL", "gpt-4o-mini"),
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except requests.RequestException as e:
        raise LLMError(f"LLM request failed: {e}") from e
    except (KeyError, IndexError, ValueError) as e:
        raise LLMError(f"Unexpected LLM response: {e}") from e


def extract_json(text):
    """Pull the first JSON object/array out of an LLM reply (handles ``` fences)."""
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "[{":
            try:
                obj, _ = dec.raw_decode(text[i:])
                return obj
            except ValueError:
                continue
    raise LLMError("The model did not return valid JSON.")


def complete_json(system, user, **kw):
    return extract_json(complete(system, user, **kw))
