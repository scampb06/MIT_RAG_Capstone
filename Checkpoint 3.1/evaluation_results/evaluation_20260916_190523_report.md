# Checkpoint 3.1 Evaluation Report — Same 18 Questions, Full Corpus

**Source results:** `evaluation_results/evaluation_20260916_190523.json`
**Golden suite:** `golden_suite.subset.wholecorpus.json` (the same 18-record stratified subset as the first report, re-validated for the full corpus)
**Corpus:** the full Wikipedia corpus (2,421 articles) — **not** the 60-file film/Oscars subset
**Retriever:** same BM25 + vector hybrid, `TOP_K=3`, whole-article documents

This is the most directly comparable run you have: **identical 18 questions, identical expected answers, only the corpus changed.** Any difference in outcome is attributable to retrieval competing against 2,361 additional, mostly off-topic documents.

## Executive Summary

| Metric | This run (full corpus) | Same 18 Qs, 60-file corpus (first report) |
|---|---|---|
| Binary correctness (pass) | 12/18 (66.7%) | 14/18 (77.8%) |
| Faithfulness (pass) | 15/18 (83.3%) | 15/18 (83.3%) |
| Answer relevance (pass) | 18/18 (100%) | 18/18 (100%) |
| Mean aspect coverage | 84.2% | 87.7% |
| Mean graded groundedness | 98.4% | 94.4% |
| Mean citation support rate | 98.2% | 98.8% |
| Mean chunk attribution score | 51.9% | 61.6% |
| **Strict source recall@3 (all required retrieved)** | **9/18 (50.0%)** | **12/18 (66.7%)** |
| Mean source recall@3 | 66.7% | 77.8% |
| Mean source precision@3 | 53.7% | 51.9% |
| **`refusal_outcome: hallucinated`** | **9/18 (50%)** | 2/18 (11%) |
| Total cost (18 records) | $2.97 (~$0.165/record) | $2.66 (~$0.148/record) |

**Headline read:** correctness dropped and strict recall fell from 66.7% to 50.0% — three questions that retrieved the right documents on the 60-file corpus (Q072, Q019, Q080) now miss at least one required document purely because of competition from unrelated full-corpus articles. Interestingly, mean precision@3 barely moved (53.7% vs 51.9%) — unlike the more topically-diverse `golden_suite_2.1.json` run, this suite's questions stay clustered around film/Oscars, so the extra candidate pool still tends to surface *other* film-related pages rather than completely unrelated ones. The real cost here is landing on the wrong specific document, not landing on a random one.

The most striking single number is the **`hallucinated` refusal-outcome jumping from 2 to 9 records** — investigated below, and it's a mixed bag: some are genuine catches, several look like judge noise.

---

## Per-Record Results

| ID | Question (short) | Correctness | Faithful | Strict Recall | Precision@3 | Refusal Outcome | Changed from 60-file run? |
|---|---|---|---|---|---|---|---|
| Q036 | Sinners nomination record | pass | pass | ✓ | 67% | hallucinated | recall held |
| Q072 | Highest-grossing film | **fail** | pass | ✗ | 33% | hallucinated | **regressed** (was pass/✓) |
| Q079 | James Cameron's Oscar count | **fail** | pass | ✓ | 67% | hallucinated | new record (was unanswerable) |
| Q098 | King Kong (ambiguous) | **fail** | pass | ✗ | 33% | hallucinated | recall held (already ✗) |
| Q100 | Whiplash false premise | **fail** | pass | ✓ | 100% | appropriate_refusal | recall held |
| Q091 | Ben Kingsley career | pass | pass | ✓ | 33% | hallucinated | recall held |
| Q002 | Titanic noms vs. wins | pass | pass | ✗ | 33% | n/a | recall held (already ✗) |
| Q006 | John Snow / cholera | pass | pass | ✗ | 0% | hallucinated | recall held (already ✗) |
| Q019 | La La Land director's start | **fail** | pass | ✗ | 33% | n/a | **regressed** (was pass/✓) |
| Q042 | Crash Best Picture reassessment | pass | pass | ✓ | 100% | n/a | recall held |
| Q045 | Brokeback vs. La La Land | pass | pass | ✗ | 100% | n/a | recall held (already ✗) |
| Q049 | 95th ceremony Best Actor | pass | pass | ✗ | 33% | n/a | recall held (already ✗) |
| Q058 | Godfather II / De Niro | **fail** | pass | ✓ | 100% | hallucinated | recall held, answer newly incomplete |
| Q067 | Whiplash Sundance | pass | **fail** | ✓ | 67% | n/a | recall held, new faithfulness dip |
| Q074 | Spielberg / Schindler's List | pass | pass | ✓ | 67% | n/a | recall held |
| Q080 | Anthony Minghella | pass | **fail** | ✗ | 33% | n/a | **regressed** (was pass/✓/pass) |
| Q086 | Judd Hirsch nomination gap | pass | pass | ✗ | 33% | hallucinated | recall held (already ✗) |
| Q094 | Costner Horizon comparison | pass | **fail** | ✓ | 33% | hallucinated | recall held, new faithfulness dip |

