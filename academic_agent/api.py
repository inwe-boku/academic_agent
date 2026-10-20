"""Academic AI HTTP client: chat, models, retry and usage."""

import json
import os
import re
import time
from dataclasses import dataclass

import requests

# Seconds to wait between retries of a failed API call (one entry per retry).
RETRY_DELAYS = [2, 5, 15, 30]
MAX_RETRY_AFTER = 300


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class TransientApiError(ApiError):
    """Network problem or HTTP 429/5xx; worth retrying."""

    def __init__(self, message, status=None, retry_after=None):
        super().__init__(message, status)
        self.retry_after = retry_after


class ConfigError(RuntimeError):
    pass


@dataclass
class Config:
    base_url: str
    client_id: str
    client_secret: str
    model: str

    @classmethod
    def from_env(cls, env=None) -> "Config":
        env = os.environ if env is None else env
        return cls(
            base_url=env.get("ACADEMIC_AI_BASE_URL", "").rstrip("/"),
            client_id=env.get("ACADEMIC_AI_CLIENT_ID", ""),
            client_secret=env.get("ACADEMIC_AI_CLIENT_SECRET", ""),
            model=env.get("ACADEMIC_AI_MODEL", ""),
        )

    def validate(self, need_model=True) -> None:
        missing = [name for name, value in (
            ("ACADEMIC_AI_BASE_URL", self.base_url),
            ("ACADEMIC_AI_CLIENT_ID", self.client_id),
            ("ACADEMIC_AI_CLIENT_SECRET", self.client_secret),
            ("ACADEMIC_AI_MODEL", self.model if need_model else "x"),
        ) if not value or value.startswith("REPLACE_WITH")]
        if missing:
            raise ConfigError(
                "Not configured: " + ", ".join(missing)
                + ". See docs/configuration.md."
            )


@dataclass
class ChatResult:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class ModelInfo:
    name: str
    context_window: int | None = None
    input_cost: float | None = None   # USD per token
    output_cost: float | None = None

    @classmethod
    def from_api(cls, data: dict) -> "ModelInfo":
        costs = {c.get("costType"): c.get("cost")
                 for c in data.get("costs") or [] if isinstance(c, dict)}
        return cls(
            name=data.get("modelName", ""),
            context_window=data.get("contextWindow"),
            input_cost=costs.get("input_tokens"),
            output_cost=costs.get("output_tokens"),
        )

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float | None:
        if self.input_cost is None or self.output_cost is None:
            return None
        return prompt_tokens * self.input_cost + completion_tokens * self.output_cost


def supports_json_mode(model: str) -> bool:
    """responseFormat is documented for standard OpenAI and Mistral models,
    not for reasoning models (o-series, gpt-5 family)."""
    return not re.match(r"(o\d|gpt-5)", model.lower())


def _retry_after(response) -> float | None:
    value = response.headers.get("Retry-After")
    try:
        return min(float(value), MAX_RETRY_AFTER) if value else None
    except ValueError:
        return None


class ApiClient:
    def __init__(self, config: Config, http=None, sleep=time.sleep,
                 on_retry=None):
        self.config = config
        self.http = http or requests
        self.sleep = sleep
        self.on_retry = on_retry
        self.json_mode = supports_json_mode(config.model)

    def _headers(self) -> dict:
        return {
            "X-Client-ID": self.config.client_id,
            "X-Client-Secret": self.config.client_secret,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _post_once(self, payload: dict) -> ChatResult:
        try:
            response = self.http.post(
                f"{self.config.base_url}/api/v1/llm/chat",
                headers=self._headers(), json=payload, timeout=180,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise TransientApiError(type(exc).__name__) from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise TransientApiError(f"HTTP {response.status_code}",
                                    response.status_code, _retry_after(response))
        if not response.ok:
            raise ApiError(
                f"Academic AI API returned HTTP {response.status_code}:\n"
                f"{response.text[:4000]}", response.status_code,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise TransientApiError("invalid JSON in response") from exc
        try:
            content = data["data"]["content"]
        except (KeyError, TypeError):
            raise ApiError(
                "Could not find assistant text in the API response.\n"
                + json.dumps(data, indent=2)[:4000]
            ) from None
        usage = (data.get("data") or {}).get("usage") or {}
        return ChatResult(
            content=content or "",
            prompt_tokens=int(usage.get("promptTokens") or 0),
            completion_tokens=int(usage.get("completionTokens") or 0),
        )

    def chat(self, messages: list[dict], json_mode=True) -> ChatResult:
        """POST /api/v1/llm/chat, retrying transient failures."""
        attempt = 0
        while True:
            payload = {"model": self.config.model, "messages": messages}
            use_json = json_mode and self.json_mode
            if use_json:
                payload["responseFormat"] = {"type": "json_object"}
            try:
                return self._post_once(payload)
            except TransientApiError as exc:
                if attempt == len(RETRY_DELAYS):
                    raise
                delay = exc.retry_after or RETRY_DELAYS[attempt]
                attempt += 1
                if self.on_retry:
                    self.on_retry(exc, delay, attempt, len(RETRY_DELAYS))
                self.sleep(delay)
            except ApiError as exc:
                # The model may not accept responseFormat: retry without it.
                if use_json and exc.status in (400, 422):
                    self.json_mode = False
                    continue
                raise

    def models(self) -> list[dict]:
        response = self.http.get(
            f"{self.config.base_url}/api/v1/llm/models",
            headers=self._headers(), timeout=30,
        )
        response.raise_for_status()
        return response.json()["data"]

    def model_info(self) -> ModelInfo | None:
        for data in self.models():
            if data.get("modelName") == self.config.model:
                return ModelInfo.from_api(data)
        return None
