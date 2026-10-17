"""Swappable LLM client interface. Local Ollama today, a cloud API later."""

from typing import Any, Dict, Protocol

from openai import OpenAI, OpenAIError


class LLMError(RuntimeError):
    """Raised when the model cannot be reached or returns an error."""


class LLMClient(Protocol):
    """Anything that can turn a system+user prompt into reply text."""

    def complete(self, system: str, user: str) -> str: ...


class OllamaClient:
    """OpenAI-compatible client for a local Ollama server."""

    def __init__(self, config: Dict[str, Any]) -> None:
        low_spec = config["low_spec"]
        llm = config.get("llm", {})
        self._model = str(low_spec["model"])
        self._max_tokens = int(low_spec["num_predict"])
        self._num_ctx = int(low_spec["num_ctx"])
        self._temperature = float(llm.get("temperature", 0.7))
        self._client = OpenAI(
            base_url=str(llm.get("base_url", "http://localhost:11434/v1")),
            api_key="ollama",
            timeout=float(llm.get("timeout_seconds", 120)),
        )

    def complete(self, system: str, user: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                extra_body={"options": {"num_ctx": self._num_ctx}},
            )
        except OpenAIError as exc:
            raise LLMError(str(exc)) from exc
        if not response.choices:
            raise LLMError("model returned no choices")
        return response.choices[0].message.content or ""
