# Initial evaluation: fixed pipeline (v0) vs initial agent (v1)

Worksheet Step 2. The fixed Checkpoint 3.1/4.1 pipeline is compared with the initial
agent on the 17-record suite, then on three multi-step tasks in detail.

| | Configuration | Result files |
|---|---|---|
| **v0** | Fixed pipeline: whole articles, BM25 + vector fusion, top 3 of 10, one answer call. Verified identical to the 4.1 baseline ([sanity report](v0_vs_4_1_baseline_sanity_report.md)) | `evaluation_agent_v0_20260927_122910.json` |
| **v1** | Agent: free seed search (4.1 chunks), then up to 3 planned steps choosing among `chunks` (with parent width), `decompose`, `graph`, `clarify` and `answer`; 4.1 prompts unchanged | run A `evaluation_agent_v1_20260927_123548.json`, run B `evaluation_agent_v1_20260927_130323.json` |

Every run uses the same 4.1 judges and metrics, with 3 correctness votes per record. v1
was run twice because the agent's own decisions vary between runs.

## 1. Results on the 17-record suite

| Metric | v0 | v1 run A | v1 run B |
|---|---|---|---|
| **Correctness, majority of 3 votes** | **7/17** | **11/17** | **12/17** |
| Binary correctness, first vote (4.1 method) | 5/17 | 10/17 | 12/17 |
| Mean graded correctness, all votes | 0.466 | 0.681 | 0.784 |
| Mean aspect coverage | 58.2% | 72.5% | 79.8% |
| Faithfulness (all claims grounded) | 10/17 | 17/17 | 13/17 |
| Mean graded groundedness | 80.6% | 100.0% | 95.9% |
| Mean citation support rate | 91.3% | 96.9% | 98.5% |
| Mean chunk attribution | 65.1% | 49.0% | 56.9% |
| Refusal judge: "hallucinated" | 7 | 3 | 5 |
| Strict source recall | 5.9% | 64.7% | 64.7% |
| Mean source recall | 23.5% | 73.5% | 76.5% |
| Mean evidence recall (golden quotes in context) | 36.1% | 60.8% | 58.8% |
| Mean article precision | 37.3% | 41.8% | 42.3% |
| Mean context size | 224,966 chars | 20,649 chars | 16,308 chars |
| **Model calls per query**, excl. judges | 1.00 | 2.88 | 2.71 |
| Mean planned retrieval steps | 0 | 1.18 | 0.88 |
| **Latency** p50 / p90, excl. rate-limit waits | 8.9 / 10.7 s | 11.0 / 14.6 s | 10.3 / 14.3 s |
| **Cost**, 17 records, excl. extra judge votes | $2.99 | $0.46 | $0.39 |

**Per-record consistency** (majority passes / runs):

| Record | v0 | v1 | Record | v0 | v1 |
|---|---|---|---|---|---|
| Q006 | 0/1 | 2/2 | Q014 | 0/1 | 2/2 |
| Q045 | 1/1 | 1/2 | G06 | 1/1 | 2/2 |
| Q049 | 1/1 | **0/2** | G07 | 1/1 | 2/2 |
| Q019 | 0/1 | 2/2 | G10 | 0/1 | 0/2 |
| Q072 | 0/1 | 1/2 | G15 | 1/1 | 2/2 |
| Q080 | 1/1 | 2/2 | G16 | 0/1 | 0/2 |
| Q003 | 0/1 | 2/2 | G08 | 0/1 | 1/2 |
| Q005 | 0/1 | 2/2 | G13 | 0/1 | 0/2 |
| Q009 | 1/1 | 2/2 | | | |

v1 gains five records in both runs: Q006, Q019, Q003, Q005 and Q014. It loses Q049 in
both runs and Q045 in one.

## 2. Retrieval behaviour

- **The agent mostly widened chunk searches.** Across both runs its planned steps were
  `chunks` with `parent: section` 22 times, `lead_section` 4, `article` 4 and `none` 5.
  **It never chose `graph` or `decompose`.**
- **About half the queries were answered from the free seed alone** (8 and 9 of 17). v1
  therefore averages under one planned step.
- **Stopping:** the planner chose to answer on 12 and 14 records; the 3-step budget ended
  the other 5 and 3.
- **Retrieved vs kept:** 79% / 77% source recall over everything retrieved at any step,
  against 74% / 77% in the final context. Fusion discarded little.

## 3. Three multi-step tasks

Each needs more than one retrieval step, for a different reason.

### Q049 — "Who won Best Actor at the 95th ceremony and what was notable about the whole nominee field that year?"