---

## Top Failures — Analysis

### 1. Retrieval regressed on three questions that worked fine on the smaller corpus
**Q072, Q019, and Q080 all correctly retrieved every required document on the 60-file corpus and now miss at least one**, purely from competition with unrelated full-corpus articles:
- **Q072** ("highest-grossing film of all time"): retrieved `Harry_Potter_(film_series).html` and `List_of_highest-paid_film_actors.html` instead of `Titanic_(1997_film).html`. The response confidently states *"Avatar became the highest-grossing film of all time"* with no caveat and no mention of Titanic at all — a wrong, uncaveated answer where the 60-file run gave a correct, properly-hedged one.
- **Q019** (La La Land director's start): missed `Damien_Chazelle.html` entirely (got `Titanic_(1997_film).html` and `New_Girl.html` instead), losing the Currier House roommate detail that only lives in the biography article.
- **Q080** (Anthony Minghella): retrieved `David_Fincher.html` and `Cillian_Murphy.html` as noise alongside the correct `Anthony_Minghella.html`, and lost `Academy_Award_for_Best_Picture.html` — the specific source for the producer-limit exception fact.

**Implication:** this is the concrete, reproducible cost of scaling the corpus for a system that was already precision-limited. These aren't edge cases — they're straightforward single- or dual-entity lookups that only failed because thousands of superficially plausible alternative documents now exist to compete with the right one.

### 2. The `hallucinated` refusal tag jumped from 2 to 9 records — and it's a mixed signal
Half the suite now carries `refusal_outcome: hallucinated`. Breaking down all nine:
- **Three are genuine, correct catches**: Q036 (missing the required "may be out of date" staleness caveat — the binary `correctness` judge missed this too, scoring it "complete"), Q072 (the wrong-answer case above), Q098 (an incomplete disambiguation that only named the 2005 King Kong film and never asked the user to specify).
- **One is the recurring `correctness`/`aspect_coverage` disagreement** flagged in the first report: Q079 scores `aspect_coverage: 1.0` but `correctness: fail`, because the response drops the "(shared with Jon Landau)" / "(shared with Conrad Buff and Richard A. Harris)" attribution detail — a real gap, but "hallucinated" overstates it.
- **Three show no other quality problem at all**: Q091, Q006, and Q086 all score `correctness: complete`, `faithfulness: pass`, and full aspect coverage, yet still carry `refusal_outcome: hallucinated` with no discernible defect in the response.

**Q091 is the standout.** This is the *second independent run* — different corpus, different retrieved documents — where this exact question ("Tell me about Ben Kingsley's career") gets flagged `hallucinated` despite a complete, accurate, fully-cited answer. That's no longer a one-off; it's a specific, reproducible false-positive tied to something about this question or the Ben Kingsley article, not random judge variance.

**Implication:** treat `refusal_outcome: hallucinated` as a prompt to look closer, not as a verdict. At minimum, don't use it as an automated CI gate without first averaging over repeated judge calls per the guide's §9 recommendation — this run shows real volatility in exactly the way that guidance warns about.

### 3. Real incompleteness where retrieval partly succeeded (Q058)
`The_Godfather_Part_II.html`, `The_Godfather.html`, and `List_of_Academy_Award_records.html` were all retrieved — a good set — but the response stops after establishing De Niro's Best Supporting Actor win and the Italian-language detail, never mentioning that Brando won Best Actor for the *same character* in the first film (even though `The_Godfather.html` was sitting right there in context). `correctness: fail` here is accurate, not a judge artifact — the model simply didn't finish the answer despite having the evidence available.

### 4. Genuine synthesis-overreach, consistent across runs (Q094)
The claim *"Dances With Wolves established a much more celebrated reputation"* was marked `grounded: false` — it's the model's own evaluative comparison, not something either source states. This is the same behavior flagged for this exact question in the first report (there it showed up as a `citation_support_rate` miss; here the stricter `faithfulness` check catches it directly). Worth noting as a consistent trait of how the model handles "compare X and Y" personal-decision-style questions: it tends to append an unsupported editorial judgment at the end.

---

## Judge & Metric Reliability Notes

- **The "documents don't say X" groundedness quirk recurs again** (Q080's ungrounded claim is exactly this pattern: *"The documents do not say what specifically happened at the Oscars after his death beyond that posthumous nomination"* — an accurate statement about absence, marked ungrounded because no chunk states an absence). Third report in a row to hit this; it's a stable, fixable issue in `judge_claims()`'s prompt, not noise.
- **`correctness` vs. `aspect_coverage` disagreement recurs** (Q079, as above) — same pattern flagged in both prior reports.
- **Precision@3 not degrading much is itself informative.** Compare this suite (53.7%, essentially flat vs. the 60-file run) against `golden_suite_2.1.json`'s full-corpus run (31.1%, down from a 52% baseline on a different, non-film corpus subset). The difference is topical clustering: this suite's questions are all film/Oscar-flavored, so even "wrong" retrievals on the full corpus tend to land on other film/Oscar pages that still count as partially relevant. A general-knowledge query has no such safety net. This suggests **retrieval degradation at scale depends heavily on how topically isolated the corpus's minority domain is** — a useful thing to know if this system is meant to serve one narrow topic within a broader indexed corpus.

---

## Recommendations, Ranked

1. **Chunking and/or a deeper reranked candidate pool remain the top priority** — this run adds three concrete before/after regressions (Q072, Q019, Q080) to the case made in the first report, all caused purely by scale.
2. **Don't trust `refusal_outcome: hallucinated` as a pass/fail signal without a second look**, especially for Q091-shaped questions (broad "tell me about X's career" prompts) — this run's 50% hallucination rate materially overstates how many responses actually have something wrong with them; roughly a third do not.
3. **Fix the self-referential absence-claim handling in `judge_claims()`** — this is now the most consistently recurring metric defect across all three reports on this codebase, not a one-off.
4. **Watch for silent incompleteness when retrieval partially succeeds** (Q058) — having the right documents in context doesn't guarantee the model uses all of them; this may be worth a targeted prompt tweak encouraging the model to check whether every retrieved document contributed something to the answer before finishing.
5. **When scoping future corpus expansions, expect precision to hold up better for domain-clustered query sets than for general ones** — plan retrieval-quality budgets accordingly rather than assuming a uniform degradation curve.

---

*Generated from `evaluation_20260916_190523.json` (18-record run of `golden_suite.subset.wholecorpus.json` against the full Wikipedia corpus). Comparisons drawn from the first report (`evaluation_20260916_154603_report.md`, same 18 questions, 60-file corpus) and the second (`evaluation_20260916_183901_report.md`, `golden_suite_2.1.json`, full corpus). Full metric definitions are in `metric_documentation.md` and `Module 3/rag_evaluation_guide.md`.*
