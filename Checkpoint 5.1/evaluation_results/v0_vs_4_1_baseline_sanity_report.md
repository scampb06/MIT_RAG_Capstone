# v0 sanity check against the Checkpoint 4.1 baseline

**Question.** Does `--agent-version v0` in the 5.1 script reproduce the fixed
Checkpoint 3.1/4.1 pipeline (`--retriever baseline` in the 4.1 script), so that it is a
valid baseline for the agent comparison?

**Answer: yes.**
- Retrieval is identical on all 17 records.
- Every answer-side difference is within judge noise: the majority of three correctness
  votes matches the 4.1 verdict on 17/17 records.

| | File |
|---|---|
| 4.1 baseline | `Checkpoint 4.1/evaluation_results/evaluation_baseline_20260921_161030.json` |
| v0 (retrieval only) | `retrieval_agent_v0_check.json` |
| v0 (full, `--judge-repeats 3`) | `evaluation_agent_v0_20260927_122910.json` |

Suite: `mini-4.1-test-suite.json` (17 records). Model `openai/gpt-5.4-mini`, temperature 0.2.

## 1. Retrieval: deterministic, so it must match exactly

| Field | Identical records |
|---|---|
| `retrieved_sources` (same articles, same order) | 17/17 |
| `context_chars` | 17/17 |
| `source_recall_at_k`, `source_recall_strict` | 17/17 |
| `article_precision`, `unique_articles_retrieved` | 17/17 |
| `evidence_recall` | 17/17 |

The free retrieval-only run and the full run both matched.

## 2. Answers and judges: stochastic, so they should agree within noise

| Metric | 4.1 baseline | v0 |
|---|---|---|
| Binary correctness, single judge | 7/17 | 5/17 |
| **Binary correctness, majority of 3 votes** | — | **7/17** |
| Mean graded correctness (first vote) | 0.471 | 0.456 |
| Mean aspect coverage | 55.1% | 58.2% |
| Faithfulness (all claims grounded) | 10/17 | 10/17 |
| Mean graded groundedness | 78.9% | 80.6% |
| Mean citation support rate | 88.2% | 91.3% |
| Mean chunk attribution | 59.9% | 65.1% |
| Mean context size | 224,966 chars | 224,966 chars |
| Model calls per query, excl. judges | 1 | 1 |
| Mean latency, excl. throttle | 10.0 s | 9.4 s |
| Estimated cost, 17 records | $3.00 | $2.99 (+ $1.49 for the two extra judge votes, reported separately) |

**Per-record verdicts.**
- The first vote differs from 4.1 on two records, Q080 and Q009. On both, the first vote
  was F and the next two were P, and the majority equals the 4.1 verdict.
- Q003's graded score was 0.00 in 4.1 and 0.50 on all three v0 votes. It fails either way.
- Every other record got the same verdict and the same graded score.

| Record | 4.1 | v0 votes | v0 majority |
|---|---|---|---|
| Q080 | pass | F P P | pass |
| Q009 | pass | F P P | pass |
| all other 15 | — | unanimous, equal to 4.1 | equal to 4.1 |

## 3. What this means for the comparison

- v0 is a faithful re-implementation of the 3.1/4.1 baseline. It runs through the same 5.1
  harness as the agents, so v0/v1/v2 differences come from the pipelines, not the tooling.
- **A single correctness verdict flips on about 1 or 2 records in 17 between runs**,
  judging the same answer and context. Differences of that size between versions are noise.
  All 5.1 comparisons therefore use `--judge-repeats 3` and report the majority vote and
  the mean graded score next to the single-judge 4.1 figure.
