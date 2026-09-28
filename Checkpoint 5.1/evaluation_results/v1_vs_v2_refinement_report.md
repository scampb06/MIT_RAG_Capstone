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
| v2, final | `evaluation_agent_v2_20260927_132135.json`, `evaluation_agent_v2_20260927_133023.json` |
| v2, intermediate | `…_124407.json` (after change-log #11–15), `…_125444.json` and `…_131136.json` (after #16) |

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