| | v0 | v1 (run A) |
|---|---|---|
| Verdict | pass (P P P), graded 1.00 | fail (F F F), graded 0.00 |
| Path | one retrieval: `95th_Academy_Awards.html` whole (177k chars of context) | seed → `chunks` section → `chunks` section → `chunks` lead_section → budget spent |
| Model calls / latency / cost | 1 / 9.0 s / $0.141 | 4 / 13.5 s / $0.048 |
| Answer | Brendan Fraser, *The Whale*; all five nominees first-time nominees | "the provided documents do not say who won Best Actor" |

The winners table is split across chunks, and the chunk naming Fraser does not repeat
the "Best Actor" heading. No search ranks it, and a wider parent around the chunks v1
*did* find stays in the wrong section. v0 succeeds only because it reads the whole
article. v1's planner diagnosed the gap correctly every time ("does not yet state the
95th ceremony's Best Actor winner") but had no tool that could close it. v1 answered
honestly rather than from memory. In one earlier exploratory v1 run it named Fraser
without his name in the context, and the refusal judge flagged that as hallucinated.

### Q009 — "The author who won the Nobel Prize in Literature the same year a magnitude-9 earthquake struck Alaska initially refused the honor — who was he, and why did he decline?"

| | v0 | v1 (run A) |
|---|---|---|
| Verdict | pass (F P P), graded 0.83 | pass (P P P), graded 1.00 |
| Path | one retrieval: Nobel Prize, 1964 Literature Prize, John Muir | seed only; planner answered at its first call |
| Evidence recall | 0.75: the earthquake article was never retrieved | 0.75: same |
| Model calls / latency / cost | 1 / 7.5 s / $0.131 | 2 / 10.5 s / $0.014 |

Both answers are correct: Sartre, who refused official honours and objected to the
prize's political bias. But **neither is grounded on the bridge**. The year 1964 comes
from the model's memory of the Alaska earthquake, because `1964_Alaska_earthquake.html`
is never in the context. v1's planner accepted the evidence without checking the
earthquake clue, even though its prompt says to judge "only from the evidence text".
This is the weakness v2 targets with fact verification.

### G13 — "What was the former name of the university where Barack Obama earned his law degree?"

| | v0 | v1 (run A) |
|---|---|---|
| Verdict | fail (F F F), graded 0.00 | fail (F F F), graded 0.50 |
| Path | one retrieval: Barack Obama, presidents by education, Oprah Winfrey | seed → `chunks "Harvard Law School former name"` → answer |
| Source recall | 0.50 | 1.00 (`Harvard_University.html` found) |
| Model calls / latency / cost | 1 / 9.2 s / $0.256 | 3 / 8.8 s / $0.022 |

v1 does the hop that v0 cannot: from "Harvard Law School" in Obama's article to Harvard
University's article. It built the query from the evidence, not from memory, as rule 1
requires. It still fails, for two reasons:
- The planner reframed "the university" as "Harvard Law School", so it looked for the law
  school's former name.
- The retrieved Harvard passages did not include the lead infobox ("Former names: Harvard
  College"), so evidence recall stayed at 0.33.

## 4. Strengths and weaknesses of the initial agent

**Strengths:**
- **Better answers at a fraction of the cost.** Correctness rose from 7 to 11–12 of 17,
  and graded correctness from 0.47 to 0.68–0.78. Cost per query fell 7×, from $0.176 to
  $0.023–0.027, because it reads about 18k characters of targeted passages instead of
  225k of whole articles.
- **Retrieval improved sharply.** Strict source recall rose from 6% to 65%, and evidence
  recall from 36% to about 60%.
- **More grounded answers.** Faithfulness rose from 10 to 13–17 of 17, and "hallucinated"
  refusal outcomes fell from 7 to 3–5.
- **Adaptive effort.** Simple questions stop after the free seed; harder ones get one to
  three targeted follow-ups, with the gap stated in the planner's log.

**Weaknesses:**
- **It cannot read "further into" an article it has found.** Q049 failed in both runs;
  the planner saw the gap and had no tool to close it.
- **It accepts evidence that doesn't cover every clue.** Q009 passed on remembered bridge
  facts.
- **Routing is narrow.** `graph` and `decompose` were never chosen. G08 ("which president
  served in both centuries"), which only the graph solved in 4.1, stays unsolved.
- **It reframes questions.** G13's "the university" became "the law school".
- **Answer-side reasoning errors pass straight through.** G16 had the right dates and the
  wrong yes/no.
- **Cost: more calls and slightly more latency.** 2.7–2.9 model calls instead of 1, and
  median latency up by about 1.5–2 s.
- **Run-to-run variation.** Graded correctness differed by 0.10 between two identical v1
  runs, so single-run differences of that size are not evidence of improvement.
