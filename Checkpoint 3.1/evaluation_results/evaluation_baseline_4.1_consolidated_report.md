# Checkpoint 4.1 Baseline Evaluation Report — Consolidated Relational Query Suite

**Source results:** `evaluation_results/evaluation_baseline_4.1_consolidated.json` — 12 records from `evaluation_20260920_201903.json` plus 6 records (G01, G05, G06, G07, G10, G13) rerun in `evaluation_20260921_080938.json` after the golden-suite edits of 21 September. Each record carries a `_provenance` field naming its source run. **Golden suite:** `Checkpoint 4.1/golden_suite_4.1.json` as of 2026-09-21 (18 records: 15 answerable relational/multi-hop queries, 1 answerable-but-expected-fail navbox case, 2 `unanswerable_from_corpus` probes) **Corpus:** the full Wikipedia corpus (2,419 articles, `Checkpoint 1.1/Wikipedia`) **Retriever:** Checkpoint 3.1 baseline — BM25 + vector hybrid, `TOP_K=3`, `CANDIDATE_POOL=10`, whole-article (unchunked) documents **Status:** this is the reference baseline for the chunker, graph, and decomposition comparisons. It supersedes `evaluation_20260920_201903_report.md`.

## Executive Summary

| Metric                                          | Consolidated baseline                            | 20 Sep run (pre-edit grading)   |
|-------------------------------------------------|--------------------------------------------------|---------------------------------|
| Records evaluated                               | 18                                               | 18                              |
| Binary correctness (pass)                       | 13/18 (72.2%)                                    | 12/18 (66.7%)                   |
| Faithfulness (pass)                             | 13/18 (72.2%)                                    | 13/18 (72.2%)                   |
| Answer relevance (pass)                         | 18/18 (100%)                                     | 18/18 (100%)                    |
| Mean aspect coverage                            | 72.2%                                            | 66.7%                           |
| Mean graded groundedness                        | 87.1%                                            | 88.4%                           |
| Mean citation support rate                      | 92.6%                                            | 91.2%                           |
| Mean citation precision                         | 79.4%                                            | 70.6%                           |
| Mean chunk attribution score                    | 49.0%                                            | 52.2%                           |
| Strict source recall@3 (all required retrieved) | 10/18 (55.6%)                                    | 10/18 (55.6%)                   |
| Mean source recall@3                            | 58.3%                                            | 58.3%                           |
| Mean source precision@3                         | 50.0%                                            | 40.7%                           |
| Refusal outcomes                                | n/a: 14, appropriate_refusal: 2, hallucinated: 2 | n/a: 16, appropriate_refusal: 2 |
| Mean / p95 total latency                        | 8.4 s / 11.4 s                                   | 8.4 s / 10.7 s                  |
| Total cost (18 records)                         | \$3.62 (rerun of six: \$1.07)                    | \$3.66                          |

**Headline read:** 13 of 18 pass. Every improvement over the 20 September figures is a grading change, not a retrieval change: the six rerun queries retrieved **byte-identical document sets** (retrieval is deterministic), and the gains come from the suite now accepting Kennedy on G06 and counting the two list articles as relevant (precision@3 40.7% → 50.0%, citation precision 70.6% → 79.4%). Recall is unchanged at 58.3%. The suite's diagnosis stands: queries that name their target entities pass; queries whose answer lives in an article the query does not name fail (G08, G13) or pass only because whole-article embeddings happen to carry an "aboutness" signal (G01, G05). The two records that were expected to behave as controls and did not — G16 (retrieval whiff) and G10 (constraint violation) — remain the most informative failures.

**Chunk attribution is 49%**, meaning roughly half of all grounded claims were also produced closed-book. For this suite that is the expected floor, not a defect: G02, G03, G14 and G18 are deliberately answerable from general knowledge and are included as controls.

## Per-Record Results

† = rerun on 21 September. Predicted = `anticipated_outcomes.baseline` in the current suite (G01 was re-predicted `possible` when rephrased).

