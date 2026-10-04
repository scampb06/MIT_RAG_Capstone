# Checkpoint 6.1 Step 3: performance and cost of the 5.1 agent

Numbers for Step 3 of the worksheet, tabulated from the saved Checkpoint 5.1 evaluation files
(17-question golden subset). Nothing was rerun. Each configuration uses the result files listed
in `Checkpoint 5.1/evaluation_results/v1_vs_v2_refinement_report.md` (two runs each, one for
v0), so correctness and cost match that report.

## 1. Headline table

| Configuration | Correct / 17 | Cost / run (incl. judges) | Agent latency p50 / p90 / max | Agent LLM calls / query (mean, max) | Planned steps / query |
|---|---|---|---|---|---|
| v0 whole-article baseline | 7.0 | $2.99 | 3.4 / 3.8 / 3.9 s | 1.0, 1 | 0 |
| v1 gpt-5.4-mini | 11.5 | $0.43 | 9.0 / 12.8 / 14.2 s | 2.8, 4 | 1.03 |
| **v2 gpt-5.4-mini** (round 2, final) | 11.5 | $0.55 | 13.0 / 22.2 / 27.5 s | 4.2, 7 | 1.18 |
| v2 gpt-5.4 planner | 12.5 | $1.02 | 15.6 / 35.7 / 59.4 s | 4.0, 6 | 1.18 |
| v2 Haiku answer | 12.5 | $0.63 | 15.2 / 22.4 / 28.9 s | 4.4, 7 | 1.44 |
| v2 Haiku planner + answer | 13.5 | $0.82 | 20.9 / 37.0 / 40.5 s | 4.7, 7 | 1.82 |
| v2 Haiku both + medium reasoning | 14.0 | $1.08 | 45.9 / 80.6 / 92.8 s | 4.5, 7 | 1.50 |

- **Agent latency** is `agent_wall_seconds`: wall-clock time from question to answer, without
  the evaluation judges. It includes any rate-limit waits during the agent's own calls. The 5.1
  report's "median latency" is `total_latency_seconds`, which includes the judge calls (for
  example 15.3 s for v2 gpt-5.4-mini, against 13.0 s here).
- **Agent LLM calls** counts the clue step, planner turns (including verification retries),
  decompose and the answer; the judges aren't included. v2's minimum is 3 calls: clue step, one
  planner turn, answer.
- **Cost per run** includes the evaluation judges and the closed-book baseline call, because the
  files don't record the agent's cost separately for every configuration (section 3).

## 2. Where the time goes (medians per query)

| Configuration | Retrieval (local, no LLM) | Planner (all turns) | Answer | Agent total | Share of agent time spent in the planner |
|---|---|---|---|---|---|
| v0 | 0.3 s | n/a | 1.8 s | 3.4 s | n/a |
| v1 gpt-5.4-mini | 1.8 s | 2.0 s | 1.2 s | 9.0 s | about 22% |
| v2 gpt-5.4-mini | 2.4 s | 4.2 s | 1.5 s | 13.0 s | about 32% |
| v2 gpt-5.4 planner | 2.6 s | 8.0 s | 1.2 s | 15.6 s | about 51% |
| v2 Haiku planner + answer | 3.4 s | 11.1 s | 2.6 s | 20.9 s | about 53% |
| v2 Haiku + medium reasoning | 2.4 s | 27.3 s | 6.5 s | 45.9 s | about 60% |

Medians don't add up to the total, because they come from different questions. The remainder is
the clue step, decompose calls, rate-limit waits and local graph work.

**Rate-limit waits.** During evaluation these averaged 7–10 s per question (3.7 s with
reasoning, whose slower calls hit the limits less often). The figure counts judge calls too, so
it's an upper bound for the agent alone, but it shows that throughput at scale is limited by
the OpenRouter rate limits.

**One-off start-up.** The promptfoo debug log shows the provider took about 50 s to load the
141,126-chunk cache, the Chroma vector DB, the BM25 index and the NetworkX graph before the
first question. That is paid once per process.

## 3. Tokens and cost by role

| Configuration | Tokens / query (incl. judges) | Planner tokens / query | Context passed to answerer (chars, mean) | Planner + clue cost / run | Answer cost / run (incl. closed-book) | Remainder (judges, decompose) / run |
|---|---|---|---|---|---|---|
| v0 | 232,321 | 0 | 224,966 | n/a | n/a | n/a |
| v1 gpt-5.4-mini | 29,953 | 7,495 | 18,479 | not recorded | not recorded | not recorded |
| v2 gpt-5.4-mini | 37,136 | 11,284 | 20,757 | not recorded | not recorded | not recorded |
| v2 gpt-5.4 planner | 33,140 | 11,002 | 17,511 | $0.70 | not recorded | ~$0.32 (incl. answer) |
| v2 Haiku answer | 39,533 | 12,125 | 21,290 | $0.20 | $0.15 | $0.28 |
| v2 Haiku planner + answer | 45,223 | 15,994 | 23,098 | $0.36 | $0.16 | $0.30 |
| v2 Haiku + medium reasoning | 45,325 | 16,715 | 20,663 | $0.59 | $0.22 | $0.27 |

