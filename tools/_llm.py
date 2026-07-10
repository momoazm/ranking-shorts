"""Shared text-generation helper: one free-tier LLM call with an automatic fallback chain.

Order is ACCURACY-FIRST (Artificial Analysis index, checked 2026-07-10), not speed-first;
a provider whose key is unset, that errors, or that hits a rate limit is skipped for the
next link:
  1. Nemotron 3 Ultra 550B (OpenRouter :free) - AA 38, best model with a live free route
     (Kimi K2.6 / DeepSeek V4 Flash :free were verified GONE from OpenRouter 2026-07-10)
  2. Qwen3 Coder 480B (OpenRouter :free)      - strong structured/JSON output, 1M ctx
  3. GLM-4.7-Flash (Zhipu direct)             - permanently free; skipped until
     ZHIPU_API_KEY is set in API.env (sign up at bigmodel.cn / z.ai)
  4. gpt-oss-120b (Groq)                      - AA 24 but fast + 1K req/day
  5. gpt-oss-120b (Cerebras)                  - 1M tokens/day
  6. Gemini 2.5 Flash                         - proprietary tail
  7. Mistral                                  - last resort
OpenRouter :free caps at 50 req/day (1,000/day after a one-time $10 top-up); when the
cap trips, links 1-2 fail fast and Groq takes over - that's expected, not a bug.

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
        model=os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
        messages=messages, temperature=temperature, **kwargs
    )
    return completion.choices[0].message.content


def _openai_compatible(prompt, system, json_mode, temperature, *, env_key, base_url, model):
    """Cerebras / Mistral / OpenRouter / Zhipu all expose an OpenAI-compatible chat endpoint."""
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


def _openrouter(model):
    return lambda p, s, j, t: _openai_compatible(
        p, s, j, t, env_key="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1", model=model,
    )


def _zhipu(p, s, j, t):
    return _openai_compatible(
        p, s, j, t, env_key="ZHIPU_API_KEY",
        base_url=os.environ.get("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
        model=os.environ.get("ZHIPU_MODEL", "glm-4.7-flash"),
    )


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
        "gemini-2.5-flash", system_instruction=system, generation_config=generation_config
    )
    return model.generate_content(prompt).text


# Ordered best-accuracy-first. Each entry: (provider_name, callable(prompt, system, json_mode, temperature)).
_CHAIN = [
    ("openrouter-nemotron", _openrouter(os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free"))),
    ("openrouter-qwen-coder", _openrouter("qwen/qwen3-coder:free")),
    ("zhipu", _zhipu),
    ("groq", _groq),
    (
        "cerebras",
        lambda p, s, j, t: _openai_compatible(
            p, s, j, t, env_key="CEREBRAS_API_KEY",
            base_url="https://api.cerebras.ai/v1",
            model=os.environ.get("CEREBRAS_MODEL", "gpt-oss-120b"),
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
            errors[name] = str(e)[:300]
    raise RuntimeError(
        "Whole LLM fallback chain failed (Nemotron->QwenCoder->Zhipu->Groq->Cerebras->Gemini->Mistral). "
        "Per-provider errors: " + json.dumps(errors)
    )


def _data_uri(path):
    import base64
    mime = "image/png" if str(path).lower().endswith(".png") else "image/jpeg"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii")


def _vision_openai_compatible(image_paths, prompt, system, json_mode, temperature,
                              *, env_key, base_url, model, client_cls=None):
    """OpenAI-style multimodal call (image_url data-URI parts). Used by Groq and Zhipu."""
    key = os.environ.get(env_key)
    if not key:
        raise RuntimeError(f"{env_key} not set")
    content = [{"type": "text", "text": prompt}]
    for p in image_paths:
        content.append({"type": "image_url", "image_url": {"url": _data_uri(p)}})
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": content}
    ]
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    if client_cls is None:
        from openai import OpenAI as client_cls_default
        client = client_cls_default(api_key=key, base_url=base_url)
    else:
        client = client_cls(api_key=key)
    completion = client.chat.completions.create(
        model=model, messages=messages, temperature=temperature, **kwargs)
    return completion.choices[0].message.content


def _groq_vision(image_paths, prompt, system, json_mode, temperature):
    """Groq multimodal Llama-4 Scout. DEPRECATED BY GROQ 2026-07-17 — kept as the first
    link only until then (fails fast afterwards and the chain moves on). Remove this link
    once it starts erroring."""
    from groq import Groq
    return _vision_openai_compatible(
        image_paths, prompt, system, json_mode, temperature,
        env_key="GROQ_API_KEY", base_url=None,
        model="meta-llama/llama-4-scout-17b-16e-instruct", client_cls=Groq)


def _zhipu_vision(image_paths, prompt, system, json_mode, temperature):
    """Zhipu GLM-4.6V-Flash — permanently free vision model; skipped until ZHIPU_API_KEY
    is set in API.env."""
    return _vision_openai_compatible(
        image_paths, prompt, system, json_mode, temperature,
        env_key="ZHIPU_API_KEY",
        base_url=os.environ.get("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
        model=os.environ.get("ZHIPU_VISION_MODEL", "glm-4.6v-flash"))


def vision_complete(image_paths, prompt, system=None, json_mode=True, temperature=0.3):
    """One image+text call with a fallback chain (Groq-vision -> Zhipu-vision -> Gemini-vision).
    Groq's vision model retires 2026-07-17; after that Zhipu (once its key is set) and Gemini
    carry vision. Returns {"text","provider"}; raises RuntimeError only if ALL fail, so a
    caller can degrade gracefully (Gemini alone hit a 429 quota in testing 2026-07-09 --
    non-Gemini links first avoid losing time-critical live clips)."""
    errors = {}
    for name, fn in (("groq", _groq_vision), ("zhipu", _zhipu_vision),
                     ("gemini", _gemini_vision_impl)):
        try:
            text = fn(image_paths, prompt, system, json_mode, temperature)
            if text and text.strip():
                return {"text": text, "provider": name}
            errors[name] = "empty response"
        except Exception as e:
            errors[name] = str(e)[:200]
    raise RuntimeError("Whole vision chain failed (Groq->Zhipu->Gemini): " + json.dumps(errors))


def _gemini_vision_impl(image_paths, prompt, system, json_mode, temperature):
    import google.generativeai as genai

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    genai.configure(api_key=key)
    gen_cfg = {"temperature": temperature}
    if json_mode:
        gen_cfg["response_mime_type"] = "application/json"
    model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=system,
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
    should use vision_complete(), which falls back Groq->Zhipu->Gemini."""
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
