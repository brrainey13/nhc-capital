"""LLM-powered code review engine — NVIDIA NIM primary, OpenRouter fallback.

Called by scripts/mr-review when --llm flag is used.
Returns guaranteed JSON findings via structured_outputs schema.

Fallback chain (all free, 20s timeout each):
  1. openai/gpt-oss-120b       (NVIDIA — ~2s, GPT-class)
  2. qwen/qwen3-next-80b       (NVIDIA — ~3s, excellent for code)
  3. moonshotai/kimi-k2-instruct (NVIDIA — ~3.5s, reliable)
  4. qwen/qwen3.5-122b-a10b    (NVIDIA — ~4.5s, solid)
  5. deepseek-ai/deepseek-v3.1  (NVIDIA — ~4s, thorough)
  6. OpenRouter free-tier       (last resort)
"""

import json
import os
import urllib.error
import urllib.request

OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"

# NVIDIA NIM providers — benchmarked 2026-03-05, ordered by speed + quality
NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
REVIEW_PROVIDERS = [
    {
        "base_url": NVIDIA_BASE,
        "api_key_env": "NVIDIA_API_KEY",
        "model": "openai/gpt-oss-120b",
        "label": "nvidia/gpt-oss-120b",
    },
    {
        "base_url": NVIDIA_BASE,
        "api_key_env": "NVIDIA_API_KEY",
        "model": "qwen/qwen3-next-80b-a3b-instruct",
        "label": "nvidia/qwen3-next-80b",
    },
    {
        "base_url": NVIDIA_BASE,
        "api_key_env": "NVIDIA_API_KEY",
        "model": "moonshotai/kimi-k2-instruct",
        "label": "nvidia/kimi-k2-instruct",
    },
    {
        "base_url": NVIDIA_BASE,
        "api_key_env": "NVIDIA_API_KEY",
        "model": "qwen/qwen3.5-122b-a10b",
        "label": "nvidia/qwen3.5-122b",
    },
    {
        "base_url": NVIDIA_BASE,
        "api_key_env": "NVIDIA_API_KEY",
        "model": "deepseek-ai/deepseek-v3.1",
        "label": "nvidia/deepseek-v3.1",
    },
]

# OpenRouter free-tier fallback (last resort)
OPENROUTER_MODELS = [
    "qwen/qwen3-coder:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "google/gemma-3-27b-it:free",
]

