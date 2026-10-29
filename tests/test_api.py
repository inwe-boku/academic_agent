import pytest
import requests

from academic_agent.api import (ApiClient, ApiError, Config, ConfigError,
                                ModelInfo, TransientApiError, supports_json_mode)


class Response:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code = status
        self.ok = status < 400
        self._data = data
        self.headers = headers or {}
        self.text = str(data)

    def json(self):
        return self._data


def ok(content="{}", prompt=10, completion=5):
    return Response(200, {"data": {"content": content,
                                   "usage": {"promptTokens": prompt,
                                             "completionTokens": completion}}})


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []

    def post(self, url, headers, json, timeout):
        self.payloads.append(json)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def client(responses, model="mistral-large"):
    sleeps = []
    http = FakeHttp(responses)
    api = ApiClient(Config("https://h", "id", "secret", model), http=http,
                    sleep=sleeps.append)
    return api, http, sleeps


def test_usage_and_json_mode():
    api, http, _ = client([ok("hi", 7, 3)])
    result = api.chat([{"role": "user", "content": "x"}])
    assert (result.content, result.prompt_tokens, result.completion_tokens) == ("hi", 7, 3)
    assert http.payloads[0]["responseFormat"] == {"type": "json_object"}


def test_no_json_mode_for_reasoning_models():
    assert not supports_json_mode("gpt-5-mini")
    assert not supports_json_mode("o3")
    assert supports_json_mode("gpt-4o")
    api, http, _ = client([ok()], model="gpt-5")
    api.chat([])
    assert "responseFormat" not in http.payloads[0]


def test_json_mode_rejected_falls_back():
    api, http, _ = client([Response(400, {"error": "unsupported"}), ok()])
    api.chat([])
    assert "responseFormat" in http.payloads[0]
    assert "responseFormat" not in http.payloads[1]
    assert api.json_mode is False


def test_retry_delays_and_retry_after():
    api, _, sleeps = client([
        requests.ConnectionError(), Response(503), Response(429, headers={"Retry-After": "7"}),
        ok("done"),
    ])
    assert api.chat([]).content == "done"
    assert sleeps == [2, 5, 7]
    assert (api.last_retries, api.last_retry_wait) == (3, 14)
    api.http.responses.append(ok())
    api.chat([])
    assert (api.last_retries, api.last_retry_wait) == (0, 0)


def test_retries_exhausted():
    api, _, sleeps = client([Response(500)] * 5)
    with pytest.raises(TransientApiError):
        api.chat([])
    assert sleeps == [2, 5, 15, 30]


def test_client_error_not_retried():
    api, _, sleeps = client([Response(401, {"error": "bad"})], model="gpt-5")
    with pytest.raises(ApiError, match="HTTP 401"):
        api.chat([])
    assert sleeps == []


def test_config_validation():
    with pytest.raises(ConfigError, match="ACADEMIC_AI_CLIENT_ID"):
        Config.from_env({"ACADEMIC_AI_BASE_URL": "https://h"}).validate()
    Config.from_env({"ACADEMIC_AI_BASE_URL": "https://h/", "ACADEMIC_AI_CLIENT_ID": "i",
                     "ACADEMIC_AI_CLIENT_SECRET": "s", "ACADEMIC_AI_MODEL": "m"}).validate()


def test_model_info_cost():
    info = ModelInfo.from_api({
        "modelName": "gpt-5", "contextWindow": 400000,
        "costs": [{"costType": "input_tokens", "cost": 0.001},
                  {"costType": "output_tokens", "cost": 0.01}],
    })
    assert info.context_window == 400000
    assert info.cost(1000, 100) == pytest.approx(0.002)
    assert ModelInfo("m").cost(1, 1) is None
    # /models reports prices per 1,000 tokens (gpt-5: 0.00138 in, 0.011 out)
    gpt5 = ModelInfo.from_api({"modelName": "gpt-5", "costs": [
        {"costType": "input_tokens", "cost": 0.00138},
        {"costType": "output_tokens", "cost": 0.011}]})
    assert gpt5.cost(73_459, 4_069) == pytest.approx(0.1461, abs=1e-4)


def test_reasoning_effort_sent_to_reasoning_models_only():
    cfg = Config("https://h", "id", "secret", "gpt-5", reasoning_effort="low")
    http = FakeHttp([ok()])
    ApiClient(cfg, http=http).chat([])
    assert http.payloads[0]["reasoningEffort"] == "low"
    cfg.model = "gpt-4o"
    http = FakeHttp([ok()])
    ApiClient(cfg, http=http).chat([])
    assert "reasoningEffort" not in http.payloads[0]


def test_reasoning_effort_rejected_falls_back():
    cfg = Config("https://h", "id", "secret", "o3", reasoning_effort="high")
    http = FakeHttp([Response(400, {"error": "unsupported"}), ok()])
    api = ApiClient(cfg, http=http)
    api.chat([])
    assert "reasoningEffort" in http.payloads[0]
    assert "reasoningEffort" not in http.payloads[1]
    assert api.reasoning_effort == ""


def test_reasoning_effort_from_env_and_validated():
    env = {"ACADEMIC_AI_BASE_URL": "h", "ACADEMIC_AI_CLIENT_ID": "i",
           "ACADEMIC_AI_CLIENT_SECRET": "s", "ACADEMIC_AI_MODEL": "gpt-5",
           "ACADEMIC_AI_REASONING_EFFORT": " Low "}
    cfg = Config.from_env(env)
    cfg.validate()
    assert cfg.reasoning_effort == "low"
    env["ACADEMIC_AI_REASONING_EFFORT"] = "fast"
    with pytest.raises(ConfigError, match="REASONING_EFFORT"):
        Config.from_env(env).validate()
