import os
from .config import CFG


def available() -> bool:
    k = os.environ.get("OPENAI_API_KEY")
    return bool(CFG["llm"]["enabled"] and k)


def complete(system: str, user: str, max_tokens: int = 400) -> str:
    """One call to the model set in config.yaml (llm.model = your Azure deployment name).
    Endpoint comes from OPENAI_BASE_URL in .env (Azure AI Foundry: https://<resource>.services.ai.azure.com/openai/v1)."""
    from openai import OpenAI
    r = OpenAI().responses.create(
        model=CFG["llm"]["model"], instructions=system, input=user,
        max_output_tokens=max(max_tokens, 400))   # reasoning models spend part of the budget thinking
    return (r.output_text or "").strip()
