# Checkpoint 3.1 Evaluation Report — Full-Corpus Run

**Source results:** `evaluation_results/evaluation_20260916_183901.json`
**Golden suite:** `Checkpoint 2.1/golden_suite_2.1.json` (15 records, one per query from `my_representative_queries()`, `adversarial_queries()`, and `adversarial_queries_round2()`)
**Corpus:** the full Wikipedia corpus (2,421 articles, `Checkpoint 1.1/Wikipedia`) — **not** the 60-file film/Oscars subset used in the earlier report
**Retriever:** same BM25 + vector hybrid, `TOP_K=3`, whole-article (unchunked) documents

## Executive Summary

| Metric | Value | vs. earlier 18-record / 60-file run |
|---|---|---|
| Records evaluated | 15 | — |
| Binary correctness (pass) | 9/15 (60.0%) | 77.8% |
| Faithfulness (pass) | 11/15 (73.3%) | 83.3% |
| Answer relevance (pass) | 14/15 (93.3%) | 100% |
| Mean aspect coverage | 72.2% | 87.7% |
| Mean graded groundedness | 80.7% | 94.4% |
| Mean citation support rate | 89.7% | 98.8% |
| Mean chunk attribution score | 50.3% | 61.6% |
| Strict source recall@3 (all required retrieved) | 10/15 (66.7%) | 66.7% |
| Mean source recall@3 | 73.3% | 77.8% |
| **Mean source precision@3** | **31.1%** | **51.9%** |
| Refusal outcomes | n/a: 11, appropriate_refusal: 2, hallucinated: 2 | — |
| Total cost (15 records) | $2.21 (~$0.15/record) | ~$0.15/record |

**Headline read:** every quality metric dropped when the same retriever was pointed at the full 2,421-article corpus instead of the curated 60-file subset — and **precision@3 fell hardest, from 52% to 31%**. Strict recall held steady at 66.7% by coincidence of small-sample arithmetic, but the *composition* of failures changed: on the 60-file corpus, misses were usually "the right topic but the wrong specific document." At full-corpus scale, four records missed every single required document, retrieving generically-similar but substantively unrelated Wikipedia pages instead. This is the direct, measured cost of removing the corpus's built-in topical focus.

---

## Per-Record Results

| ID | Question (short) | Correctness | Faithful | Strict Recall | Precision@3 | Chunk Attrib. | Refusal Outcome |
|---|---|---|---|---|---|---|---|
| Q001 | Pamuk's Nobel lecture | pass | pass | ✓ | 33% | 0.25 | n/a |
| Q002 | 2011 quake shortened the day | pass | pass | ✓ | 33% | 0.00 | n/a |
| Q003 | 85th/95th ceremony hosts | **fail** | **fail** | ✗ | 0% | — | n/a |
| Q004 | Yacht → Shefler → Stolichnaya | pass | pass | ✓ | 67% | 0.60 | n/a |
| Q005 | 1996/2004/2008 Olympics losing bids | **fail** | **fail** | ✗ | 0% | — | n/a |
| Q006 | John Snow / cholera pump | pass | pass | ✓ | 33% | 0.00 | n/a |
| Q007 | Le Mans vs. Alaska quake | **fail**\* | pass | ✓ | 67% | 0.73 | n/a |
| Q008 | Reagan year → NFL draft pick | pass | pass | ✗ | 33% | 0.00 | n/a |
| Q009 | Sartre / 1964 Alaska quake | **fail** | pass | ✗ | 33% | 0.33 | n/a |
| Q010 | 1998 curling score (unanswerable) | pass | pass | ✓ | 33% | 1.00 | appropriate_refusal |
| Q011 | Sognefjorden seiche waves | pass | pass | ✓ | 33% | 0.50 | **hallucinated** |
| Q012 | Albertville opening (unanswerable) | pass | pass | ✓ | 33% | 0.80 | appropriate_refusal |
| Q013 | Mart Laar / Estonia | pass | pass | ✓ | 33% | 1.00 | n/a |
| Q014 | 1992 IOC vote run-off | **fail** | **fail** | ✗ | 0% | — | n/a |
| Q015 | Shefler wikilink (unanswerable) | **fail** | **fail** | ✓ | 33% | 0.33 | **hallucinated** |