Observations:
- **Evaluation overhead is roughly constant at $0.27–0.30 per 17-question run**, about
  $0.017 per question. Subtracting it gives an **estimate** of the agent's own cost per query:
  about **$0.016** for v2 gpt-5.4-mini ($0.55 − $0.28 = $0.27 per run) and about **$0.03** for
  Haiku planner + answer ($0.82 − $0.30). So **about $16 vs $30 per 1,000 queries**.
- **promptfoo agrees.** It records the agent's own cost (the provider excludes the judges). The
  six indirect-injection tests on v2 gpt-5.4-mini cost $0.0051–0.0065 each. They were simple
  questions answered after the seed search (`seed, answer`, the 3-call minimum), so they sit
  below the $0.016 average.
- **The planner is the main cost.** It takes 69% of the agent's cost with Haiku in both roles
  ($0.36 of $0.52), and about 95% with the gpt-5.4 planner ($0.70 of roughly $0.74). The
  planner tokens per query (11–17k) are 2–3 times what the answerer reads. The planner
  receives up to `PLANNER_EVIDENCE_CHARS` = 16,000 characters of evidence plus its long system
  prompt on every turn, so its cost grows with every extra turn or retry.
- **v0 vs the agent.** v0 sent about 225k characters of whole articles to a single answer call
  (232k tokens per query). The agent sends about 18–23k characters of chosen passages, cutting
  cost per run from $2.99 to $0.43–0.55 and improving correctness from 7 to 11.5.

## 4. Workflow complexity

| Configuration | Answered after seed search only | Verification retries / query | Stop reasons (34 queries; v0: 17) |
|---|---|---|---|
| v0 | 100% (fixed pipeline) | 0 | fixed_pipeline 17 |
| v1 gpt-5.4-mini | 50% | 0 | planner_answer 26, step_budget 8 |
| v2 gpt-5.4-mini | 38% | 0.18 | planner_answer 25, step_budget 7, unverified_answer 1, parse_failure 1 |
| v2 gpt-5.4 planner | 35% | 0.06 | planner_answer 27, step_budget 7 |
| v2 Haiku answer | 26% | 0.15 | planner_answer 23, step_budget 9, repeat_action 2 |
| v2 Haiku planner + answer | 29% | 0.32 | step_budget 16, planner_answer 17, parse_failure 1 |
| v2 Haiku + medium reasoning | 29% | 0.32 | planner_answer 20, step_budget 12, parse_failure 2 |

- **`step_budget`** means the agent wanted to keep searching but hit `MAX_PLANNED_STEPS` = 3.
  This happened on 21–47% of queries, most often with the Haiku planner, which plans more. The
  budget caps cost and latency (no query exceeds 7 calls), at the price of answering on
  incomplete evidence.
- **`parse_failure`** (1–2 per 34 queries): the planner returned JSON that couldn't be parsed,
  so the agent fell back to answering.
- **The work is sequential.** Each planner turn chooses one action, waits for it, then plans
  again, so latency grows linearly with the number of steps. The clue step runs before the first
  planner turn on every v2 query, including questions the seed search already answers.

## 5. Bottlenecks and contributing design decisions (for the Step 3 boxes)

| Bottleneck | Evidence | Design decision behind it |
|---|---|---|
| Planner latency and cost | 32–60% of agent time; 69–95% of agent cost; 11–17k tokens per query | Every planner turn re-reads up to 16k characters of evidence plus the full prompt; the v2 rule-6 facts JSON (a verbatim quote per clue) makes outputs longer; verification retries add turns |
| Fixed overhead on easy questions | v2 never uses fewer than 3 calls; 38% of v2-mini queries were answered after the seed search alone | The clue step always runs, and the planner is always consulted before answering |
| Long latency tail | v2-mini p90 22 s vs p50 13 s; reasoning p90 81 s, max 93 s | Sequential one-action-per-turn loop; reasoning tokens on every planner turn |
| Reasoning cost | Medium reasoning: +0.5 correct for 2.2× latency and +32% cost | `--reasoning-effort` applies to every planner turn, not just hard questions |
| Answering on incomplete evidence | 21–47% of queries stop at `step_budget` | `MAX_PLANNED_STEPS = 3`, chosen to bound cost and latency |
| Throughput at scale | 7–10 s average rate-limit waits per question in evaluation | One OpenRouter key; 4–5 agent calls per query (plus judges during evaluation) |
| Start-up | About 50 s to load indexes per process | In-memory BM25 and graph rebuilt at load; 141k chunks |

## 6. Caveats

- **Sample size.** 17 questions × 2 runs per configuration (1 run for v0). Correctness varies
  between runs (the medium-reasoning runs scored 16 and 12).
- **Judges included.** Cost per run includes the judges and the closed-book call; the agent-only
  figures in section 3 are estimates.
- **The 5.1 report uses a different latency.** Its "median latency" (judges included) differs
  from the agent latency here.