| ID    | Question (short)                             | Predicted | Correctness | Faithful | Strict Recall | Precision@3 | Chunk Attrib. | Refusal             | Prediction held |
|-------|----------------------------------------------|-----------|-------------|----------|---------------|-------------|---------------|---------------------|-----------------|
| G01 † | Another winner of Lesnie's award             | possible  | pass        | pass     | ✓             | 67%         | 0.50          | n/a                 | ✓               |
| G02   | Obama's successor                            | success   | pass        | pass     | ✓             | 33%         | 0.00          | n/a                 | ✓               |
| G03   | Elizabeth II's successor                     | success   | pass        | pass     | ✓             | 33%         | 0.00          | n/a                 | ✓               |
| G04   | Another impeached president                  | success   | pass        | pass     | ✓             | 67%         | 0.00          | n/a                 | ✓               |
| G05 † | Another Best Picture director                | possible  | pass        | pass     | ✗             | 67%         | 0.67          | hallucinated\*      | ✓               |
| G06 † | Another Harvard president                    | possible  | pass        | pass     | ✗             | 100%        | 0.67          | n/a                 | ✓               |
| G07 † | Another Yale president                       | possible  | pass        | pass     | ✗             | 100%        | 0.50          | n/a                 | ✓               |
| G08   | President in both centuries                  | fail      | **fail**    | **fail** | ✗             | 0%          | 1.00          | n/a                 | ✓               |
| G09   | Five current heads of state (unanswerable)   | fail      | pass        | **fail** | ✗             | 0%          | 1.00          | appropriate_refusal | ✓               |
| G10 † | Two Oscar films by English directors         | possible  | **fail**    | pass     | ✗             | 33%         | 0.67          | hallucinated        | ✓               |
| G11   | NI local councils (navbox-only)              | fail      | **fail**    | **fail** | ✓             | 67%         | 0.67          | n/a                 | ✓               |
| G12   | African shared languages (unanswerable)      | fail      | pass        | pass     | ✓             | 33%         | 1.00          | appropriate_refusal | ✓               |
| G13 † | Former name of Obama's law school            | fail      | **fail**    | **fail** | ✗             | 67%         | 0.00          | n/a                 | ✓               |
| G14   | Obama's university founded as King's College | success   | pass        | pass     | ✓             | 67%         | 0.00          | n/a                 | ✓               |
| G15   | Sarajevo vs Dunedin population               | likely    | pass        | pass     | ✓             | 67%         | 0.67          | n/a                 | ✓               |
| G16   | Charles III born before mother's reign?      | success   | **fail**    | **fail** | ✗             | 0%          | —             | n/a                 | **✗**           |
| G17   | Lesnie's Oscar before King Kong?             | success   | pass        | pass     | ✓             | 67%         | 1.00          | n/a                 | ✓               |
| G18   | Bank One Ballpark today                      | success   | pass        | pass     | ✓             | 33%         | 0.00          | n/a                 | ✓               |

\* G05's `hallucinated` flag is a judge false positive — every claim in the answer is grounded and citation-supported. See reliability notes.

**Predictions vs. outcomes:** 17 of 18 held. The only firm miss is G16.

### What the rerun changed, record by record

| ID  | 20 Sep → 21 Sep | Retrieved set                                                  | What actually changed                                                                                                                                  |
|-----|-----------------|----------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
| G01 | pass → pass     | different (query rephrased): Lesnie, King Kong (2005), Lubezki | Lubezki still retrieved without the award name in the query                                                                                            |
| G05 | pass → pass     | identical                                                      | Peter Jackson again; precision 33% → 67% because the records list is now relevant; refusal judge flipped n/a → hallucinated on a near-identical answer |
| G06 | fail → pass     | identical                                                      | Kennedy again; now accepted. Precision 67% → 100%                                                                                                      |
| G07 | pass → pass     | identical                                                      | George H. W. Bush again; same misattributed quotation; precision 67% → 100%                                                                            |
| G10 | fail → fail     | identical                                                      | Different wrong answer: two Eastwood films instead of one, with the nationality contradiction stated in the answer                                     |
| G13 | fail → fail     | identical                                                      | Same honest miss; chunk attribution 0.20 → 0.00                                                                                                        |

## Top Failures — Analysis

### 1. The bridge and intersection queries fail on second-hop retrieval (G08, G13)

These remain the cleanest before/after cases for the graph change, and the rerun confirmed G13 is stable.

-   **G08** ("Which president served in both the 20th and 21st centuries?") retrieved `France.html`, `President_of_the_United_States.html` and `Gothic_Revival_architecture.html` — 0% precision. The closed-book answer was "Bill Clinton, 1993–2001": the model knew the answer and was blocked only by empty context.
-   **G13** ("What was the former name of the university where Barack Obama earned his law degree?") retrieved Obama's article (first hop resolved: Harvard Law School, JD 1991), then the presidents-by-education list and `Oprah_Winfrey.html`. `Harvard_University.html` was never requested because the query never says "Harvard". `source_recall_at_k: 0.5` records the half-completed hop in both runs. The closed-book answer was wrong both times ("Law School of Harvard University"), so parametric knowledge would not have rescued this one.

