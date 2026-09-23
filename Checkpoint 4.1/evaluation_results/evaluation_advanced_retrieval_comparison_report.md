# Checkpoint 4.1 Advanced Retrieval — Comparative Evaluation Report

**Suite:** `Checkpoint 4.1/mini-4.1-test-suite.json` — 17 records in five groups, each tagged with the retrieval behaviour it is meant to exercise (`group` field). All four runs use the same records, the same judges, and the same day (2026-09-21), so judge drift between days is not a factor. **Corpus:** the full Wikipedia corpus (2,419 articles; 134,107 chunks of ≤2,000 characters for the chunk strategies). **Runs compared:**

| Key | Run       | Results file                                | Configuration                                                                                                                                                                                           |
|-----|-----------|---------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| B   | Baseline  | `evaluation_baseline_20260921_161030.json`  | Checkpoint 3.1 whole-article BM25 + vector fusion, `TOP_K=3`, `CANDIDATE_POOL=10`                                                                                                                       |
| C   | Chunker   | `evaluation_chunks_20260921_164639.json`    | chunk BM25 + vector fusion, `TOP_K=8`, `CANDIDATE_POOL=40`, parent `lead_section`, 40k budget                                                                                                           |
| D   | Decompose | `evaluation_decompose_20260921_181908.json` | Lab 4.1: LLM sub-queries (2–4), per-chunk score summing, same chunk index and parent policy as C                                                                                                        |
| G   | Graph     | `evaluation_graph_20260921_183400.json`     | Lab 4.2: 4 seed articles from the chunk index, expanded through category-title matching, category co-membership, infobox and hyperlink edges; primary/context labelling; same parent policy, 60k budget |

Companion documents: `evaluation_baseline_4.1_consolidated_report.md` (the 18-record baseline), `evaluation_chunks_20260921_164639_report.md` (the chunker run in depth, including the parent-policy comparison), `parent_comparison.log` and `retrieval_*.json` (free retrieval-only passes).

## Executive Summary

| Metric                                                      | B Baseline        | C Chunker               | D Decompose   | G Graph        | Comparable?                                                         |
|-------------------------------------------------------------|-------------------|-------------------------|---------------|----------------|---------------------------------------------------------------------|
| Binary correctness                                          | 7/17 (41%)        | 6/17 (35%)              | 7/17 (41%)    | **8/17 (47%)** | yes                                                                 |
| Mean graded correctness                                     | 0.47              | 0.43                    | 0.56          | **0.66**       | yes                                                                 |
| Mean aspect coverage                                        | 0.55              | 0.56                    | **0.69**      | 0.67           | yes                                                                 |
| Faithfulness (all claims grounded)                          | 10/17             | 10/17                   | **11/17**     | 9/17           | yes                                                                 |
| Mean graded groundedness                                    | 0.79              | **0.87**                | 0.85          | 0.86           | yes                                                                 |
| Mean citation precision                                     | 0.66              | 0.76                    | **0.85**      | 0.78           | yes                                                                 |
| Mean quote fidelity                                         | 0.67              | **1.00**                | 0.92          | 0.79           | yes                                                                 |
| Mean chunk attribution                                      | 0.60              | **0.62**                | 0.48          | 0.59           | yes — lower means more of the answer was also available closed-book |
| Strict source recall (all required articles)                | 6%                | 41%                     | 47%           | **59%**        | unit change (3 articles vs 8 units) — read with recall@3            |
| Source recall@3 articles (matched count)                    | 24%               | 39%                     | **55%**       | 39%            | yes — the like-for-like retrieval number                            |
| Mean unique articles in context                             | 3.0               | 5.1                     | 4.2           | 8.0            | —                                                                   |
| Precision                                                   | 37% (@3 articles) | 48% chunk / 42% article | **55% / 49%** | 26% / 26%      | unit change                                                         |
| Mean evidence recall (golden quotes in context)             | 36%               | 50%                     | **51%**       | 50%            | yes                                                                 |
| Mean context per query                                      | 225k chars        | 29k                     | **25k**       | 39k            | yes                                                                 |
| Mean tokens per record                                      | 232k              | 33k                     | **29k**       | 44k            | yes                                                                 |
| Cost (17 records)                                           | \$3.00            | \$0.46                  | **\$0.40**    | \$0.60         | yes                                                                 |
| Mean / p95 latency (all runs paced at ≥3.1 s between calls) | 10.0 / 13.3 s     | 10.9 / 14.5 s           | 14.2 / 19.7 s | 10.1 / 14.5 s  | yes; decompose adds one LLM call per record                         |

