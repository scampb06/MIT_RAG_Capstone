# Checkpoint 4.1 Chunker Evaluation Report — Mini Suite (`--retriever chunks --parent lead_section`)

**Source results:** `Checkpoint 4.1/evaluation_results/evaluation_chunks_20260921_164639.json` **Comparison run:** `Checkpoint 4.1/evaluation_results/evaluation_baseline_20260921_161030.json` — the same 17 records, same judges, same day, `--retriever baseline` **Golden suite:** `Checkpoint 4.1/mini-4.1-test-suite.json` (17 records in five groups, each tagged with the retrieval behaviour it is meant to exercise) **Corpus:** the full Wikipedia corpus (2,419 articles → 134,107 chunks of ≤2,000 characters, `Checkpoint 2.1/wikipedia_chunks2000_cache`) **Retriever:** BM25 + vector fusion over chunks, `TOP_K=8`, `CANDIDATE_POOL=40`, parent expansion `lead_section` (each hit widened to its section, ≤4 chunks, plus the article's lead/infobox chunks, ≤3, once per article; 40k-character context budget) **Baseline for comparison:** whole-article BM25 + vector fusion, `TOP_K=3`, `CANDIDATE_POOL=10`

## Executive Summary

Comparability notes follow the consolidated baseline report: metrics marked *unit change* are computed over different retrieval units and should be read side by side, not as a delta.

| Metric                                                                 | Baseline (3 articles)                  | Chunker (8 chunks + parents)                      | Comparable?                                                      |
|------------------------------------------------------------------------|----------------------------------------|---------------------------------------------------|------------------------------------------------------------------|
| Binary correctness (pass)                                              | 7/17 (41.2%)                           | 6/17 (35.3%)                                      | yes                                                              |
| Mean graded correctness score                                          | 0.47                                   | 0.43                                              | yes                                                              |
| Mean aspect coverage                                                   | 55%                                    | 56%                                               | yes                                                              |
| Answer relevance (pass)                                                | 17/17                                  | 17/17                                             | yes                                                              |
| Faithfulness (pass)                                                    | 10/17                                  | 10/17                                             | yes                                                              |
| Mean graded groundedness                                               | 78.9%                                  | 87.1%                                             | yes                                                              |
| Mean citation support rate                                             | 88.2%                                  | 95.6%                                             | yes                                                              |
| Mean citation precision                                                | 65.6%                                  | 76.5%                                             | yes                                                              |
| Mean quote fidelity                                                    | 66.7%                                  | 100%                                              | yes (stricter under chunking: only retrieved text can be quoted) |
| Mean chunk attribution score                                           | 59.9%                                  | 62.3%                                             | yes                                                              |
| Strict source recall (all required articles)                           | 5.9%                                   | **41.2%**                                         | unit change: 3 articles vs 8 units (mean 5.06 unique articles)   |
| Mean source recall@3 articles (matched count)                          | 23.5%                                  | **39.2%**                                         | yes — the like-for-like retrieval number                         |
| Mean source recall@k                                                   | 23.5%                                  | 58.8%                                             | unit change                                                      |
| Precision                                                              | 37.3% (@3 articles)                    | 48.2% chunk precision@8 / 42.4% article precision | unit change                                                      |
| Mean evidence recall (golden quotes in context)                        | 36.1%                                  | **49.6%**                                         | yes                                                              |
| Mean context handed to the model                                       | 224,966 chars                          | **28,855 chars**                                  | yes                                                              |
| Refusal outcomes                                                       | n/a 11, hallucinated 5, over_refusal 1 | n/a 10, hallucinated 7                            | yes (see reliability notes)                                      |
| Mean / p95 latency (both runs rate-paced, \~5.7 s throttle per record) | 10.0 s / 13.3 s                        | 10.9 s / 14.5 s                                   | yes                                                              |
| Mean tokens per record                                                 | 232,339                                | 33,434                                            | yes                                                              |
| Total cost (17 records)                                                | \$3.00                                 | **\$0.46**                                        | yes                                                              |

**Headline read:** the chunker did what it was built to do at the retrieval layer and it did not show up in answer correctness. Matched-count recall rose from 23.5% to 39.2%, strict recall from 1 record to 7, evidence recall from 36% to 50%, context shrank 7.8× and cost 6.5× — and binary correctness went from 7/17 to 6/17. Exactly one verdict changed (Q049, a regression caused by the parent policy). The four records that went from zero recall to full recall (Q005, Q014, Q072, G16) all still failed, each for a different, identifiable reason: a misread table, a polarity inversion, a partial list, and a golden answer framed for a different corpus. The retrieval gains are real; the ceiling on this suite is now set by generation and by the two graph-only records.

## Per-Record Results

B = baseline, C = chunker. Evidence = fraction of golden quotes present verbatim in the context. Strict = all required articles retrieved.

| ID   | Group                      | Correctness B → C | Grade (C)              | Aspects B → C | Strict B → C | Evidence B → C | Unique articles (C) | Context B → C | Change         |
|------|----------------------------|-------------------|------------------------|---------------|--------------|----------------|---------------------|---------------|----------------|
| Q006 | comparative_decomposition  | fail → fail       | partial                | 0.40 → 0.60   | ✗ → ✓        | 0.00 → 1.00    | 6                   | 170k → 21k    | better partial |
| Q045 | comparative_decomposition  | pass → pass       | complete               | 1.00 → 1.00   | ✗ → ✗        | 0.50 → 0.25    | 4                   | 190k → 21k    | —              |
| Q049 | comparative_decomposition  | **pass → fail**   | incorrect              | 1.00 → 0.00   | ✗ → ✗        | 0.67 → 0.00    | 8                   | 177k → 26k    | **regression** |
| Q019 | high_precision_chunking    | fail → fail       | partial                | 0.67 → 0.67   | ✗ → ✓        | 0.75 → 1.00    | 3                   | 261k → 24k    | —              |
| Q072 | high_precision_chunking    | fail → fail       | incorrect              | 0.00 → 0.33   | ✗ → ✓        | 0.00 → 0.67    | 7                   | 198k → 37k    | see \#5        |
| Q080 | high_precision_chunking    | pass → pass       | substantially_complete | 0.80 → 0.80   | ✗ → ✗        | 0.50 → 0.50    | 4                   | 138k → 29k    | —              |
| Q003 | multi_entity_precision     | fail → fail       | incorrect              | 0.50 → 0.00   | ✗ → ✗        | 0.00 → 0.00    | 7                   | 112k → 36k    | —              |
| Q005 | multi_entity_precision     | fail → fail       | partial                | 0.00 → 0.67   | ✗ → ✓        | 0.00 → 0.83    | 7                   | 135k → 32k    | better partial |
| Q009 | multi_entity_precision     | pass → pass       | complete               | 1.00 → 0.67   | ✗ → ✗        | 0.75 → 0.75    | 6                   | 168k → 29k    | —              |
| Q014 | multi_entity_precision     | fail → fail       | incorrect              | 0.00 → 0.33   | ✗ → ✓        | 0.00 → 1.00    | 7                   | 199k → 34k    | see \#3        |
| G06  | complex_precision_chunking | pass → pass       | complete               | 1.00 → 1.00   | ✗ → ✗        | 0.80 → 0.60    | 4                   | 306k → 29k    | —              |
| G07  | complex_precision_chunking | pass → pass       | complete               | 1.00 → 1.00   | ✗ → ✗        | 0.67 → 0.33    | 4                   | 330k → 32k    | —              |
| G10  | complex_precision_chunking | fail → fail       | incorrect              | 0.50 → 0.50   | ✗ → ✗        | 0.17 → 0.17    | 5                   | 222k → 30k    | —              |
| G15  | complex_precision_chunking | pass → pass       | complete               | 1.00 → 1.00   | ✓ → ✓        | 1.00 → 1.00    | 3                   | 190k → 24k    | —              |
| G16  | complex_precision_chunking | fail → fail       | incorrect              | 0.00 → 0.50   | ✗ → ✓        | 0.00 → 0.00    | 5                   | 337k → 25k    | see \#3        |
| G08  | unnamed_entity_graph       | fail → fail       | incorrect              | 0.00 → 0.00   | ✗ → ✗        | 0.00 → 0.00    | 5                   | 357k → 35k    | graph-only     |
| G13  | unnamed_entity_graph       | fail → fail       | incorrect              | 0.50 → 0.50   | ✗ → ✗        | 0.33 → 0.33    | 1                   | 325k → 20k    | graph-only     |

### By group

| Group                          | Graded B → C | Aspects B → C | Strict recall B → C | Evidence B → C | Read                                                     |
|--------------------------------|--------------|---------------|---------------------|----------------|----------------------------------------------------------|
| comparative_decomposition (3)  | 0.83 → 0.50  | 0.80 → 0.53   | 0.00 → 0.33         | 0.39 → 0.42    | Q049 regression dominates; decomposition's territory     |
| high_precision_chunking (3)    | 0.50 → 0.42  | 0.49 → 0.60   | 0.00 → 0.67         | 0.42 → 0.72    | retrieval fixed, answers not yet                         |
| multi_entity_precision (4)     | 0.25 → 0.38  | 0.38 → 0.42   | 0.00 → 0.50         | 0.19 → 0.65    | largest retrieval gain of any group                      |
| complex_precision_chunking (5) | 0.60 → 0.60  | 0.70 → 0.80   | 0.20 → 0.40         | 0.53 → 0.42    | G16 now retrieved; parents cost some evidence on G06/G07 |
| unnamed_entity_graph (2)       | 0.00 → 0.00  | 0.25 → 0.25   | 0.00 → 0.00         | 0.17 → 0.17    | unchanged, as predicted                                  |

## Retrieval Diagnostics (no LLM calls)

Two free passes were run before spending judge calls; both are worth keeping in the write-up.

**Parent policy comparison** (`--retrieval-only`, same 17 queries; article recall is identical across rows by construction):

| `--parent`                              | Evidence recall | Mean context | Notes                                                                                                                                                               |
|-----------------------------------------|-----------------|--------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| baseline (3 whole articles)             | 36.1%           | 225k         | reference                                                                                                                                                           |
| none                                    | 42.2%           | 8.4k         | chunking alone already beats the baseline on evidence                                                                                                               |
| window (±1 chunk)                       | 46.0%           | 19.7k        | Q045, G06                                                                                                                                                           |
| section (≤5 chunks)                     | 47.5%           | 22.6k        | Q005 0.33→0.83, G06 0→0.40                                                                                                                                          |
| **lead_section** (section ≤4 + lead ≤3) | **49.6%**       | 28.9k        | adds G06 0.40→0.60 and G10 0→0.17 via the lead/infobox                                                                                                              |
| article (120k budget)                   | 43.1%           | 85.8k        | *worse*: two or three whole articles exhaust the budget; later hits are dropped (Q049) or fall back to one chunk (G16 — the Charles III article alone exceeds 120k) |

**Golden-quote rank diagnostic** (where does the chunk carrying each of the 63 golden quotes rank under fused scoring?): 17 in the top 8, 20 more in the top 100 (ranks 10–110 — reranker or deeper-cut territory), 10 outside the pool entirely (the unnamed second-hop articles: Bush, Elizabeth II, Harvard for G13, the Alaska quake — the graph's job). After the matcher fix, **no golden quote is split across a chunk boundary** in either suite (108/108 found verbatim in some chunk), so 2,000-character chunks with 200-character overlap are not losing evidence at the boundaries.

## Top Findings — Analysis

### 1. Retrieval improved on every axis the suite predicted; correctness did not follow

Strict recall went from 1 record to 7 and evidence recall from 36% to 50%, at 1/8th of the context and 1/6.5th of the cost. The groups built to show chunking — `high_precision_chunking` and `multi_entity_precision` — show it clearly (evidence 0.42→0.72 and 0.19→0.65). But the four records that gained full article recall (Q005, Q014, Q072, G16) all still fail, and the analysis below shows that none of them fails for a retrieval reason any more. This is the most important result of the run: on this suite the chunker has moved the bottleneck from retrieval to generation, plus the two records only the graph can reach.

### 2. The one regression is the parent policy, not the chunker (Q049)

`95th_Academy_Awards.html` was retrieved (rank 7 of 8). Its matching chunk was the *lead*, so `lead_section` returned the lead — "the ceremony took place in 2023 … 23 categories" — and not the "Winners and nominees" section three chunks further down. The model correctly reported that the Best Actor winner was not in the document. The baseline passed only because it handed over the whole 177k-character article. The rank diagnostic puts the winners chunk at fused rank 24, inside the 40-candidate pool: a deeper cut (`--k 12`), a reranker, or a decomposed sub-query ("Best Actor winner 95th Academy Awards") would each have caught it. This is the expected failure mode of a capped parent and the right trade: it cost one record here and saved 200k characters on every record.

### 3. Two generation errors on perfectly retrieved evidence (G16, Q014)

-   **G16** — context contained "born … 14 November 1948" and "became heir apparent when his mother, Queen Elizabeth II, acceded to the throne in 1952"; the judge credited both aspects; the answer begins **"No."** The same polarity inversion appeared in both closed-book answers for this question in the baseline runs. The model states the facts that make the answer "yes" and says no. No retriever change can fix this; it belongs in the write-up as a generation limitation, and the golden record should gain an explicit "the answer is yes" aspect so the inversion is visible in aspect coverage, not only in the binary verdict.
-   **Q014** — all three golden quotes in context (evidence 1.00). Falun/Lillehammer and the 41–40 run-off are correct; the first-round elimination was given as Cortina d'Ampezzo (7 votes) instead of Berchtesgaden (6). A misread of the markdown vote table. 2 of 3 aspects, binary fail.

### 4. A partial list where the parent cap bit (Q005)

2004 and 2008 losing bidders are complete and correctly attributed; the 1996 list has only Athens because the 1996 bid section fell outside the 4-chunk section cap (evidence 0.83 — five of six quotes present). Baseline: zero recall, over-refusal. The chunker turned a refusal into a two-thirds answer; decomposition (one sub-query per Games) is the natural fix for the remaining third.

### 5. A correct answer the golden record does not accept (Q072)

"According to the provided documents, Avatar is the highest-grossing film of all time … \$2.924 billion" is what the full corpus says. The golden record, written for the Titanic-centric subset, expects Titanic's history plus a staleness caveat. One of three aspects credited. Recommend widening the expected answer for the full corpus while keeping the caveat aspect — the answer genuinely lacks the "may be superseded" hedge the record's `temporally_stale` design asks for.

### 6. The graph-only records are unchanged, as predicted (G08, G13)

G08 retrieved presidential list pages but never Clinton; G13 retrieved eight chunks all from `Barack_Obama.html` (unique articles = 1 — a long article monopolising the slots) and never Harvard. Both remain the graph's before/after pair.

### 7. Cost and latency

Cost per record fell from \$0.18 to \$0.03 because the answer and both judge prompts stop embedding three whole articles. Latency did not fall: both runs are paced at ≥3.1 s between LLM calls to stay under the account's 20 requests/minute limit, and that throttle (\~5.7 s per record) dominates. Unthrottled, the chunker's calls are cheaper and shorter; the pacing is an account constraint, not an architectural one.

## Judge & Metric Reliability Notes

-   **The refusal judge flagged 7 answers "hallucinated"** (baseline: 5). Q005 is grounded (`faithfulness: pass`, groundedness 1.0) and flagged anyway; Q080 passed correctness and is flagged. On both runs the flag tracks "the answer is incomplete", not fabrication. Read `refusal_outcome: hallucinated` on answerable records as noise unless the claims list shows an ungrounded assertion.
-   **Faithfulness fails on refusal-flavoured answers again** (Q049: "the winner was not stated in the provided document" → ungrounded). Same quirk as every previous run; six of the seven faithfulness fails here are of this kind or are partial-list answers.
-   **Quote fidelity 100% vs 66.7%** is real, not noise: with chunk context the model can only quote what it saw, and every quotation matched. Under whole-article context the baseline produced two fabricated quotations (see the consolidated report's G06 case).
-   **Aspect coverage vs binary correctness diverge more under the chunker** (0.56 vs 6/17): more answers are two-thirds right. Report graded score and aspect coverage alongside the binary figure or the run reads as a regression it is not.
-   **Evidence recall is a lower bound on answerability.** G16 scores 0.00 because the golden sentences sit in "Early life", yet the lead chunk that *was* retrieved contains both facts in infobox/lead form, and the judge credited both aspects. The metric measures "the exact golden passage is present", which is the right thing to measure for retrieval but should not be read as "the answer is absent".

## Recommendations, Ranked

1.  **Run** `--retriever decompose` **on the same 17 records next** (\~\$0.50). Q049 and Q005 are its textbook cases, and `comparative_decomposition` is the group the chunker moved least.
2.  **Fix two golden records before the next run:** widen Q072's expected answer for the full corpus (Avatar, with the staleness caveat still required); add "the answer is yes" as an explicit aspect on G16.
3.  **Try** `--k 12` **(free, retrieval-only) before adding a reranker.** Twenty golden-quote chunks sit at fused ranks 10–110; the cheapest way to learn how many a deeper cut recovers is a retrieval-only pass.
4.  **Keep** `lead_section` **as the parent policy** for the remaining runs — it won the free comparison — but state its cost honestly in the write-up: Q049 is what a capped parent does to a winners table three chunks below the lead.
5.  **Report G16 and Q014 as generation-side failures**, with the closed-book polarity inversion as evidence. They cap what any retriever change can achieve on this suite and belong in the "where it hurt / remaining limitations" section of the worksheet.
6.  **Run the graph retriever last, on G08 and G13**, once decomposition has been measured — the comparison between the two on those records (with `chunk_attribution` as the tie-breaker) is the architectural argument the checkpoint asks for.

*Generated from* `evaluation_chunks_20260921_164639.json` *(17-record run of* `mini-4.1-test-suite.json`*,* `--retriever chunks --parent lead_section`*) against* `evaluation_baseline_20260921_161030.json` *(same records,* `--retriever baseline`*, same day). Retrieval-only comparisons:* `retrieval_chunks_*.json` *and* `parent_comparison.log`*. Full metric definitions are in* `Checkpoint 3.1/metric_documentation.md` *and the header of* `capstone_checkpoint_4_1_advanced_retrieval_solution.py`*.*
