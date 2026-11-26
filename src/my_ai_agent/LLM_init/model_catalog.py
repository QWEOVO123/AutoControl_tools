"""Read DeepSeek's context and output limits through the configured API client."""

from dataclasses import dataclass
from threading import Lock
from time import monotonic

from openai import APIError

from ..deepseek_api import BASE_URL

FALLBACK_INPUT_BUDGET = 120_000
SUMMARY_MAX_TOKENS = 2048
DEFAULT_OUTPUT_TOKENS = {"none": 8192, "low": 65536, "high": 65536, "max": 131072}
MODEL_ALIASES = {
    "deepseek-v4-flash": "deepseek-flash",
    "deepseek-v4-flash-vision-exp": "deepseek-flash",
}


def positive_int(value) -> int | None:
    return value if type(value) is int and value > 0 else None


@dataclass(frozen=True)
class ModelLimits:
    context_window: int
    max_output_tokens: int | None = None

    def input_budget(self, effort: str, requested_output: int | None = None) -> int:
        output = requested_output or DEFAULT_OUTPUT_TOKENS[effort]
        if self.max_output_tokens is not None:
            output = min(output, self.max_output_tokens)
        return max(1, self.context_window - output - (self.context_window + 9) // 10)


class DeepSeekModelCatalog:
    def __init__(self):
        self.lock = Lock()
        self.cache: dict[str, tuple[float, dict[str, ModelLimits]]] = {}

    def limits_for(self, model) -> ModelLimits | None:
        client = getattr(model, "root_client", None)
        if client is None:
            return None
        base_url = str(client.base_url)
        with self.lock:
            expires, catalog = self.cache.get(base_url, (0, {}))
            if expires <= monotonic():
                catalog = self._fetch(client)
                self.cache[base_url] = (monotonic() + (300 if catalog else 30), catalog)
        name = model.model_name
        return catalog.get(name) or catalog.get(MODEL_ALIASES.get(name, ""))

    @staticmethod
    def _fetch(client) -> dict[str, ModelLimits]:
        base_url = str(client.base_url).rstrip("/")
        # LangChain defaults to /v1 for chat. DeepSeek documents /models at the API root.
        if base_url == f"{BASE_URL}/v1":
            base_url = BASE_URL
        try:
            payload = client.with_options(base_url=base_url, timeout=3.0, max_retries=0).get("/models", cast_to=object)
        except (APIError, ValueError):
            return {}
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return {}
        catalog = {}
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            window = positive_int(item.get("context_window"))
            if window is not None:
                catalog[item["id"]] = ModelLimits(window, positive_int(item.get("max_output_tokens")))
        return catalog
