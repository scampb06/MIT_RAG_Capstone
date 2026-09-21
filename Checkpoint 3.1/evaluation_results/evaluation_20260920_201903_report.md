# Checkpoint 4.1 Baseline Evaluation Report — Relational Query Suite

> **Superseded (2026-09-21):** six records (G01, G05, G06, G07, G10, G13) were rerun after golden-suite edits. The reference baseline for the chunker/graph/decomposition comparisons is now `evaluation_baseline_4.1_consolidated.json` and `evaluation_baseline_4.1_consolidated_report.md`. This report is kept as the record of the original run.

**Source results:** `evaluation_results/evaluation_20260920_201903.json`
**Golden suite:** `Checkpoint 4.1/golden_suite_4.1.json` (18 records: 15 answerable relational/multi-hop queries, 1 answerable-but-expected-fail navbox case, 2 `unanswerable_from_corpus` probes)
**Corpus:** the full Wikipedia corpus (2,419 articles, `Checkpoint 1.1/Wikipedia`)
**Retriever:** Checkpoint 3.1 baseline — BM25 + vector hybrid, `TOP_K=3`, whole-article (unchunked) documents. This is the "before" measurement for the three planned architectural changes (chunker, graph, decomposition + fusion).

## Executive Summary

| Metric | Value | vs. 15-record `golden_suite_2.1` full-corpus run |
|---|---|---|
| Records evaluated | 18 | 15 |
| Binary correctness (pass) | 12/18 (66.7%) | 60.0% |
| Faithfulness (pass) | 13/18 (72.2%) | 73.3% |
| Answer relevance (pass) | 18/18 (100%) | 93.3% |
| Mean aspect coverage | 66.7% | 72.2% |
| Mean graded groundedness | 88.4% | 80.7% |
| Mean citation support rate | 91.2% | 89.7% |
| Mean chunk attribution score | 52.2% | 50.3% |
| Strict source recall@3 (all required retrieved) | 10/18 (55.6%) | 66.7% |
| Mean source recall@3 | 58.3% | 73.3% |
| Mean source precision@3 | 40.7% | 31.1% |
| Refusal outcomes | n/a: 16, appropriate_refusal: 2, hallucinated: 0 | n/a: 11, appropriate: 2, hallucinated: 2 |
| Mean / p95 total latency | 8.4 s / 10.7 s | — |
| Total cost (18 records) | $3.66 (~$0.20/record) | ~$0.15/record |

**Headline read:** the baseline passed 12 of 18, and the shape of the result is what the suite was designed to expose. Every query that names its target entities outright passed (G02, G03, G14, G15, G17, G18); every query whose answer lives in an article the query does not name failed or survived only by lexical luck (G01, G05, G08, G13). The three records where the graph is expected to flip the outcome — **G01, G08, G13** — went 1 for 3, and the one pass (G01) was a BM25 hit on the phrase "Best Cinematography" rather than anything relational. Two results were genuine surprises: a control record (G16) failed on retrieval outright, and the corpus turned out to contain **list articles** (`List_of_presidents_of_the_United_States_by_education.html`, `List_of_Academy_Award_records.html`) that short-circuit several "name another X" questions and that the golden suite did not know about.

---

## Per-Record Results

Predicted = the `anticipated_outcomes.baseline` value in the golden suite. ✓/✗ in the last column marks whether the prediction held (correct refusals count as the expected passing behaviour).