\* Q007: `correctness: fail` despite `graded_correctness: substantially_complete` and `aspect_coverage: 1.0` — see judge-reliability notes below.

---

## Top Failures — Analysis

### 1. Retrieval collapses on multi-entity queries at full-corpus scale
Four records — **Q003, Q005, Q009, Q014** — retrieved **zero** of their required documents; three of those four scored **0% precision** too, meaning every single retrieved document was irrelevant. Compare Q003 (needs `85th_Academy_Awards.html` + `95th_Academy_Awards.html`, got `Academy_Award_for_Best_Director.html`, `..._Best_Picture.html`, `..._Best_Actor.html` instead) and Q014 (needs `1992_Winter_Olympics.html`, got `1988_Winter_Olympics.html`, `1988_Summer_Olympics.html`, `Australia_at_the_Olympics.html`). In both cases the retriever converged on a *thematically* adjacent cluster — other Oscar-category pages, other Olympic-year pages — rather than the specific document the query actually needed.

Every one of these questions worked correctly in the earlier 60-file-corpus run producing `golden_suite_2.1.json` was researched against. **This is precisely what the corpus swap was designed to test**, and the result is unambiguous: precision@3 fell from 52% to 31% and the retriever now fails outright (not just imprecisely) on compound, multi-entity, or ordinal-numbered queries once thousands of superficially-similar distractor pages exist. This validates and sharpens the top recommendation from the previous report — this is no longer a theoretical risk, it's the dominant failure mode at realistic corpus scale.

**Implication:** whole-article BM25+vector fusion with `TOP_K=3` is not viable against a general Wikipedia corpus for anything beyond simple single-entity fact lookup. Chunking (splitting long articles into passages) plus a materially deeper candidate pool and/or query decomposition for multi-entity questions is no longer optional — it's required before this system can be trusted on organic queries.

### 2. A citation bug that retrieval didn't cause (Q011)
The correct document (`2011_Tōhoku_earthquake_and_tsunami.html`) **was** retrieved — it's first in `retrieved_sources` — and the response's facts are accurate and fully grounded (`faithfulness: pass`). But the response cites **`[Arctic_Ocean.html]`** for both claims instead of the article it actually drew from. `citation_precision` correctly scores this 0.0, and `refusal_outcome` independently flagged it `hallucinated` even though the content itself passed every content-quality check.

**Implication:** this is a pure generation-side citation-attribution bug, not a retrieval failure — worth checking whether the answer prompt's citation instructions get confused when multiple documents are in context (`Arctic_Ocean.html` was also retrieved, per your earlier run's discovery that Arctic_Ocean.html happens to mention this same Norway/seiche detail — the model may have keyword-matched the wrong of two documents that both contain related text).

### 3. `citation_support_rate` caught a "true fact, wrong citation" case (Q008)
Reagan's 1980 election is stated correctly, but `Ronald_Reagan.html` was never retrieved (`source_recall_strict: 0`, `chunk_attribution_score: 0.0` — the model knew this from training, not from context) — and the response nonetheless cites `[1980_NFL_draft.html]` for the Reagan claim, a document that has nothing to do with his election. The claim-level judge correctly marked `citation_supported: false` on exactly that claim while still passing the ones the NFL draft page actually supports.

**Implication:** this is the specific pattern `citation_support_rate` was added to catch, working as intended — a citation marker that's merely *nearby* rather than *actually supporting* the claim next to it.

### 4. The model failed the test built specifically to catch this failure mode (Q015)
Q010 and Q012 — both designed as `unanswerable_from_corpus` — were handled correctly (clean refusals). Q015, testing the same underlying limitation (link targets are stripped from the extracted corpus text), was **not**: the model treated the plain-text infobox label "Owner of SPI Group" as proof of a link target, and inferred an inbound wikilink from `Serene_(yacht).html` merely mentioning Shefler's name by mention rather than confirmed link evidence. `faithfulness: fail` and `refusal_outcome: hallucinated` both caught it, but the answer itself reads confidently and would mislead a user who didn't already know the answer was unverifiable.

