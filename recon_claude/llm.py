"""Thin wrapper around the Anthropic SDK for schema-constrained calls.

Every Claude call in the project goes through ClaudeClient.structured(), which
returns a parsed JSON object that conforms to the supplied JSON schema. All API
and output problems (refusal, truncation, bad JSON) become LLMError so that a
failed call stops the run instead of producing partial results.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

import anthropic

from .errors import LLMError

logger = logging.getLogger(__name__)


class ClaudeClient:
    """Calls one Claude model and returns structured (schema-valid) JSON."""

    def __init__(
        self,
        model: str,
        effort: str = "medium",
        max_tokens: int = 32000,
        client: Optional[anthropic.Anthropic] = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self._client = client
        self._lock = threading.Lock()
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    def _sdk(self) -> anthropic.Anthropic:
        # Created lazily so that constructing the pipeline never needs credentials.
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        meta: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Send one request and return the parsed JSON object.

        `meta` describes the task for logging (and lets tests substitute a fake
        client); it is never sent to the API.
        """
        label = (meta or {}).get("label", "call")
        logger.debug("Claude call: %s", label)
        try:
            with self._sdk().messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
            ) as stream:
                message = stream.get_final_message()
        except anthropic.APIStatusError as exc:
            raise LLMError(f"{label}: API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"{label}: could not reach the API: {exc}") from exc
        except anthropic.AnthropicError as exc:
            raise LLMError(f"{label}: {exc}") from exc

        with self._lock:
            self.usage["calls"] += 1
            self.usage["input_tokens"] += message.usage.input_tokens
            self.usage["output_tokens"] += message.usage.output_tokens

        if message.stop_reason == "refusal":
            detail = getattr(message, "stop_details", None)
            raise LLMError(f"{label}: request was refused by the model ({detail})")
        if message.stop_reason == "max_tokens":
            raise LLMError(f"{label}: output was truncated at max_tokens; use smaller chunks")

        text = "".join(block.text for block in message.content if block.type == "text")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"{label}: response was not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise LLMError(f"{label}: expected a JSON object, got {type(parsed).__name__}")
        return parsed
