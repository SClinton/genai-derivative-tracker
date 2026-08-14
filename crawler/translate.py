"""
Translation helper for the crawler.

Uses the Google Cloud Translation API (v2, simple REST) to translate short
search-modifier terms (e.g. "presentation", "training course") into target
languages. Resource titles themselves are NOT translated by default — proper
nouns like "OWASP Top 10 for LLM Applications" are usually kept in English
even in foreign-language content, so translating them would likely hurt
recall rather than help it.

Translations are cached to data/translation_cache.json (committed to the
repo by the GitHub Action) so repeat runs don't re-spend API quota on the
same static modifier terms.
"""

import json
import os
from pathlib import Path

import requests

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "translation_cache.json"
TRANSLATE_ENDPOINT = "https://translation.googleapis.com/language/translate/v2"


def _load_cache():
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def translate_text(text, target_lang, source_lang="en"):
    """Translate `text` into `target_lang`. Falls back to the original text
    if no API key is configured or the request fails — the crawler should
    keep working (just without localized modifiers) rather than hard-fail."""
    if not text or target_lang == source_lang:
        return text

    cache = _load_cache()
    cache_key = f"{source_lang}:{target_lang}:{text}"
    if cache_key in cache:
        return cache[cache_key]

    api_key = os.environ.get("GOOGLE_TRANSLATE_API_KEY")
    if not api_key:
        return text

    try:
        resp = requests.post(
            TRANSLATE_ENDPOINT,
            params={"key": api_key},
            json={"q": text, "source": source_lang, "target": target_lang, "format": "text"},
            timeout=15,
        )
        resp.raise_for_status()
        translated = resp.json()["data"]["translations"][0]["translatedText"]
    except Exception as e:
        print(f"  ! translation failed for '{text}' -> {target_lang}: {e}")
        translated = text

    cache[cache_key] = translated
    _save_cache(cache)
    return translated
