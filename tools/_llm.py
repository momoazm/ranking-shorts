"""Shared text-generation helper: one free-tier LLM call with an automatic fallback chain.

Order (best free-tier first; a provider whose key is unset, that errors, or that hits a
rate limit is skipped for the next): Groq -> Cerebras -> Gemini -> Mistral -> OpenRouter.
This mirrors the chain documented in the competitor project's SOP so behavior is consistent
across WAT projects.

`llm_complete()` returns {"text": ..., "provider": ...}. It raises RuntimeError with the
per-provider errors collected only if the WHOLE chain fails — callers should surface that to
the user before retrying anything (don't loop silently on metered APIs).

Set `json_mode=True` to ask the model for a single JSON object; callers should still parse
defensively via `parse_json()`, which strips ```json fences before json.loads.
"""
import json
import os
import re


def _groq(prompt, system, json_mode, temperature):
    from groq import Groq

    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set")
    client = Groq(api_key=key)
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile", messages=messages, temperature=temperature, **kwargs
    )
    return completion.choices[0].message.content


def _openai_compatible(prompt, system, json_mode, temperature, *, env_key, base_url, model):
    """Cerebras / Mistral / OpenRouter all expose an OpenAI-compatible chat endpoint."""
    from openai import OpenAI

    key = os.environ.get(env_key)
    if not key:
        raise RuntimeError(f"{env_key} not set")
    client = OpenAI(api_key=key, base_url=base_url)
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    completion = client.chat.completions.create(
        model=model, messages=messages, temperature=temperature, **kwargs
    )
    return completion.choices[0].message.content


def _gemini(prompt, system, json_mode, temperature):
    import google.generativeai as genai

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    genai.configure(api_key=key)
    generation_config = {"temperature": temperature}
    if json_mode:
        generation_config["response_mime_type"] = "application/json"
    model = genai.GenerativeModel(
        "gemini-2.0-flash", system_instruction=system, generation_config=generation_config
    )
    return model.generate_content(prompt).text


# Ordered best-first. Each entry: (provider_name, callable(prompt, system, json_mode, temperature)).
_CHAIN = [
    ("groq", _groq),
    (
        "cerebras",
        lambda p, s, j, t: _openai_compatible(
            p, s, j, t, env_key="CEREBRAS_API_KEY",
            base_url="https://api.cerebras.ai/v1", model="llama-3.3-70b",
        ),
    ),
    ("gemini", _gemini),
    (
        "mistral",
        lambda p, s, j, t: _openai_compatible(
            p, s, j, t, env_key="MISTRAL_API_KEY",
            base_url="https://api.mistral.ai/v1", model="mistral-large-latest",
        ),
    ),
    (
        "openrouter",
        lambda p, s, j, t: _openai_compatible(
            p, s, j, t, env_key="OPENROUTER_API_KEY",
            base_url="https://openrouter.ai/api/v1",
            model="meta-llama/llama-3.3-70b-instruct:free",
        ),
    ),
]


def llm_complete(prompt, system=None, json_mode=False, temperature=0.8):
    errors = {}
    for name, fn in _CHAIN:
        try:
            text = fn(prompt, system, json_mode, temperature)
            if text and text.strip():
                return {"text": text, "provider": name}
            errors[name] = "empty response"
        except Exception as e:
            errors[name] = str(e)
    raise RuntimeError(
        "Whole LLM fallback chain failed (Groq->Cerebras->Gemini->Mistral->OpenRouter). "
        "Per-provider errors: " + json.dumps(errors)
    )


def _data_uri(path):
    import base64
    mime = "image/png" if str(path).lower().endswith(".png") else "image/jpeg"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii")


def _groq_vision(image_paths, prompt, system, json_mode, temperature):
    """Groq's multimodal Llama-4 (OpenAI-compatible image parts). Groq is our best free-tier
    quota, so it's tried before Gemini for vision too."""
    from groq import Groq

    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set")
    content = [{"type": "text", "text": prompt}]
    for p in image_paths:
        content.append({"type": "image_url", "image_url": {"url": _data_uri(p)}})
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": content}
    ]
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    completion = Groq(api_key=key).chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct", messages=messages,
        temperature=temperature, **kwargs)
    return completion.choices[0].message.content


def vision_complete(image_paths, prompt, system=None, json_mode=True, temperature=0.3):
    """One image+text call with a fallback chain (Groq-vision -> Gemini-vision). These are the
    only two vision-capable links on our free keys. Returns {"text","provider"}; raises
    RuntimeError only if BOTH fail, so a caller can degrade gracefully (Gemini alone hit a 429
    quota in testing 2026-07-09 -- Groq first avoids losing time-critical live clips)."""
    errors = {}
    for name, fn in (("groq", _groq_vision), ("gemini", _gemini_vision_impl)):
        try:
            text = fn(image_paths, prompt, system, json_mode, temperature)
            if text and text.strip():
                return {"text": text, "provider": name}
            errors[name] = "empty response"
        except Exception as e:
            errors[name] = str(e)[:200]
    raise RuntimeError("Whole vision chain failed (Groq->Gemini): " + json.dumps(errors))


def _gemini_vision_impl(image_paths, prompt, system, json_mode, temperature):
    import google.generativeai as genai

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    genai.configure(api_key=key)
    gen_cfg = {"temperature": temperature}
    if json_mode:
        gen_cfg["response_mime_type"] = "application/json"
    model = genai.GenerativeModel("gemini-2.0-flash", system_instruction=system,
                                  generation_config=gen_cfg)
    parts = [prompt]
    for p in image_paths:
        with open(p, "rb") as f:
            data = f.read()
        mime = "image/png" if str(p).lower().endswith(".png") else "image/jpeg"
        parts.append({"mime_type": mime, "data": data})
    return (model.generate_content(parts).text or "").strip()


def gemini_vision(image_paths, prompt, system=None, json_mode=True, temperature=0.3):
    """Gemini-only vision call (kept for callers that specifically want Gemini). Most callers
    should use vision_complete(), which falls back Groq->Gemini."""
    text = _gemini_vision_impl(image_paths, prompt, system, json_mode, temperature)
    if not text:
        raise RuntimeError("Gemini vision returned an empty response")
    return {"text": text, "provider": "gemini"}


def parse_json(text):
    """Parse a JSON object out of an LLM response, tolerating ```json code fences."""
    fenced = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    return json.loads(text.strip())
