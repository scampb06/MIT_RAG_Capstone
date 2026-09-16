| Metric | Range | Expected | Layer | Needs reference? | Deterministic or LLM | Failure it catches |
|---|---|---|---|---|---|---|
| source_recall_at_k | 0 to 1 | 1 | Retrieval | Yes | Deterministic | Retrieval misses a required document |
| source_precision_at_k | 0 to 1 | 1 | Retrieval | Yes | Deterministic | Context dilution - noise in the top-k |
| source_recall_strict / all_required_present | 0 or 1 | 1 | Retrieval | Yes | Deterministic | Any single required document missing |
| source_hit_at_k | 0 or 1 | 1 | Retrieval | Yes | Deterministic | Complete retrieval miss (zero required docs found) |
| correctness / graded_correctness | Pass/Fail; 0 to 1 (4 levels) | Pass; 1 (complete) | Generation | Yes | LLM judge | Wrong answer despite a fluent response |
| aspect_coverage | 0 to 1 | 1 | Generation | Yes | LLM judge | Missing sub-claims inside an otherwise-correct answer |
| answer_relevance | Pass/Fail | Pass | Generation | No | LLM judge | Off-topic drift, ignoring the question asked |
| faithfulness | Pass/Fail | Pass | Generation | No | LLM judge (claim-level) | Whole-answer fabrication (any unsupported claim) |
| graded_groundedness_score | 0 to 1 (null if no claims) | 1 | Generation | No | LLM judge (claim-level) | Partial fabrication a pass/fail gate would hide |
| citation_support_rate | 0 to 1 (null if no citations) | 1 | Generation | No | LLM judge (claim-level) | Citation naming the right file next to the wrong claim |
| chunk_attribution_score | 0 to 1 (null if no grounded claims) | 1 | Generation | No | LLM judge + closed-book ablation | Correct-sounding answer from parametric memory, retrieval unused |
| citation_precision | 0 to 1 (null if no citations) | 1 | Generation | Yes | Deterministic | Citation naming a source outside the expected set |
| unsupported_citation_rate | 0 to 1 (null if no citations) | 0 | Generation | No | Deterministic | Citation naming a document that was never retrieved |
| quote_fidelity_rate | 0 to 1 (null if no quotes) | 1 | Generation | No | Deterministic | Fabricated or altered verbatim quotation |
| quote_attribution_accuracy | 0 to 1 (null if no quotes) | 1 | Generation | No | Deterministic | Verbatim quote attributed to the wrong source |
| refusal_outcome | 1 of 3 categories | appropriate_refusal | Safety | Yes | LLM judge | Over-refusal, or hallucinating instead of declining |
| answer_latency_seconds / total_latency_seconds | 0 to ∞ (seconds) | as low as possible | Operational | No | Deterministic | Slow responses, tail latency |
| estimated_cost_usd | 0 to ∞ USD (null if cost rates unset) | as low as possible | Operational | No | Deterministic | Token / retrieval-depth cost blowout |