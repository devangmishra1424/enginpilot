"""Ollama fallback — reserved for Day 14 (Phase 6, demo hardening).

Not implemented yet: the real circuit-breaker logic (NVIDIA timeout/error ->
fall back to local Ollama) belongs to router.py once this is built out.
"""


def generate(prompt: str) -> str:
    raise NotImplementedError("Ollama fallback is a Day 14 task, not yet built")