**Implication:** both are retrieval-of-the-unnamed-entity failures. Chunking does not request the second document either; a typed `education` edge from Obama to `Harvard_University.html`, or a category intersection over president nodes, does. A graph-run pass on either record with `chunk_attribution` staying high is unambiguous evidence that the edge supplied the document.

### 2. A control record failed on retrieval (G16)

"Was Charles III born before his mother's reign began?" retrieved `Louis_XV.html`, `Louis_XIV.html` and `Edward_III_of_England.html`. `Charles_III.html` is 149k characters; its whole-article embedding is dominated by decades of royal-duty content, and the query's remaining tokens ("III", "born", "mother", "reign") are shared by every monarch biography in the corpus. The regnal numeral is a poor BM25 anchor. G03 retrieved `Elizabeth_II.html` without difficulty, so the corpus is not the problem.

**Implication:** this is the whole-article dilution failure from the Checkpoint 3.1 reports appearing on a query that *names* its entity, and it is the strongest single argument in this baseline for the chunker. A passage carrying "Charles was born … 14 November 1948" with the name attached is exactly what chunking produces. Expect G16 to flip under the chunker with no help from the graph.

### 3. The model states the disqualifying fact and answers anyway (G10)

With identical retrieval to the first run (`List_of_Academy_Award_records.html`, `Clint_Eastwood.html`, a BAFTA supporting-actor list), the rerun answered *Unforgiven* and *Million Dollar Baby* — and wrote, in the same sentence, that the biography "identifies Eastwood as an American director". The first run at least paired Eastwood with David Lean; the rerun dropped Lean entirely although the records list line "David Lean (from England) for The Bridge on the River Kwai" was in context both times. Two runs, identical context, two different wrong answers — the temperature-0.2 variance is on the generation side, and the constraint "English" was violated both times.

**Implication:** retrieval never surfaced Mendes or Nolan, so the model was working from a context that contained exactly one English director. The graph's `English film directors` ∩ `Directors of Best Picture Academy Award winners` path enforces the nationality constraint structurally rather than asking the model to honour it. The new required aspect ("each director identified as English") now fails this answer on aspect coverage (0.0), not only on the binary judge.

### 4. A correct answer with a fabricated quotation (G06)

The rerun answered John F. Kennedy — correct, grounded in Harvard's alumni text, and now accepted. But the response presents the phrase "35th president of the United States" in quotation marks as text from `Harvard_University.html`. **That phrase does not appear in the extracted Harvard text**, which describes Kennedy only as a "1940 Harvard College alumnus" and one of "two U.S. presidents, Franklin D. Roosevelt (AB, 1903) and John F. Kennedy (AB 1940)". The fact is true; the quotation is invented. The deterministic `quote_fidelity_rate` scored it 0.0. The LLM claim judge marked the same claim `grounded: true, citation_supported: true`.

**Implication:** true-fact-fabricated-quote is a distinct failure mode from hallucination, and the quote-fidelity metric is currently the only instrument catching it. Treat a record with `correctness: pass` and `quote_fidelity_rate: 0.0` as a citation-integrity defect regardless of what the claim judge says.

### 5. G01 still passes without the award name — and that tells you what the chunker may break

