# Checkpoint 3.1 Evaluation Report — Subset Run

**Source results:** `evaluation_results/evaluation_20260916_154603.json`
**Golden suite:** `golden_suite.subset.json` (18 records, stratified subset — see subset selection rationale in-session)
**Retriever:** BM25 + vector hybrid, `TOP_K=3`, whole-article (unchunked) documents
**Run date reflected in filename:** 2026-09-16

## Executive Summary

| Metric | Value |
|---|---|
| Records evaluated | 18 |
| Binary correctness (pass) | 14/18 (77.8%) |
| Faithfulness (pass) | 15/18 (83.3%) |
| Answer relevance (pass) | 18/18 (100%) |
| Mean aspect coverage | 87.7% |
| Mean graded groundedness | 94.4% |
| Mean citation support rate | 98.8% |
| Mean chunk attribution score | 61.6% |
| Strict source recall@3 (all required retrieved) | 12/18 (66.7%) |
| Mean source recall@3 | 77.8% |
| Mean source precision@3 | 51.9% |
| Refusal outcomes | n/a: 11, hallucinated: 4, appropriate_refusal: 3 |
| Total cost (18 records) | $2.656 (~$0.148/record) |
| Total tokens | 3,470,558 |

**Headline read:** generation quality is solid where retrieval succeeds (citation support and groundedness are both consistently high), but retrieval precision is the weak link — only about half of what's retrieved at k=3 is actually relevant, and a third of records are missing at least one required document entirely. Three of the four "top failures" below trace back to retrieval, not generation.

---

## Per-Record Results

| ID | Question (short) | Scope | Adversarial | Correctness | Faithful | Strict Recall | Precision@3 | Chunk Attrib. | Refusal Outcome |
|---|---|---|---|---|---|---|---|---|---|
| Q036 | Record for most nominations (single film) | multi | temporally_stale | pass | pass | ✗ | 33% | 1.00 | appropriate_refusal |
| Q072 | Highest-grossing film of all time | multi | temporally_stale | **fail** | pass | ✓ | 33% | 1.00 | hallucinated |
| Q079 | Titanic director's total Oscars | single | unanswerable | pass | **fail** | ✓ | 33% | 1.00 | appropriate_refusal |
| Q098 | About the film King Kong | multi | ambiguous_entity | pass | pass | ✗ | 33% | 0.29 | hallucinated |
| Q100 | Whiplash "won" Best Picture? | multi | false_premise | pass | pass | ✓ | 100% | 1.00 | appropriate_refusal |
| Q091 | Ben Kingsley's career | single | — | pass | pass | ✓ | 33% | 0.38 | hallucinated |
| Q002 | Titanic noms vs. wins | multi | — | pass | pass | ✗ | 33% | 0.00 | n/a |
| Q006 | Animated Feature vs. Score category history | multi | — | **fail** | **fail** | ✗ | 0% | 1.00 | n/a |
| Q019 | La La Land director's start | multi | — | pass | pass | ✓ | 67% | 1.00 | n/a |
| Q042 | Crash Best Picture reassessment | multi | — | pass | pass | ✓ | 100% | 0.86 | n/a |
| Q045 | Brokeback vs. La La Land upsets | multi | — | pass | **fail** | ✗ | 67% | 0.47 | hallucinated |
| Q049 | Best Actor 95th ceremony | multi | — | **fail** | pass | ✗ | 33% | 0.50 | n/a |
| Q058 | Best Supporting Actor, Godfather II | multi | — | **fail** | pass | ✓ | 67% | 0.67 | n/a |
| Q067 | Whiplash Sundance awards | multi | — | pass | pass | ✓ | 100% | 0.00 | n/a |
| Q074 | Spielberg / Schindler's List | multi | — | pass | pass | ✓ | 33% | 1.00 | n/a |
| Q080 | Anthony Minghella career | multi | — | pass | pass | ✓ | 67% | 0.57 | n/a |
| Q086 | Biggest nomination gap | multi | — | pass | pass | ✓ | 67% | 0.20 | n/a |
| Q094 | Costner: Horizon vs. Dances With Wolves | multi | — | pass | pass | ✓ | 33% | 0.15 | n/a |

---

## Top Failures — Analysis