**Headline read.** Every advanced configuration retrieves far better than the baseline (strict recall 6% → 41–59%, evidence recall 36% → \~50%) at a fraction of the context (225k → 25–39k characters) and cost (\$3.00 → \$0.40–0.60). Converting that into correct answers was the harder part: the chunker alone did not move correctness at all, decomposition moved graded correctness and aspect coverage (0.47 → 0.56, 0.55 → 0.69), and the graph produced the best binary and graded scores (8/17, 0.66) by solving the two records built for it — G08 and G13, which no lexical configuration could reach — plus G16 and Q005. Each technique also lost something: the chunker lost Q049 to its parent policy, decomposition lost Q045/Q009 on single aspects and halved chunk attribution by naming answer entities in its sub-queries, and the graph lost Q045/Q080/Q009 to over-broad context (precision 26%). The techniques are complementary, and the per-group table shows where each belongs.

## Per-Record Results

Correctness, aspect coverage, strict recall and evidence recall for the four runs (B/C/D/G). "Change" compares each advanced run with the baseline.

| ID   | Group                      | Correctness B/C/D/G         | Aspects B/C/D/G     | Strict recall B/C/D/G | Evidence B/C/D/G    | Change vs baseline    |
|------|----------------------------|-----------------------------|---------------------|-----------------------|---------------------|-----------------------|
| Q006 | comparative_decomposition  | fail/fail/**pass**/**pass** | 0.40/0.60/0.80/1.00 | ✗/✓/✓/✓               | 0.00/1.00/1.00/1.00 | D, G gain             |
| Q045 | comparative_decomposition  | pass/pass/fail/fail         | 1.00/1.00/0.67/0.67 | ✗/✗/✓/✗               | 0.50/0.25/0.75/0.25 | D, G lose (partial)   |
| Q049 | comparative_decomposition  | pass/fail/fail/fail         | 1.00/0.00/0.33/0.00 | ✗/✗/✗/✗               | 0.67/0.00/0.33/0.00 | all lose (see \#4)    |
| Q019 | high_precision_chunking    | fail/fail/fail/fail         | 0.67/0.67/1.00/0.67 | ✗/✓/✓/✓               | 0.75/1.00/0.25/0.50 | —                     |
| Q072 | high_precision_chunking    | fail/fail/fail/fail         | 0.00/0.33/0.33/0.00 | ✗/✓/✗/✗               | 0.00/0.67/0.00/0.00 | — (see \#6)           |
| Q080 | high_precision_chunking    | pass/pass/pass/fail         | 0.80/0.80/0.80/0.60 | ✗/✗/✗/✗               | 0.50/0.50/0.50/0.50 | G loses               |
| Q003 | multi_entity_precision     | fail/fail/**pass**/fail     | 0.50/0.00/1.00/0.00 | ✗/✗/✓/✗               | 0.00/0.00/1.00/0.00 | D gains               |
| Q005 | multi_entity_precision     | fail/fail/fail/**pass**     | 0.00/0.67/0.67/1.00 | ✗/✓/✓/✓               | 0.00/0.83/0.83/0.83 | G gains; C, D partial |
| Q009 | multi_entity_precision     | pass/pass/fail/fail         | 1.00/0.67/0.67/0.33 | ✗/✗/✗/✗               | 0.75/0.75/0.75/0.75 | D, G lose (partial)   |
| Q014 | multi_entity_precision     | fail/fail/fail/fail         | 0.00/0.33/0.00/0.67 | ✗/✓/✓/✓               | 0.00/1.00/1.00/1.00 | — (see \#5)           |
| G06  | complex_precision_chunking | pass/pass/pass/pass         | 1.00/1.00/1.00/1.00 | ✗/✗/✗/✓               | 0.80/0.60/0.40/0.80 | G retrieves Bush      |
| G07  | complex_precision_chunking | pass/pass/pass/pass         | 1.00/1.00/1.00/1.00 | ✗/✗/✗/✓               | 0.67/0.33/0.33/0.33 | G retrieves Bush      |
| G10  | complex_precision_chunking | fail/fail/fail/fail         | 0.50/0.50/1.00/0.50 | ✗/✗/✗/✗               | 0.17/0.17/0.17/0.00 | — (see \#7)           |
| G15  | complex_precision_chunking | pass/pass/pass/pass         | 1.00/1.00/1.00/1.00 | ✓/✓/✓/✓               | 1.00/1.00/1.00/1.00 | control               |
| G16  | complex_precision_chunking | fail/fail/**pass**/**pass** | 0.00/0.50/1.00/1.00 | ✗/✓/✓/✓               | 0.00/0.00/0.00/0.33 | D, G gain             |
| G08  | unnamed_entity_graph       | fail/fail/fail/**pass**     | 0.00/0.00/0.00/1.00 | ✗/✗/✗/✓               | 0.00/0.00/0.00/0.50 | **G gains**           |
| G13  | unnamed_entity_graph       | fail/fail/fail/**pass**     | 0.50/0.50/0.50/1.00 | ✗/✗/✗/✓               | 0.33/0.33/0.33/0.67 | **G gains**           |

### By group

| Group (n)                      | Metric                        | B               | C               | D               | G                   |
|--------------------------------|-------------------------------|-----------------|-----------------|-----------------|---------------------|
| comparative_decomposition (3)  | pass / graded / strict recall | 2 / 0.83 / 0.00 | 1 / 0.50 / 0.33 | 1 / 0.58 / 0.67 | 1 / 0.58 / 0.33     |
| high_precision_chunking (3)    | pass / graded / strict recall | 1 / 0.50 / 0.00 | 1 / 0.42 / 0.67 | 1 / 0.50 / 0.33 | 0 / 0.33 / 0.33     |
| multi_entity_precision (4)     | pass / graded / strict recall | 1 / 0.25 / 0.00 | 1 / 0.38 / 0.50 | 1 / 0.50 / 0.75 | 1 / 0.50 / 0.50     |
| complex_precision_chunking (5) | pass / graded / strict recall | 3 / 0.60 / 0.20 | 3 / 0.60 / 0.40 | 4 / 0.85 / 0.40 | 4 / 0.90 / 0.80     |
| unnamed_entity_graph (2)       | pass / graded / strict recall | 0 / 0.00 / 0.00 | 0 / 0.00 / 0.00 | 0 / 0.00 / 0.00 | **2 / 1.00 / 1.00** |

The groups behaved as the suite predicted, with one surprise: `comparative_decomposition` is where the baseline did *best* (its whole-article context happened to contain the Q049 winners table) and none of the advanced configurations recovered that record.

## Findings — Analysis

### 1. Retrieval improved everywhere; correctness only where the technique matched the failure

The baseline's dominant failure was retrieval (strict recall 6%). All three advanced configurations fixed most of it — but a retrieved passage is only a pass if the model then answers correctly and the golden answer accepts it. Findings \#4–\#7 are the four records that gained full recall under the chunker and still failed, and each has a non-retrieval cause. On this suite the chunker moved the bottleneck from retrieval to generation; decomposition and the graph then addressed the residual retrieval failures that were structural (multi-entity, unnamed second hop).

### 2. Decomposition: the multi-entity specialist, with a provenance cost

Q003 is the showcase — "85th Academy Awards host Best Picture winner" and "95th … " as separate sub-queries retrieved both ceremony articles and produced a complete, cited comparison where the baseline and chunker had zero recall. Q005 split into one sub-query per Games; G16 split into "Charles III birth date" and "Elizabeth II reign began" and, for the first time, the answer was "Yes" with both dates. Matched-count recall (55%) and chunk precision (55%) are the best of any run. The cost is visible in `chunk_attribution`, which fell from 0.62 to 0.48: the sub-queries frequently name the answer entity from memory before anything is retrieved — Q045 → "Brokeback Mountain", Q019 → "Damien Chazelle", Q072 → "Avatar", Q009 → "Jean-Paul Sartre". The retrieval then grounds an answer the model already had. This is the parametric-bridge behaviour the suite notes warned about, and the metric caught it. Decomposition did *not* inject Clinton or Harvard for G08/G13, and both still failed — the cleanest possible control for the graph.

### 3. Graph: solves the unnamed-entity records, pays in precision

G08 passed through a category intersection — `Bill_Clinton.html` is the only article in both `20th-century presidents of the United States` (11 corpus members) and `21st-century presidents of the United States` (4) — and G13 through Obama's typed `Education` edge to `Harvard_University.html`, whose lead/infobox parent carried "Former names \| Harvard College". G16 reached `Elizabeth_II.html` through the `Mother` infobox edge; G06 and G07 reached `George_W._Bush.html` through Ivy League and Yale links. These are the relationships the node/edge schema was designed to expose, and none of them are reachable lexically.

The price is context precision: 26% at the chunk level, the lowest of any run. Seed-and-expand adds Theresa May to a question about Charles III's birth (she is a "life peer created by Charles III") and lists of German cities to a question about Sarajevo. That over-broad context cost three records that other runs passed — Q045, Q080 (aspects 0.80 → 0.60) and Q009 (0.67 → 0.33) — which is exactly the "where it hurt" the worksheet asks about. Two honest caveats: G08's chunk attribution is 0.0 (the model knew Clinton closed-book, so the graph's contribution is grounding and citation, not knowledge), and the category matcher is lexical — it matched "Time loop films" for Q072 and "La-La Land Records artists" for Q019 on single shared words, harmless here only because those categories are tiny.

The graph retriever needed three fixes after its first free pass, all in scoring rather than data: seeds by distinct article rather than by chunk (Sarajevo had been crowded out by three Dunedin chunks); matched categories ranked by query overlap before BM25 (BM25 preferred "20th-century presidents in Africa", one member, over the U.S. category, eleven members, and the top-5 cut dropped both U.S. categories); and a candidate's score as its best relation plus a capped bonus rather than a sum over every shared category (Jimmy Carter's twelve incidental shared categories had outranked Harvard's one relevant edge, 25.0 to 3.0). The diagnostic that exposed these is `scratchpad/diagnose_graph.py`; the before/after is `retrieval_graph_20260921_182724.json` vs the run reported here.

### 4. The one record every advanced run lost (Q049)

`95th_Academy_Awards.html` is retrieved by all three advanced configurations, but its matching chunk is the lead, and the winners table sits three chunks lower — outside a capped parent. The baseline passed only because it handed over the whole 177k-character article. Decomposition's sub-query "95th Academy Awards Best Actor winner" still ranked the winners chunk below the category page "Academy Award for Best Actor". The diagnostic puts that chunk at fused rank 24: a deeper cut (`--k 12`) or a reranker would recover it. This is the expected cost of capped parents, and it bought a 200k-character saving on every other record.

### 5. Generation errors on perfectly retrieved evidence (G16 under the chunker, Q014 everywhere)

G16's chunker answer began "No." with both supporting dates present and both aspects credited — the same polarity inversion seen in the closed-book answers; decomposition and the graph answered "Yes" from equivalent evidence. Q014 has all three golden quotes in context under C, D and G and still fails on the first-round elimination (Cortina d'Ampezzo instead of Berchtesgaden — a misread of the markdown vote table), scoring 0.33–0.67 on aspects. No retriever change can fix these; they belong in the write-up as a generation limitation.

### 6. A correct answer the golden record does not accept (Q072)

The chunker answered "Avatar, \$2.924 billion" — what the full corpus says. The golden record, written for the Titanic-centric subset, expects Titanic's history plus a staleness caveat. Recommend widening the expected answer for the full corpus (keeping the caveat aspect, which the answer genuinely lacks). Not changed during these runs so the four configurations stayed on identical grading.

### 7. Out of reach for all four (G10, Q049 winners, Q003 under C/G)

G10 needs "English film directors" ∩ Oscar-winning films; the category matcher preferred seven "Films that won the Best X Academy Award" categories over `English film directors` (4 members), and decomposition retrieved Mendes but not Nolan. The answer requires an *attribute constraint* (nationality) on top of a category walk, which neither the lexical matcher nor a one-hop expansion expresses. A real fix would be intersecting matched categories by *kind* (person-categories ∩ award-categories) rather than by count.

### 8. Cost and latency

Cost per record: \$0.18 (B) → \$0.02–0.04 (C, D, G). Latency is flat across runs because every run is paced at ≥3.1 s between LLM calls to stay under the account's 20 requests/minute limit (throttle ≈5–6 s per record); decomposition adds one call per record (+4 s). Unthrottled, all three advanced runs would be faster than the baseline: their prompts are 5–8× smaller.

## Judge & Metric Reliability Notes

-   **Binary correctness understates the advanced runs.** Many answers are two-thirds right (Q005 under C/D, Q014, Q045, Q009). Graded correctness and aspect coverage are the fairer headline: 0.47/0.55 (B) → 0.66/0.67 (G).
-   `refusal_outcome: hallucinated` **is noise on answerable records.** It flags grounded, faithful, partially complete answers (Q005 under C, Q080) in every run; counts range 2–7 across runs on near-identical behaviour.
-   **Faithfulness fails on honest "the documents do not say" statements** (Q049 under C, several refusal-flavoured answers) — the recurring quirk; six of the seven chunker faithfulness fails are of this kind.
-   **Chunk attribution is the tie-breaker between decomposition and the graph** on the bridge records, as the suite intended: decomposition's sub-queries supply the missing entity from memory (attribution 0.48 overall), the graph supplies it structurally — though on G08 specifically the model also knew the answer (attribution 0.0), so the graph's win there is grounding, not reach.
-   **Evidence recall is a lower bound on answerability.** G16 scores 0.00 under C and D because the golden sentences are in "Early life", yet the lead chunk carries both facts and D answered correctly from it.
-   **Quote fidelity is genuinely stricter under chunking** (1.00 under C vs 0.67 under B): the model can only quote what it saw, and every chunker quotation matched.
-   **Judge variance is about one verdict per run.** Q045/Q009 dropping to "partial" under D and G on answers that read as complete is within that band; do not over-interpret single-record swings.

## Recommendations, Ranked

1.  **Adopt a combined pipeline for the final system:** chunk index with `lead_section` parents, decomposition for multi-entity questions, graph expansion for relational ones — and report the union. On this suite at least one of C, D or G passes 12 of 17 records (Q006, Q045, Q080, Q003, Q005, Q009, G06, G07, G15, G16, G08, G13), versus 7 for the baseline; the per-record table shows the techniques' wins barely overlap, which is the argument for routing rather than picking one.
2.  **Fix the two golden records** (Q072 Avatar framing; explicit "yes" aspect on G16) and re-validate before any final run.
3.  **Try** `--k 12` **(free)** to recover Q049's winners chunk and the other twenty golden-quote chunks at fused ranks 10–110, before adding a reranker.
4.  **Constrain graph expansion for precision:** skip categories with a single shared query word, cap context articles per relation kind, and prefer person∩award style category intersections by category *kind* — this is what G10 needs and what would have spared Q080/Q009.
5.  **Report the generation-side failures (G16 polarity, Q014 table misread) and the parametric-bridge effect of decomposition** as limitations; both are measurable with the existing metrics and both cap what any retriever change can achieve.
6.  **Keep the retrieval-only mode as the first step of every experiment.** Three of the four graph problems and both matcher bugs were found and fixed for free before a single judge call.

## Worksheet mapping (Checkpoint 4.1, Step 6)

1.  **System overview** — Wikipedia Retrieval Engine; 2.1 baseline = whole-article BM25 + vector fusion, `TOP_K=3` (`evaluation_baseline_4.1_consolidated_report.md`).
2.  **Failure diagnosis** — whole-article dilution (G16: three wrong monarchs), multi-entity queries (Q003/Q005/Q014: zero recall), unnamed second-hop entities (G08/G13). Evidence: baseline strict recall 6%, mean context 225k characters.
3.  **Data redesign** — nodes: `article`, `category`; edges: `links_to`, `in_category`, typed infobox edges (`education`, `mother`, `preceded_by`, `succeeded_by`, `cinematography`, …) plus raw infobox properties; built by `process_wikipedia_with_nodes_and_edges()` (28,054 nodes, 56,761 edges).
4.  **Advanced retrieval implemented** — `--retriever decompose` (Lab 4.1) and `--retriever graph` (Lab 4.2) in `capstone_checkpoint_4_1_advanced_retrieval_solution.py`; primary vs context labelling in the prompt (`[file] (context: 'Education' of Barack_Obama.html)`); log evidence in `eval_mini_*.log`.
5.  **Comparative evaluation** — this report: same 17 records, matched document counts reported via `source_recall_at_3_articles`, before/after per record and per group.
6.  **Analysis & reflection** — findings \#1–\#8: where it helped (G08/G13/G16/Q003/Q005), where it hurt (Q049, Q045/Q080/Q009 under the graph, attribution under decomposition), cost/latency, limitations (G10, generation errors, lexical category matching, rate pacing).

*Generated from the four 17-record runs listed above, all graded against* `mini-4.1-test-suite.json` *as of 2026-09-21. Metric definitions:* `Checkpoint 3.1/metric_documentation.md` *and the header of* `capstone_checkpoint_4_1_advanced_retrieval_solution.py`*.*