The rephrased query ("Name another cinematographer who has won the same award as Andrew Lesnie") still retrieved `Emmanuel_Lubezki.html`. There is no longer a lexical hook to the award, so this is the dense retriever: a query about "a cinematographer who has won an award" is semantically close to the whole-article embedding of a page *about* an award-winning cinematographer. Whole-article vectors carry a strong topical "aboutness" signal, and that is what carried G01 (and G05's `Sam_Mendes.html`) here.

**Implication:** chunking weakens that signal — section-level chunks are about sections, not people — so G01 may become *harder* for the chunker than for the baseline. The graph path (Lesnie → shared category node → Lubezki) is deterministic and does not depend on either signal. Read a chunker regression on G01 as expected, not as a bug, and read a graph pass on it as a precision/determinism result rather than a reach result. `King_Kong_(2005_film).html` also surfaced (it links Lesnie as cinematographer); it is not in `relevant_files` and costs the record a third of its precision — a reasonable candidate to add.

### 6. The navbox case behaved as documented (G11)

`Belfast.html` and `Northern_Ireland.html` were retrieved (strict recall 1.0); the eleven council names are only in a stripped navbox. The response listed the councils from memory, then retracted mid-answer ("Actually, the document only says … 11 councils … but it does not list all of their names"). Faithfulness correctly failed the ungrounded list. Unchanged from the first run; a documented pipeline limitation, not a retrieval defect.

### 7. The unanswerable probes were handled correctly (G09, G12)

Clean `appropriate_refusal` outcomes with no padding, while the closed-book answers for both confidently supplied five heads of state and a table of African languages. `chunk_attribution: 1.0` on both confirms the refusals came from the context.

## Judge & Metric Reliability Notes

-   **The deterministic quote metrics beat the LLM claim judge twice in the rerun.** G06: fabricated quotation, `quote_fidelity_rate` 0.0, claim judge `grounded: true`. G07: the quotation "Former presidents who attended for undergrad include …" is from `Yale_University.html` but is cited to `[Bill_Clinton.html]`; `quote_attribution_accuracy` 0.0 in both runs, while the claim judge marked the citation unsupported in the first run and supported in the second on identical input. When the two disagree, trust the string match.
-   **The refusal judge is noisy.** G05's rerun answer (Peter Jackson, every claim grounded and citation-supported) was flagged `hallucinated`; the first run's near-identical answer was `n/a`. G10's `hallucinated` is also a stretch — the answer is grounded, it just violates a constraint. Both "hallucinated" counts in the summary table should be read as judge noise, not as fabrications.
-   **The "documents don't say X" groundedness quirk recurs** (G08, G09, G11, G13, G16). Honest statements of absence are marked ungrounded because no passage asserts an absence. On this suite it drags faithfulness down on exactly the records where the model behaved best. Treat `faithfulness: fail` on a refusal as a known false positive unless the claims list shows a substantive ungrounded assertion (as in G11).
-   `chunk_attribution` **judged the same claim inconsistently across runs (G01).** Both runs marked "Lubezki has won Best Cinematography" as *not* attributable to retrieval, although the closed-book answer named John Seale in the first run and Roger Deakins in the second — never Lubezki. The 0.50 score understates the record both times.
-   **Closed-book answers contain internal contradictions (G16, G17).** Both open with "No." and then argue for "yes". Since attribution is judged against the closed-book reference, temporal-ordering records deserve a manual read.
-   **Generation variance at temperature 0.2 is visible on identical context.** G10 produced two different wrong answers from the same three documents. Single-run correctness on borderline records is a coin-flip; the retrieval metrics are the stable signal.

## Recommendations, Ranked

1.  **Run the chunker next against this consolidated baseline.** Per-record expectations: G16 should flip to pass (dilution fix); G06/G07/G15 should hold or improve on precision; G08 and G13 should still fail (second hop never requested); G01 may regress (loss of whole-article "aboutness"); cost per record should fall sharply because the judge prompts stop embedding three whole articles.
2.  **Use G08 and G13 as the graph's headline pair.** Both fail identically across runs with the model explicitly reporting the gap. Neither depends on generation variance.
3.  **Add a citation-integrity check to the report template**: flag any record with `correctness: pass` and `quote_fidelity_rate < 1.0` (G06 here). The claim judge does not catch fabricated quotations of true facts.
4.  **Consider adding** `King_Kong_(2005_film).html` **to G01's** `relevant_files`**.** It links Lesnie as cinematographer and is on-topic; excluding it costs the record precision for a sensible retrieval.
5.  **Keep discounting** `faithfulness` **on refusals and** `refusal_outcome: hallucinated` **on grounded answers** until the judges are averaged over repeats. On this suite the two false "hallucinated" flags and five refusal-quirk faithfulness fails are all judge artefacts.
6.  **Record retrieval determinism in every comparison.** The six rerun queries retrieved identical sets on two days; any correctness change between runs of the *same* configuration is generation variance, and any change between configurations should first be checked at the `retrieved_sources` level before crediting it to the architecture.

*Generated from* `evaluation_baseline_4.1_consolidated.json` *(12 records from* `evaluation_20260920_201903.json` *+ 6 from* `evaluation_20260921_080938.json`*), graded against* `Checkpoint 4.1/golden_suite_4.1.json` *as of 2026-09-21. Full metric definitions are in* `metric_documentation.md` *and* `Module 3/rag_evaluation_guide.md`*.*