### 1. Retrieval precision is the dominant failure driver
Mean precision@3 is **51.9%** — on a typical record, roughly 1.5 of the 3 retrieved documents are off-target. **Q006** is the extreme case: 0% precision *and* 0% recall — none of the three retrieved documents (`Academy_Award_for_Best_Director.html`, `Academy_Award_for_Best_Picture.html`, `Academy_Award_for_Best_Production_Design.html`) had anything to do with the actual question (a comparison of the 74th and 68th ceremonies' category history). The model correctly declined to fabricate the missing half of the answer, but still failed outright on correctness because the right documents were never in front of it.

**Implication:** this is a retrieval-depth/query-formulation problem, not a generation problem. Multi-entity comparative queries (two ceremonies, two films, two categories) are where the BM25+vector hybrid struggles most — `source_recall_strict` is 66.7% overall but drags noticeably lower on `in_depth`/comparison-style questions specifically (Q006, Q045, Q049 all missed required documents). Worth testing a higher `CANDIDATE_POOL`/`TOP_K` for compound queries, or decomposing multi-entity questions into sub-queries before retrieval.

### 2. Temporal staleness produced a confident, uncaveated wrong answer (Q072)
Asked "the highest-grossing film of all time," the model retrieved the right document, correctly quoted that Avatar "surpassed" Titanic in 2010, and then asserted **Avatar** as the current answer — with no hedge about the corpus's cutoff date, even though the golden answer explicitly wants a "these figures reflect the sources' date and may be superseded" caveat. `refusal_outcome` correctly caught this as `hallucinated`. This is a real system-prompt gap: nothing in `ANSWER_SYSTEM` currently instructs the model to flag potential staleness on "current record"/"latest"/"as of now"-type questions.

**Implication:** add an explicit staleness-hedging instruction to the answer system prompt for superlative/"current" framed questions, and consider surfacing the source documents' implicit recency (e.g., the most recent ceremony year in the retrieved set) so the model has something concrete to caveat against.

### 3. Ambiguous-entity disambiguation failed silently, and the correctness judge missed it (Q098, and again in Q036)
Asked generically "about the film King Kong" — a corpus with two distinct King Kong-related entries — the model retrieved unrelated documents (`Brokeback_Mountain.html`, `The_Wings_of_the_Dove_(1997_film).html`) and confidently described only the 1976 film with zero acknowledgment that the question was ambiguous or that other data existed. Yet `graded_correctness` scored this **"complete" with 100% aspect coverage**, including credit for aspects it says word-for-word "the corpus covers more than one" and "please specify which you mean" — neither of which appears anywhere in the response. Only the independent `refusal_outcome` judge caught this as `hallucinated`.

The same over-crediting shows up again in **Q036**: the required aspects include "Note that this reflects the corpus's most recent recorded ceremony and may be out of date," and it's marked `covered`, but the actual response — *"The current record is 16 nominations for a single film, held by Sinners (2025)"* — contains no caveat of any kind. This is structurally the same staleness gap as Q072 (finding #2), except here `refusal_outcome` said `appropriate_refusal` instead of catching it, where the near-identical gap in Q072 *was* caught as `hallucinated`. Same failure mode, same judge, inconsistent verdict.

**Implication:** this is the clearest evidence in the run that a single correctness (or refusal) judge call is not reliable enough to trust alone — it produced a false "complete"/"appropriate" verdict on responses that plainly missed a required element, twice, and disagreed with itself on structurally identical cases. This validates running faithfulness/relevance/refusal as *separate* judgments rather than one aggregate score, and argues for the guide's recommendation (§9) to average judge calls over repeats before using `graded_correctness` or `refusal_outcome` for any automated gating.

### 4. New `citation_support_rate` metric caught exactly the failure it was built for (Q094)
In the Costner comparison, two synthesis sentences — "In scale, Horizon is larger as a multi-film project" and "In reception, Horizon has been far less warmly received" — were cited to `Kevin_Costner.html` alongside the surrounding factual claims, but the judge correctly flagged `citation_supported: false` on both: the page states the underlying facts, not the comparative conclusion drawn from them. This is precisely the "cites the correct article after an unsupported sentence" pattern you asked this metric to catch — the old `citation_precision` metric would have scored this a perfect 1.0 since the filename itself is correct.

**Implication:** the metric is working as designed. Worth watching for this pattern specifically in `in_depth`/comparison-type questions, where the model tends to append an evaluative summary sentence and reuse the last-cited source rather than either citing nothing or explicitly noting the synthesis is its own.

### 5. Chunk attribution shows retrieval is often decorative on famous-trivia questions
Mean chunk attribution is 61.6%, but on canonical Oscar trivia it collapses: **Q002** (Titanic noms/wins) 0%, **Q067** (Whiplash Sundance) 0%, **Q094** (Costner filmography) 15%, **Q086** (nomination-gap record) 20%. In these cases the closed-book model reproduced the same specific facts with no context at all — the citations are accurate, faithfulness is high, but retrieval wasn't actually load-bearing. This is the parametric-leakage failure mode the metric exists to surface, and it's common precisely because the corpus (real Wikipedia Oscar history) overlaps heavily with the model's training data.

**Implication:** this run can't cleanly distinguish "retrieval works" from "the model already knew this" on well-known-trivia questions. If verifying retrieval dependence matters for the capstone's grading criteria, the *in_depth*/multi-document/obscure-detail questions (Q074, Q080 — both scored 57–100% attribution) are the more meaningful signal than the fact-lookup ones.

---

## Metric & Judge Reliability Notes

- **Two `hallucinated` refusal labels look like judge noise, not real failures.** Q091 (Ben Kingsley) and Q045 (Brokeback/La La Land comparison) both pass `faithfulness` and score ≥75% on `graded_correctness` from the independent correctness judge, yet the refusal judge separately flagged both as `hallucinated`. With only one judge call per record (no repeats, per the guide's §9 caution about LLM-judge variance), these read as plausible false positives rather than confirmed issues — worth a manual read before trusting `refusal_outcome` as a hard signal, especially at this small sample size.
- **`faithfulness` penalizes honest "the documents don't say X" statements.** In Q079, Q006, and Q045, claims like *"the documents do not say how many Oscars Cameron received"* were marked `grounded: false` — technically correct, since no chunk states an absence, but this isn't a fabrication, it's the model accurately describing a retrieval gap. As written, `judge_claims()` conflates "unsupported claim" with "claim about what's missing." Worth exempting self-referential coverage statements from the groundedness check in a future revision.
- **`graded_correctness` and `aspect_coverage` disagree with each other on the same call.** Q100 scored `graded_correctness: complete` (1.0) with `aspect_coverage: 0.4` (2 of 5 required aspects); Q019 scored `substantially_complete` (0.75) despite `aspect_coverage: 1.0`. These come from the same judge invocation, so the holistic label and the itemized aspect check aren't self-consistent — another data point for averaging repeats before treating either field as precise.
- **A citation-formatting bug silently broke `citation_precision` in Q002.** The model wrote `[Titanic_(1997_film.html)]` — missing the closing parenthesis before `.html` — so the deterministic citation matcher couldn't resolve it to the actual retrieved file, scoring `citation_precision: 0.0` on what was otherwise a correct, well-grounded citation. Filenames containing parentheses are a plausible recurring trip hazard for both the generator and the regex-based matcher.

---

## Recommendations, Ranked

1. **Improve multi-entity retrieval.** Precision@3 (52%) and strict recall (67%) are the biggest levers on correctness — Q006's total retrieval miss is the clearest single example. Consider query decomposition for comparative questions, or raising `TOP_K`/`CANDIDATE_POOL` specifically when the query mentions two or more distinct entities/ceremonies.
2. **Add a staleness-hedging instruction** to `ANSWER_SYSTEM` for "current"/"latest"/superlative-record questions, so answers like Q072 caveat instead of asserting.
3. **Don't trust `graded_correctness` alone** — Q098 shows it can score "complete" on a response that failed the actual task. Keep relying on the independent judges (faithfulness, relevance, refusal) as cross-checks, and consider having the correctness judge re-derive its verdict from `aspect_coverage` rather than scoring both independently in one pass.
4. **Refine `judge_claims()` to not penalize honest gap-acknowledgment.** Faithfulness dropped on three records purely because the model correctly said "the documents don't cover X."
5. **Harden citation-string matching** against filename punctuation typos (fuzzy match, or strip/normalize parentheses before comparing) so a single missing character doesn't zero out `citation_precision`.
6. **Treat `chunk_attribution_score` as most informative on in_depth/obscure questions**, not fact-lookup trivia — on this corpus, well-known facts are frequently reproducible closed-book regardless of retrieval quality.

---

*Generated from `evaluation_20260916_154603.json` (18-record stratified subset run). Full definitions for every metric referenced here are in `metric_documentation.md` and `Module 3/rag_evaluation_guide.md`.*
