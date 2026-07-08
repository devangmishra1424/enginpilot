"""One-line-swappable model routing (Execution Plan 1.2).

If a model gets deprecated or a better one comes online, only MODEL_REGISTRY
changes — no caller of generate() has to change.
"""

from llm import nvidia

# Why these models: repeated live testing (isolated tests, multiple sessions,
# playground + real API) has consistently shown Meta-hosted models
# (llama-3.1-8b-instruct, llama-3.1-70b-instruct) responding reliably in
# under a few seconds, while NVIDIA-native/Nemotron-branded models
# (llama-3.3-70b-instruct, nvidia/llama-3.1-nemotron-nano-8b-v1) consistently
# hang the full 180s timeout across independent sessions. This is a
# hosting-path issue specific to NVIDIA/Nemotron branding on the free tier,
# not a model-size issue — llama-3.1-70b-instruct (also 70B, Meta-hosted) is
# reliable where llama-3.3-70b-instruct (also 70B, NVIDIA-hosted) hangs.
# Revisit if NVIDIA's free-tier hosting changes, or the team moves to a paid
# tier.
MODEL_REGISTRY = {
    "articulation": "meta/llama-3.1-70b-instruct",
    "routing": "meta/llama-3.1-8b-instruct",
}


def generate(prompt: str, role: str = "articulation") -> str:
    if role not in MODEL_REGISTRY:
        raise ValueError(f"Unknown role: {role!r}. Known roles: {list(MODEL_REGISTRY)}")
    model = MODEL_REGISTRY[role]
    return nvidia.generate(prompt, model=model)
