"""Provider model discovery shared by Qt and desktop jobs."""

from urllib.parse import urlsplit
from util.api_errors import concise_api_error
from util.translation_task import TaskSignal


API_URL_PRESETS = (
    ("OpenAI", "https://api.openai.com/v1"),
    ("Claude (Anthropic)", "https://api.anthropic.com/v1"),
    ("Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/"),
    ("DeepSeek", "https://api.deepseek.com/v1/"),
    ("Mistral", "https://api.mistral.ai/v1/"),
    ("Nvidia", "https://integrate.api.nvidia.com/v1/"),
    ("OpenRouter", "https://openrouter.ai/api/v1"),
)


class ModelCatalogCore:
    """Model discovery logic; UI adapters choose its execution thread."""

    # Fallback list shown when no API key is set or a fetch fails
    DEFAULTS = [
        "gpt-5.6-sol", "gpt-5.6-terra", "gpt-4.1-mini", "gpt-4.1", "gpt-4o", "gpt-4o-mini",
        "o3", "o4-mini",
        "claude-sonnet-5", "claude-opus-4-5", "claude-sonnet-4-6",
        "claude-sonnet-4-5", "claude-haiku-4-5",
        "gemini-3.6-flash", "gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro",
        "deepseek-chat",
        "mistral-medium-3-5",  # Free-mode recommendation; stable family alias
    ]

    def initialize(self, api_key, api_url, provider=None):
        self.api_key = api_key
        self.api_url = api_url.strip()
        self.provider = (provider or "").strip().lower()

    def run(self):
        models = []
        errors = []
        # Only attempt each provider's fetcher when the configured URL matches.
        # Avoids sending a DeepSeek (or other) key to Anthropic and getting a
        # spurious 401 authentication error.
        provider_fetchers = {
            "openai": self._fetch_openai,
            "anthropic": self._fetch_anthropic,
            "gemini": self._fetch_gemini,
        }
        if self.provider:
            fetcher = provider_fetchers.get(self.provider)
            if fetcher is None:
                self.fetch_error.emit(
                    f"Unsupported model-list provider: {self.provider}"
                )
                return
            fetchers = [fetcher]
        else:
            hostname = (urlsplit(self.api_url).hostname or "").lower()
            provider = "anthropic" if hostname == "api.anthropic.com" else "gemini" if hostname == "generativelanguage.googleapis.com" else "openai"
            fetchers = [provider_fetchers[provider]]
        for fetcher in fetchers:
            try:
                models.extend(fetcher())
            except Exception as exc:
                errors.append(concise_api_error(exc))
        if models:
            self.models_fetched.emit(sorted(set(models)))
        else:
            self.fetch_error.emit("\n".join(errors))

    def _fetch_openai(self):
        import openai
        # The SDK requires a non-empty value even when a local server ignores
        # authentication entirely.
        kwargs = {"api_key": self.api_key or "not-needed", "timeout": 15, "max_retries": 0}
        if self.api_url:
            kwargs["base_url"] = self.api_url
        client = openai.OpenAI(**kwargs)
        all_models = [m.id for m in client.models.list()]
        # When using a custom URL (non-OpenAI provider like DeepSeek), return all
        # model IDs unfiltered. An explicitly configured official OpenAI URL is
        # still OpenAI and must retain the chat-model filter.
        hostname = urlsplit(self.api_url).hostname if self.api_url else ""
        if hostname and hostname.lower() != "api.openai.com":
            return sorted(all_models)
        prefixes = ("gpt-", "o1", "o2", "o3", "o4", "chatgpt")
        return sorted(m for m in all_models if any(m.lower().startswith(p) for p in prefixes))

    def _fetch_anthropic(self):
        import anthropic
        kwargs = {"api_key": self.api_key, "timeout": 15, "max_retries": 0}
        if self.api_url:
            base_url = self.api_url.rstrip("/")
            if "api.anthropic.com" in base_url.lower() and base_url.endswith("/v1"):
                base_url = base_url[:-3]
            kwargs["base_url"] = base_url
        client = anthropic.Anthropic(**kwargs)
        return sorted(m.id for m in client.models.list(limit=100))

    def _fetch_gemini(self):
        import openai
        base = self.api_url or "https://generativelanguage.googleapis.com/v1beta/openai/"
        client = openai.OpenAI(api_key=self.api_key, base_url=base, timeout=15, max_retries=0)
        return sorted(
            m.id for m in client.models.list()
            if "gemini" in m.id.lower()
        )


class ModelCatalog(ModelCatalogCore):
    def __init__(self, api_key, api_url, provider=None):
        self.models_fetched = TaskSignal()
        self.fetch_error = TaskSignal()
        self.initialize(api_key, api_url, provider)