| ID | Question (short) | Predicted | Correctness | Faithful | Strict Recall | Precision@3 | Chunk Attrib. | Refusal | Prediction |
|---|---|---|---|---|---|---|---|---|---|
| G01 | Another Best Cinematography winner | fail | pass | pass | ✓ | 67% | 0.50 | n/a | ✗ (lexical luck) |
| G02 | Obama's successor | success | pass | pass | ✓ | 33% | 0.00 | n/a | ✓ |
| G03 | Elizabeth II's successor | success | pass | pass | ✓ | 33% | 0.00 | n/a | ✓ |
| G04 | Another impeached president | success | pass | pass | ✓ | 67% | 0.00 | n/a | ✓ |
| G05 | Another Best Picture director | possible | pass | pass | ✗ | 33% | 1.00 | n/a | ✓ (via list article) |
| G06 | Another Harvard president | possible | **fail**\* | pass | ✗ | 67% | 1.00 | n/a | — (suite defect) |
| G07 | Another Yale president | possible | pass | pass | ✗ | 67% | 0.50 | n/a | ✓ |
| G08 | President in both centuries | fail | **fail** | **fail** | ✗ | 0% | 1.00 | n/a | ✓ |
| G09 | Five current heads of state (unanswerable) | fail | pass | **fail** | ✗ | 0% | 1.00 | appropriate_refusal | ✓ |
| G10 | Two Oscar films by English directors | possible | **fail** | pass | ✗ | 0% | 0.33 | n/a | ✓ |
| G11 | NI local councils (navbox-only) | fail | **fail** | **fail** | ✓ | 67% | 0.67 | n/a | ✓ |
| G12 | African shared languages (unanswerable) | fail | pass | pass | ✓ | 33% | 1.00 | appropriate_refusal | ✓ |
| G13 | Former name of Obama's law school | fail | **fail** | **fail** | ✗ | 33% | 0.20 | n/a | ✓ |
| G14 | Obama's university founded as King's College | success | pass | pass | ✓ | 67% | 0.00 | n/a | ✓ |
| G15 | Sarajevo vs Dunedin population | likely | pass | pass | ✓ | 67% | 0.67 | n/a | ✓ |
| G16 | Charles III born before mother's reign? | success | **fail** | **fail** | ✗ | 0% | — | n/a | **✗ (retrieval miss)** |
| G17 | Lesnie's Oscar before King Kong? | success | pass | pass | ✓ | 67% | 1.00 | n/a | ✓ |
| G18 | Bank One Ballpark today | success | pass | pass | ✓ | 33% | 0.00 | n/a | ✓ |

\* G06: the answer given (John F. Kennedy) is factually correct and grounded in `Harvard_University.html`; the judge failed it because the golden record's expected answer named only George W. Bush. See failure #3.

**Predictions vs. outcomes:** 15 of 18 held. The three misses are G01 (predicted fail, passed by lexical luck — flagged as possible in the suite), G16 (predicted success, failed on retrieval — a genuine surprise), and G06 (scored fail, but the answer was right and the suite was wrong).

---

## Top Failures — Analysis

### 1. The bridge and intersection queries failed exactly as designed (G08, G13)
These are the two records the graph retriever is meant to rescue, and the baseline confirmed the diagnosis precisely.

- **G08** ("Which president served in both the 20th and 21st centuries?") retrieved `France.html`, `President_of_the_United_States.html` and `Gothic_Revival_architecture.html` — 0% precision, 0% recall. Nothing in the query lexically points at Bill Clinton, and whole-article vectors for "president … 20th century … 21st century" match generic history pages. The model correctly declined. The closed-book answer was Bill Clinton, 1993–2001, so the model *knew* the answer and was held back only by the empty context — a clean demonstration that this query needs structure, not a better prompt.
- **G13** ("What was the former name of the university where Barack Obama earned his law degree?") retrieved `Barack_Obama.html` (first hop found: Harvard Law School, 1988–1991, JD), then `List_of_presidents_of_the_United_States_by_education.html` and `Oprah_Winfrey.html` instead of `Harvard_University.html`. The response resolved the bridge entity correctly and then said "the provided documents do not state a former name" — true of what it was given. `source_recall_at_k: 0.5` records the half-completed hop exactly. Note the closed-book answer was also wrong ("Law School of Harvard University"), so unlike G08 this is one where parametric knowledge would not have papered over the gap.

**Implication:** both failures are second-hop retrieval failures, not reasoning failures. Chunking will not fix them (the second document is still never requested); a typed edge from Obama's Education row to `Harvard_University.html`, or a category intersection over president nodes, is the direct fix. These two records are the cleanest before/after evidence available for the graph change.

### 2. A control record failed on retrieval, not reasoning (G16)
"Was Charles III born before his mother's reign began?" was predicted to pass everywhere because Charles III's own article contains both dates. It retrieved **`Louis_XV.html`, `Louis_XIV.html` and `Edward_III_of_England.html`** — three monarchs, none of them Charles — and the model declined. The suite's G03 ("Who succeeded Elizabeth II as monarch?") retrieved `Elizabeth_II.html` without trouble, so the corpus is not the problem. Two things conspired: `Charles_III.html` is 149k characters, so its whole-article embedding is dominated by decades of royal-duty content rather than his birth; and the query's remaining tokens ("III", "born", "mother", "reign") are shared by every monarch biography in the corpus. The regnal numeral "III" is a particularly poor BM25 anchor — it matched Edward III and Louis-era pages as readily as Charles.

