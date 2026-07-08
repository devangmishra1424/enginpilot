"""Shared configuration constants for the agent layer (Playbook Section 7.3).

Single source of truth — import this everywhere a constant here is needed
rather than redefining it locally.
"""

# Confidence-gated answers guardrail (Section 7.3): if a retrieval's best
# (highest) similarity score is below this floor, treat the result as if
# nothing had been retrieved at all rather than answering from a weak match.
# 0.55 matches the team's architecture.md discussion value.
RETRIEVAL_CONFIDENCE_FLOOR = 0.55