# JSON Schema for structured output — model MUST conform
FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "One paragraph summary of the overall code change quality",
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "File path where the issue was found",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "warning", "info"],
                        "description": "critical=must fix, warning=should fix, info=suggestion",
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "security",
                            "bug",
                            "performance",
                            "logic",
                            "style",
                            "architecture",
                            "testing",
                            "documentation",
                        ],
                    },
                    "message": {
                        "type": "string",
                        "description": "Clear description of the issue",
                    },
                    "suggestion": {
                        "type": "string",
                        "description": "Concrete fix or improvement suggestion",
                    },
                },
                "required": ["file", "severity", "category", "message"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "findings"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are a senior code reviewer for a Python/TypeScript monorepo.
You review pull request diffs and return structured findings.

Review criteria (in priority order):
1. SECURITY: hardcoded secrets, SQL injection, auth bypass, data exposure
2. BUGS: logic errors, null/undefined handling, race conditions, off-by-one
3. PERFORMANCE: O(n²) when O(n) possible, missing indexes, unnecessary DB calls
4. LOGIC: edge cases, error handling, missing validation
5. ARCHITECTURE: god files (>500 LOC), tight coupling, missing abstractions
6. TESTING: new code without tests, untested edge cases
7. STYLE: naming, dead code, unclear intent (only if egregious)

Rules:
- Only report real issues. Do NOT pad with noise.
- If the code is clean, return an empty findings array.
- Be specific: reference exact file paths and describe the issue precisely.
- Suggestions should be concrete — not "consider refactoring" but "extract X into Y".
- security and bug issues are CRITICAL. Performance and logic are WARNING. Style is INFO.
- Do NOT flag test files for hardcoded values (that's normal in tests).
- Do NOT flag config files for localhost references.

Project context (important — avoid false positives):
- The admin-dashboard is behind Cloudflare Access (Google OAuth + FastAPI middleware). ALL endpoints
  require authentication. Do NOT flag endpoints for "missing auth" unless the endpoint
  explicitly disables or bypasses the existing auth middleware.
- The dashboard runs on localhost:8000 behind Cloudflare Tunnel with a fixed domain. localhost
  references in dashboard code are expected.
- API keys are loaded from .env files (gitignored) or CI/CD variables. Reading keys from
  .env or environment variables is the correct pattern — do NOT flag this as "hardcoded secrets".
- scripts/ directory contains CI tooling that runs in trusted environments (local machine
  or GitHub Actions). These scripts legitimately access API tokens from environment variables.
- OAuth client IDs (e.g. OPENAI_CLIENT_ID) are PUBLIC identifiers, not secrets. Do NOT
  flag public client IDs as "hardcoded secrets" — they are safe to have as fallback defaults.
- GIT_ASKPASS with try/finally cleanup is the correct pattern for ephemeral CI credentials.
  Do NOT flag this as insecure if cleanup is in a finally block or trap handler.
- CI scripts run in ephemeral containers that are destroyed after each job. Temporary files
  in CI are acceptable when properly cleaned up."""


def review_diff(diff_text: str, changed_files: list[str], risk_tier: str) -> dict:
    """Send diff to LLM and get structured review findings.

    Returns: {"summary": str, "findings": [...], "model": str}

    Provider chain:
      1. NVIDIA GLM5 (primary — Opus-class)
      2. OpenRouter free models (fallback)
    """
    # Truncate diff if too large (keep under ~100K tokens)
    max_diff_chars = 200_000
    if len(diff_text) > max_diff_chars:
        diff_text = diff_text[:max_diff_chars] + "\n\n... (diff truncated)"

    user_msg = (
        f"Risk tier: {risk_tier.upper()}\n"
        f"Changed files ({len(changed_files)}):\n"
        + "\n".join(f"  - {f}" for f in changed_files)
        + f"\n\nDiff:\n```\n{diff_text}\n```"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    # 1. Try NVIDIA providers first
    for provider in REVIEW_PROVIDERS:
        api_key = os.environ.get(provider["api_key_env"], "")
        if not api_key:
            print(f"  Skipping {provider['label']}: {provider['api_key_env']} not set", flush=True)
            continue
        result = _call_provider(
            base_url=provider["base_url"],
            api_key=api_key,
            model=provider["model"],
            messages=messages,
        )
        if result is not None:
            result["model"] = provider["label"]
            return result

    # 2. Fallback to OpenRouter
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
    if openrouter_key:
        for model in OPENROUTER_MODELS:
            result = _call_provider(
                base_url="https://openrouter.ai/api/v1",
                api_key=openrouter_key,
                model=model,
                messages=messages,
            )
            if result is not None:
                result["model"] = model
                return result

    # 3. Last resort — NVIDIA Mistral Large 3 675B (slow but heavyweight)
    nvidia_key = os.environ.get("NVIDIA_API_KEY", "")
    if nvidia_key:
        result = _call_provider(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=nvidia_key,
            model="mistralai/mistral-large-3-675b-instruct-2512",
            messages=messages,
        )
        if result is not None:
            result["model"] = "nvidia/mistral-large-3-675b"
            return result

    return {
        "summary": "All review models failed (no API keys or all errored).",
        "findings": [],
        "model": None,
        "error": "all_models_failed",
    }


def _call_provider(
    base_url: str, api_key: str, model: str, messages: list
) -> dict | None:
    """Call an OpenAI-compatible provider with structured JSON output.

    Works with NVIDIA API, OpenRouter, and any OpenAI-compat endpoint.
    Returns parsed result or None on failure.
    """
    url = f"{base_url}/chat/completions"

    payload: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": 4096,
    }

    # Try structured_outputs first (OpenRouter/OpenAI style)
    # NVIDIA may not support json_schema — fall back to json_object
    use_json_schema = "openrouter" in base_url.lower()
    if use_json_schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "code_review",
                "strict": True,
                "schema": FINDINGS_SCHEMA,
            },
        }
    else:
        # For NVIDIA and others: request JSON mode + schema in system prompt
        payload["response_format"] = {"type": "json_object"}
        # Inject schema into system message so model knows the format
        schema_hint = (
            "\n\nYou MUST respond with valid JSON matching this exact schema:\n"
            + json.dumps(FINDINGS_SCHEMA, indent=2)
        )
        payload["messages"] = [
            {**messages[0], "content": messages[0]["content"] + schema_hint},
            *messages[1:],
        ]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )

    print(f"  Calling {model} via {base_url}...", flush=True)

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            # Validate required keys
            if "summary" not in parsed or "findings" not in parsed:
                print(f"  {model}: missing required keys in response", flush=True)
                return None
            print(
                f"  ✅ {model}: {len(parsed['findings'])} findings",
                flush=True,
            )
            return parsed
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            body = json.loads(e.read().decode())
            err_msg = body.get("error", {}).get("message", str(e))
        except Exception:
            err_msg = str(e)
        print(f"  ❌ {model}: HTTP {status} — {err_msg}", flush=True)
        return None
    except json.JSONDecodeError as e:
        print(f"  ❌ {model}: invalid JSON response — {e}", flush=True)
        return None
    except Exception as e:
        print(f"  ❌ {model}: {e}", flush=True)
        return None


if __name__ == "__main__":
    # Quick smoke test — uses a minimal diff
    test_diff = (
        "diff --git a/example.py b/example.py\n"
        "+def hello():\n"
        "+    print('hello world')\n"
    )
    result = review_diff(test_diff, ["example.py"], "low")
    print(json.dumps(result, indent=2))
