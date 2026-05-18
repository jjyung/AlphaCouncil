"""Deterministic scoring modules — one per master.

Each module exports:
  - a `*Score` dataclass with the master's numeric breakdown,
  - `score(state) -> *Score` reading shared_data:* from session state,
  - `format_block(score) -> str` returning a markdown block to embed in the
    master's LLM prompt.

Scoring rules return total scores even when many inputs are None; a missing
field maps to "criterion unverified" rather than zero. The LLM is told this
explicitly so it can weigh the qualitative analyst reports against gaps in
the deterministic signal.
"""
