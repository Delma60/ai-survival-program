# scripts/check_llm.py
"""Phase 0 check: confirm Ollama answers with valid JSON and measure speed.

Run from the project root:  python scripts/check_llm.py
"""
import json
import sys
import time
from pathlib import Path

import yaml
from openai import OpenAI, OpenAIError

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    low = cfg["low_spec"]
    llm = cfg.get("llm", {})
    client = OpenAI(
        base_url=str(llm.get("base_url", "http://localhost:11434/v1")),
        api_key="ollama",
        timeout=float(llm.get("timeout_seconds", 120)),
    )

    start = time.perf_counter()
    try:
        r = client.chat.completions.create(
            model=low["model"],
            messages=[
                {"role": "system", "content": "Reply with JSON only."},
                {
                    "role": "user",
                    "content": 'Choose "work" or "end_day". '
                    'Return {"action": "...", "note": "..."}',
                },
            ],
            response_format={"type": "json_object"},
            max_tokens=low["num_predict"],
            temperature=float(llm.get("temperature", 0.7)),
            extra_body={"options": {"num_ctx": int(low["num_ctx"])}},
        )
    except OpenAIError as exc:
        print(f"FAIL: could not reach model '{low['model']}': {exc}")
        return 1
    elapsed = time.perf_counter() - start

    text = r.choices[0].message.content or ""
    print("Raw reply:", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"FAIL: reply is not valid JSON: {exc}")
        return 1

    valid = {"work", "end_day"}
    if data.get("action") not in valid:
        print(f"FAIL: 'action' must be one of {sorted(valid)}, got {data.get('action')!r}")
        return 1

    tokens = r.usage.completion_tokens if r.usage else 0
    rate = tokens / elapsed if elapsed and tokens else 0.0
    print(f"PASS: valid JSON. {tokens} tokens in {elapsed:.1f}s (~{rate:.1f} tokens/s incl. load time)")
    if rate and rate < 2:
        print("WARNING: under 2 tokens/s. Consider a 1.5B model (see blueprint 14.3).")
    return 0


if __name__ == "__main__":
    sys.exit(main())