import os

def env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)

CHATWOOT_BASE_URL = env("CHATWOOT_BASE_URL")
CHATWOOT_API_TOKEN = env("CHATWOOT_API_TOKEN")
OPENAI_API_KEY = env("OPENAI_API_KEY")
REDIS_URL = env("REDIS_URL", "redis://redis:6379/0")
TZ = env("TZ", "America/Sao_Paulo")
