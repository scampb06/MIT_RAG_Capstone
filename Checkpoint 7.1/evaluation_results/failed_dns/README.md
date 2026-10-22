# Runs invalidated by a DNS outage (2026-10-20, about 17:08-17:28)

`getaddrinfo failed` / `EAI_AGAIN openrouter.ai`: the machine could not resolve the API host.
Kept for transparency only; none of these files is used in any report. Each run was repeated
after the network recovered.

- Golden suite, Haiku with selective reasoning: run 1 stopped after 1 of 17 records; run 2 made no progress.
- promptfoo, tuned targets: indirect (mini, Haiku) and benign returned `APIConnectionError` on every
  test; the red-team replay had 16 of 37 agent errors.
