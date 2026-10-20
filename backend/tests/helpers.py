import json
from pathlib import Path

import httpx

SAMPLES = json.loads((Path(__file__).parent / "data" / "original_rhymes.json").read_text(encoding="utf-8"))


def sample_brief(i: int = 0) -> dict:
    return json.loads(json.dumps(SAMPLES[i]))


def chat_response(content: str | dict, status: int = 200) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    return httpx.Response(status, json={"choices": [{"message": {"content": text}}], "usage": {"total_tokens": 10}})


def gemini_response(content: str | dict) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def no_sleep(_: float) -> None:
    return None