**Implication:** the model's refusal calibration is inconsistent across near-identical situations — it correctly recognized "the corpus doesn't have this" in two cases but guessed plausibly in a third. Worth investigating whether the specific phrasing of Q015 (asking about infobox *structure* rather than a missing *fact*) is what threw it off, since that's a subtly different kind of gap than "the number I need isn't here."

### 5. A gap in the golden suite itself, not the RAG pipeline (Q006)
The model retrieved and cited `John_Snow.html` — a real, accurate, on-topic biography article that exists in the full corpus. But `golden_suite_2.1.json`'s `required_sources`/`expected_sources` for this record only list `1854_Broad_Street_cholera_outbreak.html`, since that's what the 60-file-corpus research (done before the corpus swap) anticipated. The correct citation to `John_Snow.html` therefore scores as imprecise (`citation_precision: 0.5`) purely because the golden record didn't know that article existed.

**Implication:** this isn't a system defect — it's a reminder that a golden suite built by hand-researching a corpus needs re-validation (the same kind of pass we ran on `golden_suite.subset.json` → `golden_suite.subset.wholecorpus.json`) whenever the corpus it's checked against changes. `golden_suite_2.1.json` was built directly against the full corpus, but evidently didn't catch every dedicated biography page for entities incidentally mentioned in the target articles.

---

## Judge & Metric Reliability Notes

- **`correctness` and `aspect_coverage` disagree again (Q007).** `graded_correctness: substantially_complete` (0.75) and `aspect_coverage: 1.0` (all three required aspects covered), yet the binary `correctness` field says `fail`. Same pattern flagged in the previous report — these two fields come from one judge call and aren't internally consistent.
- **`answer_relevance: fail` on Q014 looks like an isolated judge call, not a real pattern.** Q003 and Q005 are structurally identical cases (retrieval found nothing relevant, model correctly declined and explained what it found instead), and both scored `answer_relevance: pass`. Q014's decline is no less on-topic. Worth a manual read before trusting this field on borderline "declined but explained" responses.
- **The "documents don't say X" groundedness quirk recurs** (Q003, Q005, Q014) — the same issue flagged before: an accurate statement that a fact is *absent* gets marked `grounded: false` because no chunk states an absence. This structurally penalizes exactly the honest-refusal behavior you want to see more of at full-corpus scale, where refusals are now much more common (4 of 15 records here vs. essentially none in the clean 60-file run).

---

## Recommendations, Ranked

1. **Chunk the corpus.** Whole-article retrieval was already precision-limited on 60 curated documents; at 2,421 documents it now produces outright misses on compound queries. Splitting long articles into passages — combined with a reranking step — is the highest-leverage fix available, and this run is the evidence that it's no longer optional.
2. **Add query decomposition for multi-entity questions.** Every zero-recall failure here (Q003, Q005, Q009, Q014) involves a query naming two or more specific entities (two ceremonies, three Olympic years, two 1964 events). Splitting these into sub-queries before retrieval, then merging results, would likely have saved most of them.
3. **Investigate the citation-misattribution bug from Q011 specifically** — it's a generation-side defect independent of retrieval quality, and the cleanest reproducible case you have: right document retrieved, right facts stated, wrong filename cited.
4. **Re-run the golden-suite-vs-corpus validation workflow periodically**, not just once — Q006 shows that even a full-corpus-built golden suite can miss legitimate documents its own retriever later surfaces (in this case a real biography article for a person only mentioned in passing in the primary source).
5. **Treat `answer_relevance` and `correctness` as advisory rather than authoritative on refusal-flavored responses** until judge calls are averaged over repeats — both showed internal inconsistencies in this 15-record run alone.

---

*Generated from `evaluation_20260916_183901.json` (15-record run of `golden_suite_2.1.json` against the full Wikipedia corpus). Full metric definitions are in `metric_documentation.md` and `Module 3/rag_evaluation_guide.md`.*
