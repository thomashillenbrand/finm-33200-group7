"""autochecker — verify claims against Compustat quarterly fundamentals.

Two-stage agentic flow:
  - stage 1 (screen): does the claim assert anything about a Compustat figure?
  - stage 2 (verify): compare the claim against the post-call quarterly panel,
    returning evidence (default) or a verdict (opt-in via --mode verdict).

Reads `VERIFIER_AGENT_MODEL` from the environment for the chat model id.
All artifacts produced by this package live under data/autochecker/.
"""
