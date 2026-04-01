from __future__ import annotations

import os
import logging
from typing import Dict, List, Optional

import requests
from openai import OpenAI

logger = logging.getLogger(__name__)

LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "openai").lower()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")

_openai_client: Optional[OpenAI] = None


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


def _ollama_chat(messages: List[Dict[str, str]], model: Optional[str] = None) -> str:
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {"model": model or OLLAMA_MODEL, "messages": messages, "stream": False}
    r = requests.post(url, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    return (data.get("message") or {}).get("content") or ""


def _openai_chat(messages: List[Dict[str, str]], model: Optional[str] = None, temperature: float = 0.2, max_tokens: int = 512) -> str:
    resp = _get_openai_client().chat.completions.create(
        model=model or OPENAI_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


def chat_completion(
    *,
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 512,
) -> str:
    if LLM_PROVIDER == "ollama":
        return _ollama_chat(messages, model=model)

    try:
        return _openai_chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)
    except Exception as e:
        logger.warning("OpenAI chat failed (%s). Falling back to Ollama.", e)
        return _ollama_chat(messages, model=model)