**Implication:** this is the whole-article dilution failure from the Checkpoint 3.1 reports showing up on a query that *names* its entity. It is the strongest single piece of evidence in this run for the chunker: a passage-level index would carry "Charles was born … 14 November 1948" as its own unit with the name attached. Expect G16 to flip under the chunker without any help from the graph. The closed-book answer is also worth a look: it opens with "No." and then reasons its way to "born before her reign began" — the model contradicts itself within one paragraph (G17's closed-book answer does the same). These yes/no inversions matter because the closed-book response is the reference for `chunk_attribution_score`.

### 3. The corpus has list articles the suite didn't know about, and they produced one false failure (G06) and two accidental passes (G05, G10-half)
The retriever surfaced `List_of_presidents_of_the_United_States_by_education.html` for G06, G07 and G13, and `List_of_Academy_Award_records.html` for G01, G05 and G10. Neither article was in any record's `relevant_files`, because the suite was built by verifying edges and infobox rows in entity articles, not by searching for pre-aggregated lists.

- **G06** answered **John F. Kennedy** for "another president besides Obama who attended Harvard", grounded in Harvard's alumni list (`chunk_attribution: 1.0`, `faithfulness: pass`). That is a correct answer. The judge failed it because `expected_answer` names George W. Bush and the required aspect says so. **This is a golden-suite defect, not a system failure.** The answer set must be widened to every president Harvard's article lists (Kennedy, both Roosevelts, both Adamses, Hayes, Bush, Obama).
- **G05** answered **Peter Jackson** from the records list. Correct in fact, but Jackson is not among the ten corpus members of `Directors of Best Picture Academy Award winners` (there is no `Peter_Jackson.html`), so the record's recall and citation precision both scored 0 against a right answer. The category-graph path and the list-article path give different, equally valid answers.
- **G10** answered **The Bridge on the River Kwai** (David Lean — correct, from the records list) and **Unforgiven** (Clint Eastwood — wrong: Eastwood is American). The model satisfied the "won Academy Awards" constraint from the retrieved pages and never checked the "English" constraint. Neither Mendes nor Nolan was retrieved. Failing this record was right, but for a different reason than the suite anticipated.

**Implication:** for "name another X" questions, list articles are a lexical shortcut that makes the baseline look more relational than it is. Either the suite accepts them (widen `relevant_files` and answer sets — the honest option, since they are legitimate corpus evidence) or the queries are rephrased so that no list article contains the answer. Do the first before the next run, or the graph comparison will be measured against wrong "failures".

### 4. G01 passed by lexical luck, so it is a weaker graph discriminator than intended
The phrase "Best Cinematographer Oscar winner" is close enough to "Academy Award for Best Cinematography" that BM25 pulled `Emmanuel_Lubezki.html` into the top 3 alongside Lesnie. The answer was correct and well grounded. But the suite predicted this as a *possible* lexical hit, and it happened. Under the graph, the expected improvement on G01 will show up in precision (the shared-category path is deterministic) rather than in correctness, and the record will not by itself demonstrate that the graph found something lexical retrieval could not. A rephrasing that removes the award name from the query — for example "Which other cinematographer in the corpus shares an award category with Andrew Lesnie?" — would make the record discriminate.

### 5. The navbox case behaved as documented, with one visible parametric slip (G11)
`Belfast.html` and `Northern_Ireland.html` were both retrieved (strict recall 1.0), so retrieval did its job; the eleven council names are simply not in the extracted text. The response is instructive: it first *lists* the councils from memory (with "Mid Ulster" twice and a trailing "?"), then retracts in the next sentence — "Actually, the document only says … 11 councils with limited responsibilities, but it does not list all of their names." The claim-level judge marked the list ungrounded and `faithfulness: fail`, which is the right call, and the closed-book answer listed all eleven correctly. This is the clearest example in the run of the model writing from parametric knowledge, noticing, and correcting mid-answer — a behaviour the graded groundedness metric captures better than the binary correctness field would.

### 6. The unanswerable probes were handled correctly (G09, G12)
Both produced clean `appropriate_refusal` outcomes with no hallucinated list-padding, even though the closed-book answers for both confidently supplied five heads of state and a table of African languages. `chunk_attribution: 1.0` on both records is the metric confirming the refusal came from the context, not from the model's priors. G09's `faithfulness: fail` and G12's `citation_support_rate: 0.0` are the "documents don't say X" grading quirk (see below), not real defects.

---

## Judge & Metric Reliability Notes

- **The "documents don't say X" groundedness quirk recurs** (G08, G09, G11, G12, G13, G16). Every honest statement that a fact is *absent* was marked `grounded: false` because no passage asserts an absence. On this suite, which deliberately contains refusal cases, it drags faithfulness down on exactly the records where the model behaved best: G09's only ungrounded claim is "I can't give five examples from these documents without guessing." Treat `faithfulness: fail` on a refusal as a known false positive unless the claims list shows a substantive ungrounded assertion (as in G11).
- **`chunk_attribution` judged one claim inconsistently (G01).** The first claim, "Emmanuel Lubezki is another Best Cinematography Oscar winner," was marked *not* attributable to retrieval even though the closed-book answer named John Seale, not Lubezki — the claim could only have come from the retrieved article. The second claim, listing his three films, was marked attributable. The 0.50 score understates the record.
- **Closed-book answers contain internal contradictions (G16, G17).** Both open with "No." and then argue for "yes". Since `chunk_attribution_score` is computed by comparing claims against this closed-book reference, a self-contradictory reference makes the attribution judgement noisier for yes/no questions. Worth a manual read on temporal-ordering records before trusting the attribution number.
- **`citation_support_rate` caught a real misattribution (G07).** "George H. W. Bush attended Yale" was cited to `Bill_Clinton.html`, which never says so; the judge marked that single claim `citation_supported: false` while passing the claim cited to Yale's page. Same pattern as Q008 in the Checkpoint 3.1 full-corpus report — the metric is doing its job.
- **`correctness` is only as good as the golden answer set.** G06 is a fail on paper and a pass in fact. The binary field cannot distinguish "wrong answer" from "right answer the suite didn't anticipate"; `faithfulness: pass` + `chunk_attribution: 1.0` + `aspect_coverage: 0.0` is the signature to look for.

---

## Recommendations, Ranked

1. **Fix the golden suite before the next run.** Widen G06's answer set to every president Harvard's article lists; add `List_of_presidents_of_the_United_States_by_education.html` to `relevant_files` on G06, G07 and G13 and `List_of_Academy_Award_records.html` on G01, G05 and G10; accept Peter Jackson on G05. Otherwise the chunker and graph runs will be compared against a baseline that under-counts its own correct answers.
2. **Re-run G16 under the chunker first.** It is the purest dilution failure in the run — a named entity, both facts in one article, three wrong monarchs retrieved — and it should flip without the graph. If it does not, the problem is the regnal-numeral token and the fix is on the query side.
3. **Use G08 and G13 as the graph's headline before/after pair.** Both failed on second-hop retrieval with the model explicitly reporting the gap. A pass on either under the graph, with `chunk_attribution` staying high, is unambiguous evidence that the edge (not memory) supplied the missing document.
4. **Rephrase G01 to remove the award name**, or accept that it measures precision rather than reach. As written it passed lexically and will not demonstrate a graph-only capability.
5. **Add a constraint-check aspect to G10** ("both directors are identified as English") so the Unforgiven error is caught by aspect coverage rather than only by the binary correctness judge — the graph's `English film directors` category path is precisely what enforces that constraint, and the metric should be able to see it.
6. **Keep discounting `faithfulness` on refusals** until the claim judge is taught that "the documents do not state X" is grounded when X is genuinely absent. On this suite six records are affected.

---

*Generated from `evaluation_20260920_201903.json` (18-record baseline run of `Checkpoint 4.1/golden_suite_4.1.json` against the full Wikipedia corpus). Full metric definitions are in `metric_documentation.md` and `Module 3/rag_evaluation_guide.md`.*
