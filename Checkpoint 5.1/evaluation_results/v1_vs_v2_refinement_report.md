# Refinement: initial agent (v1) vs refined agent (v2)

This report covers worksheet Steps 3 (system refinement) and 4 (impact of refinement), with
evidence notes for Step 5 (reflection). The individual changes, each tied to the failure
that motivated it, are listed in the design doc's
[v2 change log](../capstone_checkpoint_5_1_agent_design.md#14-v2-change-log). The
v0/v1 comparison is in the [initial evaluation report](v0_vs_v1_initial_evaluation_report.md).

**Method.**
- The same 17-record suite, 4.1 judges and metrics, with 3 correctness votes per record.
- v1 and the final v2 were each run twice, and figures are averaged over both runs.
  A single run moves by about 0.1 in graded correctness, so one-run differences are not
  evidence.

| | Result files |
|---|---|
| v0 | `evaluation_agent_v0_20260927_122910.json` |
| v1 | `evaluation_agent_v1_20260927_123548.json`, `evaluation_agent_v1_20260927_130323.json` |
| v2 round 1, final (tag `v2-round1`) | `evaluation_agent_v2_20260927_132135.json`, `evaluation_agent_v2_20260927_133023.json` |
| v2 round 1, intermediate | `…_124407.json` (after change-log #11–15), `…_125444.json` and `…_131136.json` (after #16) |
| v2 round 2, final | `evaluation_agent_v2_20260928_203048.json`, `evaluation_agent_v2_20260928_204052.json` |
| v2 round 2, before fixes #24–26 | `evaluation_agent_v2_20260928_200542.json`, `…_201556.json` |
| v2 round 2 ablations (6 records each) | `evaluation_agent_v2-without-{tables,sections,clues,facets}_20260928_*.json` |
| v2 round 3, gpt-5.4 planner | `evaluation_agent_v2-planner-gpt-5.4_20260928_213653.json`, `…_214812.json` |
| Model tests: Haiku planner + answer | `evaluation_agent_v2-planner-claude-haiku-4.5-answer-claude-haiku-4.5_20260929_071105.json`, `…_072313.json` |
| Model tests: Haiku planner + answer, medium reasoning | `evaluation_agent_v2-planner-claude-haiku-4.5-answer-claude-haiku-4.5-reasoning-medium_20260929_074024.json`, `…_075935.json` |
| Model tests: Haiku answer only | `evaluation_agent_v2-answer-claude-haiku-4.5_20260929_081945.json`, `…_082956.json` |
| Model tests: Haiku answer only, raw tables (4 records) | `evaluation_agent_v2-without-tables-answer-claude-haiku-4.5_20260929_095544.json`, `…_095835.json` |

Sections 1–4 describe **round 1**. **Round 2** (four further refinements, each switchable
with `--disable`) is in [section 5](#5-round-2-tables-sections-frozen-clues-facets).
**Round 3** (a stronger planner model) is in [section 6](#6-round-3-a-stronger-planner-model), and
the **model tests** (Claude Haiku 4.5, reasoning effort) are in [section 7](#7-model-tests-claude-haiku-45-and-reasoning-effort).
**Future work** is in [section 8](#8-future-work).

## 1. What was refined (Step 3)

The v2 changes fall into four groups. Numbers refer to the change log.

| Group | Changes | Why |
|---|---|---|
| **Workflow: new tools** | `read_section` (#6, #11), `title_search`, and the `parent: article` fallback to `lead_section` (#7) | v1's planner often diagnosed the gap correctly but had no tool to close it. On Q049 the winners table cannot be reached by search, and on G13 a long article silently lost its infobox. |
| **Prompts: planner** | Rule 6: list the question's clues, cover each with a quoted fact (#1, #9). Graph routing for "described, not named" questions (#13). Section labels and new-passage counts in the evidence view (#6, #12) | v1 answered Q009 on a remembered bridge fact, and never chose `graph` or `decompose` in 35 planned steps. |
| **Verification: code** | Quotes checked against the cited file, allowing for markup, elisions and short table cells (#4, #12); an uncovered clue sends the answer back once (#1, #9) | Prompt rules alone did not stop answers built on unretrieved facts. |
| **Prompts: answer and decompose** | Decompose limited to names in the question (#2). Reason-then-answer; the fact behind each clue; YYYY-MM-DD date comparison (#3, #10, #14). Conclusions restate only cited facts; answer directly; cite every sentence (#16, #17) | G16 had the right dates and the wrong yes/no. Two of these changes (#16, #17) fix faithfulness regressions that #3 itself caused. |

Two fixes went into the shared harness and apply to all versions:
- a fusion coverage bug (#8);
- `--judge-repeats` (#15), added after identical contexts drew opposite verdicts.

## 2. How v2 got there

| v2 run | After changes | Majority pass | Graded | Faithful | What it showed |
|---|---|---|---|---|---|
| 26 Sep, 17 records, 1 vote | up to #10 | 9/17 (single judge) | 0.618 | 12/17 | Lost to v1 (11/17). Investigation found bugs #11–13, a reasoning failure (#14), and judge noise (#15). |
| 27 Sep `124407` | #11–15 | 11/17 | 0.809 | 14/17 | Graded correctness up, but faithfulness down: uncited summary sentences (#16). |
| `125444`, `131136` | #16 | 12/17, 13/17 | 0.716, 0.779 | 12/17, 14/17 | Uncited meta-sentences penalised on G07 (#17). |
| **`132135`, `133023` (final)** | #17 | **13/17, 10/17** | **0.828, 0.725** | **16/17, 13/17** | the comparison below |

Tuning stopped here. Further prompt changes would have been fitted to individual test
questions (G08's century arithmetic, G13's law school vs university), which would inflate
the score without improving the system.

## 3. Impact (Step 4)

### Suite averages (mean per run)

| Metric | v0 fixed | v1 initial | **v2 refined** | v2 − v1 |
|---|---|---|---|---|
| Correctness, majority of 3 votes | 7.0/17 | 11.5/17 | **11.5/17** | 0 |
| Mean graded correctness | 0.466 | 0.733 | **0.777** | +0.044 |
| Mean aspect coverage | 58.2% | 76.2% | **84.2%** | +8.0 pts |
| Faithfulness (all claims grounded) | 10.0/17 | 15.0/17 | 14.5/17 | −0.5 |
| Mean graded groundedness | 80.6% | 98.0% | 97.6% | ≈ |
| Mean citation support | 91.3% | 97.7% | 98.1% | ≈ |
| Mean chunk attribution | 65.1% | 53.0% | 54.8% | +1.8 pts |
| Refusal judge "hallucinated" | 7.0 | 4.0 | 5.5 | +1.5 |
| Strict source recall | 5.9% | 64.7% | 61.8% | −2.9 pts |
| Source recall@3 articles | 23.5% | 50.0% | **57.4%** | +7.4 pts |
| Mean evidence recall | 36.1% | 59.8% | 59.6% | ≈ |
| Mean context size | 224,966 | 18,479 | 17,996 chars | ≈ |
| Model calls per query, excl. judges | 1.00 | 2.79 | 3.18 | +0.39 |
| Planned retrieval steps per query | 0 | 1.03 | 1.29 | +0.26 |
| Median latency, excl. rate-limit waits | 8.9 s | 10.6 s | 11.6 s | +1.0 s |
| Cost per 17-record run | $2.99 | $0.43 | $0.50 | +17% |


### Where v2 is noticeably better, consistent across both runs

| Record | v1 | v2 | What changed |
|---|---|---|---|
| **Q049** 95th Best Actor | 0/2, graded 0.25, evidence 0.17 | **2/2**, graded 0.88, evidence 0.67 | v1 widened chunk searches three times and never reached the winners table. v2 made one `read_section` call on "Winners and nominees", and both facts were quote-verified. It is also cheaper: 3 calls and about $0.024, against v1's 4 calls and $0.048. |
| **G16** Charles III born before his mother's reign? | 0/2, graded 0.17 | **2/2**, graded 1.00 | Same dates in both versions (1948 and 1952). The date-comparison instruction fixed the reasoning, not the retrieval. |
| **G13** university's former name | 0/2, evidence 0.33 | 1/2, graded 0.79, **evidence 1.00** | v2 retrieves Harvard University's lead and infobox ("Former names: Harvard College"), and both v2 answers say Harvard College. One run's verdict was F F P despite that. |
| **Q045** Brokeback / La La Land | 1/2 | **2/2**, graded 0.96 | Fuller comparison: aspect coverage up. |
| **Tool use** | `chunks` only (35 of 35 steps) | `chunks` 23, `read_section` 15, `title_search` 3, `decompose` 2, `graph` 1 | v2 chooses the tool to fit the gap. |

### Where v2 is worse or no better

| Record | v1 | v2 | Why |
|---|---|---|---|
| Q014 1992 IOC vote | 2/2 | 0/2 | The answer model misread a complex voting table, once after `read_section` returned the whole table and once from the seed alone. The context is correct (evidence recall 1.00); the reading is not. |
| G07 another Yale president | 2/2 | 0/2 | v2's answers are correct and grounded but name two presidents ("George H. W. Bush … and Gerald Ford …"), and the judge grades that partial. v1 named one and passed. This is a judge and golden-record sensitivity, not an agent error. |
| Q009 1964 Nobel / Alaska | 2/2 | 1/2 | In one run the planner lumped the bridge into a single clue, answered on the Nobel page alone, and passed as v1 did, on a remembered year. In the other it retrieved `1964_Alaska_earthquake.html` (`title_search`, recall 1.00), and the answer grounded the bridge ("the 1964 Alaska earthquake, which occurred on 1964-03-27 … M<sub>w</sub> 9.2–9.3", cited). But it dropped Sartre's political reason, and it failed on aspect coverage. **This is the only run of any version that answered Q009 with the bridge grounded.** |
| Q080 | 2/2 | 1/2 | Three wider chunk reads spent the budget; evidence recall fell from 0.75 to 0.50. |
| G08, G10 | 1/2, 0/2 | 1/2, 0/2 | Not reliably solved. G08 passed once with correct date reasoning ("Bill Clinton served from 1993-01-20 to 2001-01-20, which spans both …") and failed once by confusing the 1901 century boundary (Theodore Roosevelt). G10 needs "English director" ∩ "Oscar winner", and `graph` was chosen only once. |

### Trade-offs

- **Cost:** 0.39 more model calls per query (verification retries, more planned steps),
  about 1 s more median latency and 17% more cost. That is still 6× cheaper than the
  fixed whole-article pipeline.
- **Commitment vs refusal.** v1 declines when the evidence falls short ("the documents do
  not say…"). v2's quote verification pushes the planner to commit to *some* quoted fact.
  That turns honest refusals into grounded but occasionally wrong answers: "hallucinated"
  refusal outcomes rose from 4.0 to 5.5 per run, and faithful answers fell by 0.5 per run.
- **More moving parts, more failure points.** Each change fixed one failure and opened
  another path:
  - reason-then-answer produced uncited conclusions (#16, #17);
  - verification turned hedged gaps into wasted searches (#9);
  - a single-cell quote rule met a 4-character minimum in the verifier (#12).

## 4. Evidence notes for the reflection (Step 5)

- **When the agent adds value:**
  - The question describes an entity without naming it (G13).
  - The answer sits somewhere search cannot rank (Q049's table chunk).
  - The context would otherwise be huge. v0 sends about 225k characters per query and
    still misses the second article on 16 of 17 records (strict recall 6%).
  - The agent's gains are large and robust: 7 → 11.5 of 17 correct, one sixth of the cost.
- **When a simpler pipeline is better:**
  - Single-article questions whose whole article is the answer. v0 passes Q049 by reading
    all 177k characters of the ceremony article; v1 fails it.
  - About half of all queries were answered from the free seed, and there the loop only
    adds a planner call.
- **Autonomy is only as good as the tools and checks.** v1's planner often saw exactly what
  was missing but could not act on it. v2's biggest wins came from giving it the right tool
  (`read_section`), not from better prompting.
- **Deterministic checks catch what prompts cannot, but only syntactically.** Quote
  verification proved every quote real (66 of 67 facts verified across the final runs).
  It could not stop a real quote being used for the wrong claim, such as the law school's
  old name given for the university's.
- **Evaluation noise is the same size as the effects.**
  - The same answer drew opposite verdicts, and single runs moved by about 0.1 graded
    correctness.
  - Majority votes over repeated runs were necessary to tell real gains (Q049, G16) from
    luck.
  - The judges also reward styles as well as facts: one name vs two on G07, uncited
    summary sentences.
- **Parametric leakage persists without verification.** v0 and v1 pass Q009 using a year
  from memory, and the correctness judge accepts it. Only evidence recall and the
  refusal and claim judges expose it.


## 5. Round 2: tables, sections, frozen clues, facets

Round 2 targeted the four root causes left after round 1: tables losing their labels,
section parents too narrow to reach a subsection's table, an unstable clue list, and
category search unable to combine properties. Each refinement is a v2 feature that
`--disable` switches off, so its effect can be measured on its own. The changes are #18–28
in the [change log](../capstone_checkpoint_5_1_agent_design.md#14-v2-change-log).

### 5.1 What changed (Step 3)

| Feature | Change | Targets |
|---|---|---|
| `tables` | The 2.1 module's new `render_wikitables()` rewrites every wikitable before extraction. Layout cells become "Heading: item; item"; data rows become "Label: value; …" records. v2 uses a separate table-rendered index of 141,126 chunks; 87% reuse the original embeddings. | Q049 (the Fraser chunk had no "Best Actor" label), Q014 (unreadable two-row header) |
| `sections` | `section` and `lead_section` parents span the whole Header 2 section, subsections included, as a 6-chunk window around the hit | Q049 (the 4.1 section parent never crossed into "Awards") |
| `clues` | A question-only clue step lists the values the question gives only indirectly, then the other clues. The list is frozen for the run, is enforced by the coverage check, and is passed to the answer prompt as a checklist. | Q009 (bridge clue bundled, then covered by the Nobel fact alone) |
| `facets` | `graph` takes up to 3 facets, each matched to categories separately and intersected at the strictest level that yields a result. An automatic facet search runs when the clue step returns 2 or more facets. | G10 (English directors ∩ Oscar winners), G08 |

Three bugs found in the first round-2 runs were fixed before the final runs: the frozen
clues being bypassed (#25), args-only replies becoming parse failures (#24), and
`clarify` being used for multi-answer questions (#26).

Two design decisions came from measurement, not assumption:
- **A dedicated clue step instead of the planner's own list.** Inside its reply, the planner
  never split Q009's bridge and never proposed facets.
- **Asking for "indirect values" instead of "split nested clues".** Told to split, the
  model bundled Q009's bridge in 11 of 12 calls. Asked which values are given only
  indirectly, it named the earthquake year in 3 of 3. Temperature played no part: OpenRouter
  ignores it for these models (see section 6).

### 5.2 Results (Step 4), mean of two runs each

| Metric | v1 | v2 round 1 | **v2 round 2** |
|---|---|---|---|
| Correctness, majority of 3 votes | 11.5/17 | 11.5/17 | **11.5/17** |
| Mean graded correctness | 0.733 | 0.777 | 0.765 |
| Mean aspect coverage | 76.2% | 84.2% | 80.6% |
| Faithfulness (all claims grounded) | 15.0/17 | 14.5/17 | 13.0/17 |
| Refusal judge "hallucinated" | 4.0 | 5.5 | **4.5** |
| Strict source recall | 64.7% | 61.8% | **67.6%** |
| Mean evidence recall | 59.8% | 59.6% | 53.9% |
| Mean evidence recall, excluding Q014 (see note) | 57.3% | 57.0% | 57.3% |
| Model calls per query, excl. judges | 2.79 | 3.18 | 4.18 |
| Median latency, excl. rate-limit waits | 10.6 s | 11.6 s | 15.3 s |
| Cost per 17-record run | $0.43 | $0.50 | $0.55 |

**Note on Q014.** Its golden quotes are copied from the original table markup
("Falun | Sweden | 10 | 11 | …"). The table-rendered index writes the same row as
"City: Falun; Country: Sweden; Round 1: 10; …", so Q014's evidence recall is 0 in round 2
even with the table in context. Excluding Q014, evidence recall is unchanged. The metric
itself was not changed, so every version is measured the same way.

**Per record, majority passes over two runs:**

| Record | v1 | Round 1 | Round 2 | Note |
|---|---|---|---|---|
| **Q009** | 2/2 | 1/2 | **2/2** | **Evidence recall 1.00: the earthquake article is retrieved and cited in both runs.** The first grounded bridge by any version. v0 and v1 passed on a remembered year. |
| Q080 | 2/2 | 1/2 | 2/2 | evidence 0.50 → 0.75 |
| G07 | 2/2 | 0/2 | 1/2 | the clarify misuse was fixed (#26) |
| Q049, G16, Q045 | 0/2, 0/2, 1/2 | 2/2 each | 2/2 each | round-1 wins retained |
| Q019 | 2/2 | 2/2 | 0/2 | Both round-2 answers are correct and faithful, and one covers all three aspects, against round 1's one; graded 0.5–0.75, so they fail the binary cut. Every ablation run passes it, so this is judge variation. |
| Q006 | 2/2 | 2/2 | 1/2 | graded 0.71; also flips across ablations |
| Q014 | 2/2 | 0/2 | 0/2 | still misread; see 5.4 |
| G10 | 0/2 | 0/2 | 0/2 | the clue step rarely produces usable facets; see 5.4 |
| G08, G13 | 1/2, 0/2 | 1/2, 1/2 | 1/2, 1/2 | unchanged |

### 5.3 Attribution: `--disable` one feature at a time

Six records, one run per ablation, 3 judge votes each:

| Record | Round 2, all on (2 runs) | without `clues` | without `facets` | without `sections` | without `tables` |
|---|---|---|---|---|---|
| Q009 correct / **evidence** | 2/2, **1.00** | 1/1, **0.75** | 1/1, 1.00 | 1/1, 1.00 | 1/1, 0.75 |
| Q080 | 2/2, 0.75 | 1/1, 0.50 | 1/1, 0.50 | 1/1, 1.00 | 1/1, 0.50 |
| Q019 | 0/2, 0.88 | 1/1, 1.00 | 1/1, 1.00 | 1/1, 1.00 | 1/1, 1.00 |
| Q006 | 1/2, 1.00 | 1/1, 1.00 | 0/1, 1.00 | 1/1, 1.00 | 1/1, 1.00 |
| G07 | 1/2, 0.33 | 0/1, 0.33 | 0/1, 0.33 | 1/1, 0.33 | 0/1, 0.33 |
| G13 | 1/2, 0.67 | 1/1, 1.00 | 1/1, 1.00 | 1/1, 1.00 | 0/1, 1.00 |

- **`clues` → Q009's grounding.** Without it the planner answers from the seed, and
  evidence recall drops to 0.75. With it, the earthquake year is clue 1 and gets
  searched. This is the one effect that holds across every run.
- **Q019, Q006, G07 and G13 flip in both directions across single runs.** These are
  judge and planner variation, not feature effects. With one run per ablation, nothing
  smaller than Q009's effect can be attributed.
- **With the gpt-5.4-mini answer model, `tables`, `sections` and `facets` show no reliable
  record-level effect on this suite.** (Correction: with a stronger answer model, `tables`
  decides Q014; see [section 7.4](#74-does-table-rendering-matter-with-a-stronger-answer-model).)
  - The renderer did label the Fraser chunk, but plain search still ranks it below the
    "Academy Award for Best Actor" articles. Q049 is solved by `read_section` either way.
  - Whole-section parents reach the table when a hit lands in the right section, which
    the planner rarely needed once `read_section` existed.

### 5.4 Pre-set success criteria

| Criterion (fixed before running) | Result |
|---|---|
| Q014 passes in at least 1 of 2 runs | **not met** (0/2) |
| Q009 has the earthquake page in context in at least 1 of 2 runs | **met** (2/2, evidence recall 1.00) |
| G10 passes in at least 1 of 2 runs | **not met** (0/2) |
| Round 2 is no more than one record below round 1's average (11.5) | **met** (11.5) |
| Round-1 wins still pass (Q049, G16, Q045) | **met** |
| Cost no more than +25% over round 1 | **met** (+12%) |

**Why the two misses remain:**
- **Q014.** The rendered table is correct and in context in both runs. The answer model
  still names the wrong cities or the wrong first-round elimination. Rendering fixed the
  representation but not the reading. The next step would be answer-side, for example
  asking the model to restate the relevant rows before answering. (Section 7 found the
  answer-side fix: Claude Haiku 4.5 as the answer model reads the rendered table
  correctly, and section 7.4 shows it needs the rendering to do so.)
- **G10.** The facet tool finds Mendes and Minghella when given "English film directors"
  and "Best Picture Academy Award winners". But gpt-5.4-mini's clue step rarely proposes
  facets for this question, and when it does, they mix entity types (directors and films).
  The planner never chose facets itself. The bottleneck is the model's judgement, not
  retrieval.

### 5.5 Trade-offs and reflection notes

- **The refinements cost more than they returned on this suite.** Model calls rose by a
  third (3.18 → 4.18 per query) and median latency by about 4 s. Correctness stayed at
  11.5 and graded correctness moved within noise.
- **The one clear gain is the grounded bridge on Q009, and it matters.** It is the only
  configuration that answers Q009 from retrieved evidence rather than memory. Correctness
  can't show that, because the judge passes the remembered answer too. Only evidence
  recall and the claim and refusal judges reveal it.
- **Deterministic steps beat prompt instructions only when the model can do the
  sub-task.** Freezing clues works because the clue step, framed as "indirect values",
  identifies the bridge reliably. Facets fail because the model cannot reliably name the
  right categories, however the tool is built.
- **Framing matters more than wording.** "Split nested clues", even with a near-identical
  example, failed 6 of 6 times; "which values are given only indirectly" succeeded 3 of 3.
- **Better representation is not better reading, on its own.** With gpt-5.4-mini,
  Q014's table was clean in context and the answer was still wrong. Section 7.4 shows the
  other half: a stronger reader fails on the raw table and succeeds on the rendered one.
  Representation and reading are both needed.
- **Measurement drifts with representation.** Rendering tables invalidated Q014's golden
  quotes for evidence recall. Changing the corpus's text changes what verbatim metrics can
  see.
- **Noise dominates at this sample size.** With 17 records and two runs, single-record
  flips (Q019, Q006) are indistinguishable from real regressions. Attribution needed
  repeated runs and a pre-registered pass/fail list to stay honest.

## 6. Round 3: a stronger planner model

**Question.** After round 2, most remaining failures were judgement failures of the planner
and the clue step:
- facets never chosen or badly named (G10, G08);
- "the university" reframed as "Harvard Law School" (G13);
- answering while listing open gaps, bare `args` replies, clarifying multi-answer
  questions.

Would a stronger model in those two roles improve quality?

**Test.** `--planner-model openai/gpt-5.4` for the planner and the clue step only. Decompose,
the answer model and all judges stay on gpt-5.4-mini, so the measuring instrument is
unchanged. All round-2 features are on, so the comparison with the round-2 runs differs
only in the planner model. Two full runs, 3 judge votes each.

### 6.1 Results, mean of two runs each

| Metric | v1 | v2, gpt-5.4-mini planner | **v2, gpt-5.4 planner** | Change |
|---|---|---|---|---|
| Correctness, majority of 3 votes | 11.5/17 | 11.5/17 | **12.5/17** | **+1.0** |
| Mean graded correctness | 0.733 | 0.765 | 0.779 | +0.014 |
| Mean aspect coverage | 76.2% | 80.6% | **86.4%** | **+5.8 pts** |
| Faithfulness (all claims grounded) | 15.0/17 | 13.0/17 | 14.0/17 | +1.0 |
| Strict source recall | 64.7% | 67.6% | **70.6%** | +2.9 pts |
| Mean source recall | 75.0% | 76.5% | **79.4%** | +2.9 pts |
| Chunk precision | 50.9% | 49.6% | **53.6%** | +4.0 pts |
| Article precision | 42.1% | 38.5% | 41.1% | +2.6 pts |
| Evidence recall, excluding Q014 | 57.3% | 57.3% | **62.8%** | **+5.5 pts** |
| Chunk attribution | 53.0% | 51.1% | **58.9%** | **+7.8 pts** |
| Citation precision | 91.2% | 85.5% | 80.9% | −4.6 pts |
| Citation support rate | 97.7% | 96.3% | 92.9% | −3.4 pts |
| Refusal judge "hallucinated" | 4.0 | 4.5 | 6.5 | +2.0 (worse) |
| Model calls per query, excl. judges | 2.79 | 4.18 | 4.03 | −0.15 |
| Median latency, excl. rate-limit waits | 10.6 s | 15.3 s | 19.9 s | +4.5 s |
| Cost per 17-record run | $0.43 | $0.55 | **$1.02** (planner $0.70) | ×1.8 |

**Per record, majority passes over two runs (gpt-5.4-mini planner → gpt-5.4 planner):**
- **Gains:**
  - **G13: 1/2 → 2/2**, with evidence recall 1.00 in both runs, the first configuration
    to solve it consistently.
  - Q019: 0/2 → 2/2.
  - Q006: 1/2 → 2/2.
- **Losses:** Q049 and Q080 (2/2 → 1/2).
- **Unchanged failures:**
  - **Q014: 0/2.** The misreading happens in the answer model, which did not change.
  - **G10: 0/2.** The stronger planner tried `graph` in one of its two runs but still found no working
    facets.

### 6.2 Reading the result

- **Retrieval improved most clearly.** Recall, chunk precision, evidence recall and chunk
  attribution all rose, and they moved together across both runs. Attribution counts
  claims that come from retrieval rather than from the model's own knowledge. A stronger
  planner chooses better queries and actions, so more of each answer rests on retrieved
  text.
- **The correctness gain (+1 record per run) is at the edge of the noise.** The two
  gpt-5.4 runs differ by one record and by 0.108 in graded correctness.
- **The citation-precision drop is concentrated in two unsolved records.** The number of
  distinct files cited per answer is unchanged (1.94 against 2.03), and so is context
  size (11.7 units).
  - **G10 (−0.50):** the gpt-5.4 plans pulled in film articles, and the answers cited
    films that do not meet the criteria (*The Lord of the Rings*, *Gone with the Wind*,
    *Pride & Prejudice*). The mini runs cited Joe Wright and Sam Mendes.
  - **G08 (−0.25):** answers cited the presidents list rather than the individual
    presidents.

  So this is different retrieval on failing questions, not looser citing in general.
- **Cost.** The planner and clue step account for $0.70 of the $1.02 per run. The
  stronger model costs 3.3 times as much per token, and median latency rose by 4.5 s.
- **Temperature had no effect in any version.** OpenRouter lists no `temperature`
  parameter for the gpt-5.4 models; they accept `reasoning` effort instead. The 0.2 used
  throughout and the 0 requested for the clue step were both ignored. Earlier notes
  attributing the clue step's stability to temperature 0 were wrong. Reasoning effort is
  the untested lever for model behaviour.

### 6.3 Reflection notes

- **Model strength buys better retrieval decisions more than better answers.** The gains
  show up in recall, precision and attribution. Correctness moved one record, because two
  of the three stubborn failures sit elsewhere: Q014 in the answer model, and G10 in the
  corpus's category naming.
- **"Use a bigger model" is a trade-off to report, not a free win.** It improved the
  retrieval metrics, cost 1.8 times as much and took 4.5 s longer, and it did not fix the
  hardest questions.
- **Upgrading one role at a time kept the result interpretable.** Because the answer model
  and judges stayed fixed, every change here is attributable to the planner.

## 7. Model tests: Claude Haiku 4.5 and reasoning effort

**Question.** Round 3 showed a stronger planner mainly improves retrieval, and several
failures happen after retrieval: Q014's table is in context but misread. Would a model
from a different family, `anthropic/claude-haiku-4.5`, improve the planner, the answer
model, or both? And would OpenRouter's `reasoning` effort, never set in any earlier run,
add to that?

**Setup.** All v2 round-2 features on. Decompose and every judge stay on gpt-5.4-mini, so
the instrument is unchanged. The closed-book answer used for chunk attribution runs on
the answer model, because attribution compares an answer with what the *same* model
says without retrieval. Chunk attribution is therefore not comparable across answer
models and is left out below. Two full runs per configuration, 3 judge votes each.

### 7.1 Results, mean of two runs each

| Metric | gpt-5.4-mini (round 2) | gpt-5.4 planner | Haiku answer only | Haiku planner + answer | **Haiku both + medium reasoning** |
|---|---|---|---|---|---|
| Correctness, majority of 3 votes | 11.5/17 | 12.5/17 | 12.5/17 | 13.5/17 | **14.0/17** (runs: 16, 12) |
| Mean graded correctness | 0.765 | 0.779 | 0.850 | **0.880** | 0.873 |
| Mean aspect coverage | 80.6% | 86.4% | 83.9% | **92.5%** | 90.5% |
| Faithfulness (all claims grounded) | 13.0/17 | 14.0/17 | 13.5/17 | 12.5/17 | 13.5/17 |
| Mean graded groundedness | 95.7% | 95.9% | 94.3% | 93.1% | 94.9% |
| Mean citation support rate | 96.3% | 92.9% | 99.0% | 97.9% | **100.0%** |
| Mean citation precision | 85.5% | 80.9% | 79.3% | **87.3%** | 86.5% |
| Refusal judge "hallucinated" | 4.5 | 6.5 | **4.0** | 6.5 | 5.0 |
| Strict source recall | 67.6% | **70.6%** | 58.8% | **70.6%** | **70.6%** |
| Mean source recall | 76.5% | **79.4%** | 69.1% | 76.5% | **79.4%** |
| Chunk precision | 49.6% | 53.6% | 51.0% | 53.8% | **54.7%** |
| Evidence recall, excluding Q014 | 57.3% | **62.8%** | 52.6% | 61.5% | 60.2% |
| Planned steps per query | 1.18 | 1.18 | 1.44 | 1.82 | 1.50 |
| Median latency, excl. rate-limit waits | 15.3 s | 19.9 s | 16.1 s | 25.7 s | 52.4 s |
| Cost per 17-record run | $0.55 | $1.02 | $0.63 | $0.82 | $1.08 |

**Per record, majority passes over two runs:**

| Record | gpt-5.4-mini | gpt-5.4 planner | Haiku answer | Haiku both | Haiku + reasoning |
|---|---|---|---|---|---|
| **Q014** (1992 voting table) | 0/2 | 0/2 | **2/2** | **2/2** | **2/2** |
| **G08** (president in both centuries) | 1/2 | 1/2 | 0/2 | 0/2 | **2/2** |
| G06 (another Harvard president) | 2/2 | 2/2 | 1/2 | 0/2 | 2/2 |
| G07 (another Yale president) | 1/2 | 1/2 | 2/2 | 2/2 | 2/2 |
| G13 (university's former name) | 1/2 | 2/2 | 1/2 | 2/2 | 1/2 |
| Q019 | 0/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| Q072 | 1/2 | 1/2 | 1/2 | 2/2 | 1/2 |
| G10 (English directors' Oscar films) | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 |

All other records pass in (nearly) every configuration.

### 7.2 What each change contributes

- **The answer model reads; the planner retrieves.** Haiku as the answer model alone, with
  the planner still on gpt-5.4-mini:
  - adds one correct record per run and most of the graded-correctness gain (0.765 →
    0.850);
  - solves **Q014**. Given the same rendered table the mini answer model misread, Haiku
    answers "Falun and Lillehammer tied in Round 4 with 11 votes each … Falun received 41
    votes and Lillehammer received 40" (P P P, all aspects, both runs). This needs the
    rendered table as well: on the raw table Haiku fails Q014 too (section 7.4);
  - costs almost nothing extra ($0.63 against $0.55).
- **Haiku as the planner as well adds another record** (13.5) and restores retrieval:
  strict recall rises from 58.8% to 70.6%. It also plans more (1.8 steps per query).
  About half of the total gain comes from each role.
- **Medium reasoning**, with both roles on Haiku:
  - averages 14.0, but its two runs gave 16/17 and 12/17. The correctness difference
    from 13.5 is within noise.
  - is consistently better on claim and citation quality: 100% citation support, fewer
    "hallucinated" verdicts (5.0 against 6.5), and more faithful answers (13.5 against
    12.5).
  - solves **G08** for the first time in any configuration (2/2), a question that needs
    century-boundary reasoning ("January 1993 to January 2001 spans both").
  - doubles median latency to 52 s and adds about 30% to cost.
- **G06's swings are answer style, not correctness.** Haiku lists several Harvard
  presidents quote by quote, and the judges split on the format, as they did on G07.
- **G10 is unsolved in all ten runs.** The facet tool works when given the right facets;
  no model tried here proposed them.

### 7.3 Recommendation and trade-offs

| Configuration | Correct / run | Graded | Cost / run | Median latency | Best for |
|---|---|---|---|---|---|
| gpt-5.4-mini throughout | 11.5 | 0.765 | $0.55 | 15 s | cheapest agent |
| **Haiku planner + answer** | **13.5** | **0.880** | **$0.82** | **26 s** | **best quality for cost** |
| Haiku both + medium reasoning | 14.0 | 0.873 | $1.08 | 52 s | cleanest citations, hardest reasoning (G08) |

- **Model choice moved the metrics more than any architectural refinement.** Rounds 1–2 of
  v2 kept correctness at 11.5 with a mini model. Changing the model to Haiku took it to
  13.5 at +48% cost. The architecture made that possible: tools such as `read_section` and
  the clue step supply the right context, and a stronger reader turns it into answers.
- **Assign stronger models by role.** The answer role gained most per dollar (Q014,
  graded correctness); the planner role improved retrieval.
- **Reasoning effort helps precision more than correctness at this sample size.** It is
  worth it where wrong citations are costly or questions need arithmetic over retrieved
  facts, but it doubles latency.
- **Noise remains the limit on conclusions.** The 16-versus-12 spread between two identical
  reasoning runs is as large as any difference between configurations. Only effects that
  hold across runs and match a per-record explanation (Q014, G08, strict recall) should be
  treated as real.

### 7.4 Does table rendering matter with a stronger answer model?

**Question.** With gpt-5.4-mini the table rendering showed no effect (section 5.3), and Q014
failed on both the raw and the rendered table. Haiku solved Q014, but every Haiku run used
the rendered index. Would Haiku also read the raw table?

**Test.** Haiku as the answer model (planner on gpt-5.4-mini) with `--disable tables`, on
the four table-heavy records, two runs, 3 judge votes each. The comparison runs are
identical except for the index.

| Record | Rendered tables (2 runs) | Raw tables (2 runs) |
|---|---|---|
| **Q014** (1992 voting table) | **2/2**, graded 1.00 | **0/2**, graded 0.08 |
| Q049 (95th winners table) | 2/2, graded 1.00 | 2/2, graded 0.96 |
| Q005 (Olympic bid lists) | 2/2, graded 1.00 | 2/2, graded 1.00 |
| Q003 (ceremony hosts and winners) | 2/2, graded 1.00 | 2/2, graded 1.00 |

- **With the raw table in context, Haiku misreads it.** Evidence recall is 1.00, so the rows
  are there. One answer reads "Sofia and Falun tied in the run-off … Sofia received 41
  votes and Falun received 41", exactly the misreading the split two-row header invites.
  With the rendered records ("City: Falun; … Round Run-off: 41") it answers correctly in
  both runs.
- **Q014 needs both changes; neither is enough alone:**

  | | Raw table | Rendered table |
  |---|---|---|
  | gpt-5.4-mini answer model | 0/2 | 0/2 |
  | Claude Haiku 4.5 answer model | 0/2 | **2/2** |

- **Caveat.** With raw tables the planner answered straight from the seed in both runs;
  with rendered tables it read the section with `read_section`. The index also changed
  the planner's path, so the test compares the two indexes as a whole. It cannot separate
  "better table text" from "different path".
- **The other three records pass either way.** On this suite the rendering's benefit is
  confined to Q014. It is a real benefit that only a capable enough reader can use.
- **Reflection.** A refinement that looks useless under one model can be necessary under
  another. The round-2 ablations, run on gpt-5.4-mini, would have justified removing the
  table rendering. Ablating one layer at a time is only conclusive for the other layers
  as configured.

## 8. Future work

### 8.1 An `expand` action: widen what has already been found

**The gap.** In a one-shot pipeline, parent-child chunking is the second half of retrieval:
search for small chunks, then hand the answer model their surroundings. The agent inherited
that coupling. Every retrieval tool starts with a new corpus-wide search, and parent
expansion applies only to that search's hits. **No action widens a passage that is
already in the evidence.**

**How it showed on Q049.**
- v1's seed found the 95th ceremony article's lead chunk (c00000, rank 7 of 8).
- The planner then did what its prompt suggested for "the right article but the answer
  sits in a nearby table": `chunks` with `parent: section`. But that runs a new search.
- All three of run A's searches ranked other Best Actor articles higher and returned no
  95th-ceremony chunk, so the widening happened in the wrong articles.

The planner's reasoning was sound; the tool didn't do what the prompt implied. v2's
`read_section` closed most of the gap, because it reads a named section of an article
already in hand with no search step. It still depends on the planner *naming* the right
section, which on Q049 it had to infer from other ceremony articles.

**Proposal: one action, anchored on a passage, widened in steps.**

```
expand {"passage": "P3", "scope": "neighbours" | "section" | "section_and_lead" | "article", "continue": false}
```

| Scope | Reads | Motivating record |
|---|---|---|
| `neighbours` | the passage plus one or two passages either side | lists and tables continuing past a chunk boundary |
| `section` | the passage's whole Header 2 section, subsections included, windowed around it | Q049 (winners table in the "Awards" subsection) |
| `section_and_lead` | that section plus the article's lead and infobox | G13 (answer in the infobox, hit elsewhere) |
| `article` | the whole article within budget, falling back to `section_and_lead` | short articles, or an unclear section |

**Design points:**
- **One action with a `scope`, not four tools.** Choosing among tools is already the
  planner's weakest skill: gpt-5.4-mini never chose `graph` or `decompose` in 35 steps,
  and it misapplied `clarify`. A parameter is an easier choice than a new tool, and it
  matches `chunks {parent}` and `graph {relations}`.
- **Passage ids as the anchor.** The planner currently sees filenames and section labels,
  not passage ids. Each evidence passage needs a short stable id
  (`[P3 · 95th_Academy_Awards.html § lead]`) so the planner can say which one to widen.
- **`continue` for paging.** Long sections are read as a 6-chunk window. `continue: true`
  would read the next window, instead of re-reading the same one as the planner did
  repeatedly on Q014.
- **Narrowest scope first.** The prompt would say to widen only when a step adds nothing
  new; the existing "N new passages" count shows when that happens.
- **Reuse, not rebuild.** The scopes are the 4.1 parent modes (`window`, `section`,
  `lead_section`, `article`) plus round 2's whole-section windows. Fusion already handles
  the 40k-character budget and duplicates.
- **Keep `read_section`** for reading a section by name when none of its passages is in
  the evidence yet.

**How to test it.** Make it a v2 feature with `--disable expand`, run with the planner
that follows tool guidance best (gpt-5.4 or Haiku), so tool design is not confounded with
planner weakness:
- **Targets:** Q049, Q014, G13, Q005, Q003.
- **Success:** equal or better correctness with **fewer planned steps and fewer repeated
  actions**. Q049 should take one `expand` where v1 made three failed searches.

### 8.2 Other open items

- **Facet choice (G10).** The facet tool works when given the right facets ("English film
  directors" and "Best Picture Academy Award winners" gives Mendes and Minghella). No
  model tried here proposed usable facets. Options:
  - a `find_categories` tool that lists matching category titles, so the planner chooses
    real categories instead of inventing phrases;
  - facet proposals checked against the category list before the search runs.
- **Evaluation noise.** Two runs of the same configuration differ by up to four records
  (16 against 12 with Haiku and reasoning). Firm conclusions need more runs per
  configuration or a larger suite, and golden records less sensitive to answer style
  (G06, G07, Q019).
- **Evidence-recall quotes.** Q014's golden quotes are in the pre-rendering table format.
  Content-based matching, or re-deriving the quotes per index, would make evidence recall
  comparable across indexes.
- **Model per role.** The answer role gave the largest gain per dollar (Q014, graded
  correctness); the planner role improved retrieval. A fuller grid (planner × answer ×
  reasoning effort) would find the best cost-quality point, including reasoning on
  gpt-5.4 as planned.
