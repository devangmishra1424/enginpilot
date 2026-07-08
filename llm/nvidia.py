"""Thin wrapper around NVIDIA Build hosted endpoints (Playbook Section 3.2).

temperature=0 always — this system needs faithful phrasing, not creativity
(Execution Plan, "Confirmed model choices").
"""

import os

from dotenv import load_dotenv
from langchain_nvidia_ai_endpoints import ChatNVIDIA

load_dotenv()

DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"

_clients: dict[str, ChatNVIDIA] = {}


def _get_client(model: str) -> ChatNVIDIA:
    """One cached ChatNVIDIA client per model id."""
    if model not in _clients:
        api_key = os.getenv("NVIDIA_API_KEY")
        if not api_key:
            raise RuntimeError(
                "NVIDIA_API_KEY is not set. Add it to a .env file at the repo root "
                "(NVIDIA_API_KEY=nvapi-...) before calling the NVIDIA endpoints."
            )
        # timeout=180: NVIDIA Build's free inference tier queues requests under
        # load (confirmed 275-deep queue for llama-3.3-70b at one point) — the
        # client's 60s default isn't enough to survive that wait. A hang or
        # timeout here likely means the free tier is under load, not a bug.
        _clients[model] = ChatNVIDIA(model=model, api_key=api_key, temperature=0, timeout=180)
    return _clients[model]


def generate(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Send prompt to the given NVIDIA-hosted model, return the response text."""
    client = _get_client(model)
    response = client.invoke(prompt)
    return response.content
