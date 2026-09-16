# Golden Test Suite Generation Prompt

**Purpose:** Instruct an advanced LLM with full corpus access to generate a 100-query
golden evaluation suite for a Wikipedia RAG chatbot, stratified by the Singer/Lemmerich
reader-taxonomy dimensions.

**How to use:** Paste everything below the horizontal rule into the generating model,
with the corpus mounted or attached. Then run `validate_golden_suite.py` on the output.

---

## ROLE

You are a retrieval-evaluation engineer constructing a golden test suite for a
retrieval-augmented generation (RAG) system. Your output will be used to measure
retrieval recall, answer faithfulness, citation accuracy, and refusal behavior.
Precision matters more than fluency. A single fabricated quotation or wrong filename
invalidates the record it appears in.

## CORPUS

You have access to a corpus of approximately 7,000 Wikipedia articles stored as
individual HTML files. Topical range is broad and general-encyclopedic, including but
not limited to:

- Biography: scientists, philosophers, athletes, artists, political figures
  (e.g. Albert Einstein, Aristotle, Andy Roddick)
- Geography and earth science (e.g. Arctic Ocean)
- Film, television, and awards (e.g. Avatar (2009), Academy Awards)
- Sporting events and competitions
- History, treaties, and diplomacy (e.g. Anglo-Dutch Treaty of 1814)
- Medicine, psychology, and health topics (e.g. Asperger syndrome)
- Science, technology, and mathematics

**You must read the actual files.** Every factual claim, every quotation, and every
filename in your output must be verified against the HTML on disk. Do not rely on what
you remember about these topics from training. If your memory and the corpus disagree,
the corpus wins. If a fact you want to use is not in the corpus, discard the question
and write a different one.

## THE TAXONOMY

Stratify the suite along four axes. The first three come from the Singer, Lemmerich,
West, Zia, Wulczyn, Strohmaier, and Leskovec reader studies of Wikipedia
("Why We Read Wikipedia", WWW 2017; "Why the World Reads Wikipedia", WSDM 2019).
The fourth is a structural axis for retrieval evaluation.

### Axis 1 — Information need (controls retrieval depth)

**`fact_lookup`** — The reader wants one specific fact or a quick answer. Answerable
from a single passage, often a single sentence. Typically a date, number, name, title,
place, or short attribute. The correct answer is short and checkable.

*Example shape:* "What year did X win Y?" / "Who directed Z?" / "How deep is W?"

**`overview`** — The reader wants a general orientation to a topic. Requires
synthesizing several sections of one article (or occasionally two closely related
articles). The answer is a paragraph, not a sentence, and a correct answer must cover
multiple distinct aspects rather than one fact.

*Example shape:* "What is X known for?" / "Give me the background to Y." /
"What happened at Z and why did it matter?"

**`in_depth`** — The reader wants detailed understanding, comparison, causation, or
context that no single article states outright. Requires genuine synthesis, usually
across two or more documents. The answer must combine facts that appear in different
places; a system that retrieves only one document cannot answer correctly.

*Example shape:* "How did X's approach differ from Y's?" /
"What connects the events of A to the outcome in B?" /
"Trace the development of C across its major phases."

### Axis 2 — Motivation / trigger (controls register and phrasing)

This axis does **not** change what the answer is. It changes how the question is
*worded*. Write each query in the voice implied by its motivation. This stress-tests
query understanding, not just retrieval.

| Motivation | Voice and phrasing guidance |
|---|---|
| `work_or_school` | Formal, complete, well-specified. Full entity names, explicit scope. Often "explain", "describe", "compare", "what were the causes of". Reads like an assignment prompt. |
| `conversation` | Terse, colloquial, often a sentence fragment. Someone settling an argument or checking a claim mid-discussion. May be an incomplete sentence. "wait, was X actually the first to..." |
| `current_event` | Framed around recency or ongoing relevance. Note: the corpus is static, so these often become temporal-boundary tests. Ask about the most recent state the corpus records, not about today. |
| `media_reference` | The reader encountered the topic in a film, book, show, or song and wants the underlying facts. Often approaches the topic sideways, via the depiction rather than the subject. |
| `personal_decision` | Comparative and evaluative framing. The reader is weighing something — where to travel, what to read, which to choose. Asks about tradeoffs, differences, suitability. Must still be answerable from corpus facts, not opinion. |
| `intrinsic_learning` | Curiosity-driven, open, no external pressure. "I've always wondered..." Often broad and unhurried. |
| `bored_random` | Exploratory, loosely specified, sometimes tangential or trivia-flavored. May chain two unrelated interests. |

### Axis 3 — Prior familiarity (controls entity-mention style)

**`unfamiliar`** — The reader is meeting the topic for the first time. They name the
entity explicitly and completely, because the name is all they have. Retrieval is
comparatively easy: the query string contains the target article's title.

*Example:* "Who was Aristotle and what did he contribute to philosophy?"

**`familiar`** — The reader already knows the topic and is filling a specific gap.
This produces the **hard retrieval case**, and you must exploit it deliberately:

- Use partial or informal descriptors instead of the full title ("the Greek who taught
  Alexander" rather than "Aristotle").
- Use presupposition — assume background rather than stating it ("Why did he break with
  Plato on the forms?").
- Ask about a sub-topic using internal jargon that appears in the article body but not
  in its title (e.g. asking about *phronesis*, *eudaimonia*, or the Peripatetic school).
- Occasionally omit the entity name entirely where context makes it recoverable.

At least **15** of your `familiar` queries must omit the target article's exact title
from the query string. These are your lexical-retrieval stress tests: BM25 will fail on
them, and only semantic or hybrid retrieval should succeed.

### Axis 4 — Scope (structural)

**`single_document`** — All supporting evidence comes from one file.

**`multi_document`** — Correct answer requires evidence from two or more distinct files.
The question must be genuinely unanswerable from any one document alone. Do not write a
question that merely *mentions* two topics; write one where the answer needs facts from
both.

## REQUIRED DISTRIBUTION

Produce exactly **100** queries meeting these counts.

### Information need
| Level | Count |
|---|---|
| `fact_lookup` | 35 |
| `overview` | 33 |
| `in_depth` | 32 |

### Motivation
| Level | Count |
|---|---|
| `conversation` | 24 |
| `work_or_school` | 18 |
| `current_event` | 17 |
| `personal_decision` | 13 |
| `intrinsic_learning` | 12 |
| `media_reference` | 10 |
| `bored_random` | 6 |

### Prior familiarity
| Level | Count |
|---|---|
| `familiar` | 55 |
| `unfamiliar` | 45 |

### Scope
| Level | Count |
|---|---|
| `multi_document` | 40 (minimum) |
| `single_document` | 60 (maximum) |

**Cross-cutting requirements:**

- The 40 `multi_document` queries must include all 32 `in_depth` queries plus at least
  8 drawn from `overview` or `fact_lookup` (a fact lookup requiring two documents —
  such as comparing two figures' dates — is a valid and useful case).
- Distribute across at least **60 distinct primary articles**. Do not cluster the suite
  on a handful of famous topics.
- Cover every major topical area listed in the CORPUS section with at least 5 queries.
- Vary answer length: some expected answers should be a few words, some a full paragraph.

## ADVERSARIAL SLICE

**10 of the 100 queries** must be designed to fail safely. These sit outside the reader
taxonomy — the original surveys only sampled readers who found what they wanted, so the
taxonomy has no vocabulary for failed retrieval. Since hallucination reduction is a
primary goal of the system under test, a suite with no unanswerable questions cannot
measure the thing that matters most.

Distribute as follows, and set `adversarial_kind` on each:

- **`unanswerable_from_corpus`** (3) — A reasonable, well-formed question about a topic
  the corpus covers, asking for a detail the corpus does not contain. Set
  `answerable: false` and leave `supporting_quotes` **empty**. The expected behavior is
  an explicit statement that the information is not available in the source material.

- **`ambiguous_entity`** (3) — A query naming an entity that matches two or more corpus
  articles, or a name whose referent is genuinely unclear. The expected behavior is a
  clarifying question, or an answer that explicitly disambiguates and addresses each
  candidate. Set `answerable: true` and cite all candidate articles in
  `relevant_files`.

- **`false_premise`** (2) — A query that embeds a factual error contradicted by the
  corpus ("Why did Einstein refuse the 1921 Nobel Prize?"). Expected behavior is to
  correct the premise before, or instead of, answering. Set `answerable: false` unless
  a corrected version of the question is answerable, in which case set `true` and
  supply quotes that establish the correction.

- **`temporally_stale`** (2) — A query asking for a current or present-day value where
  the corpus holds only a snapshot ("What is the current world record for...?").
  Expected behavior is to answer with the corpus value while explicitly flagging that
  it reflects the source's date and may be out of date. Set `answerable: true` and
  supply the quote carrying the dated figure.

Every adversarial record must carry a non-empty `expected_behavior` string describing
what a correct system does. Adversarial queries still receive full taxonomy labels and
count toward the distribution quotas above.

## QUOTATION RULES

The system under test must supply direct quotations, so quote fidelity in this suite is
non-negotiable.

1. **Verbatim.** Each `supporting_quotes[].text` must appear character-for-character in
   the source file after HTML tags are stripped and entities are decoded. Do not
   paraphrase, do not correct grammar, do not fix the source's spelling, do not
   normalize its capitalization.
2. **Strip markup, preserve wording.** Remove tags and decode entities (`&amp;` → `&`,
   `&#39;` → `'`, `&ndash;` → the dash character). Do not otherwise alter the text.
3. **Drop reference markers.** Wikipedia prose carries superscript citation markers that
   render as `[1]`, `[2]`, `[citation needed]`. Exclude these from your quotes, and do
   not let them split a quote mid-sentence.
4. **Prefer prose.** Quote from body paragraphs. Avoid infobox cells, table rows,
   navigation boxes, and image captions — their text interleaves unpredictably once
   markup is stripped, and quotes drawn from them frequently fail verbatim matching.
5. **Length.** Each quote should be 25–300 characters: long enough to stand as evidence,
   short enough to be a genuine excerpt.
6. **Sufficiency.** The quotes attached to a record must, on their own, support the
   entire `expected_answer`. If part of your answer is not covered by a quote, either
   add a quote or cut that part of the answer.
7. **Coverage for multi-document records.** A `multi_document` record must carry at least
   one quote from at least two different files.
8. **Filenames must be real.** Every `source_file` and every `relevant_files` entry must
   be an exact filename present in the corpus, including extension and capitalization.
   Every `source_file` must also appear in that record's `relevant_files`.

## OUTPUT SCHEMA

Return a single JSON object. No prose, no markdown fences, no commentary before or
after. Top-level key `queries` holds an array of exactly 100 objects.

```json
{
  "queries": [
    {
      "id": "Q001",
      "query": "In what year did Einstein receive the Nobel Prize in Physics?",
      "information_need": "fact_lookup",
      "motivation": "conversation",
      "prior_familiarity": "familiar",
      "scope": "single_document",
      "answerable": true,
      "adversarial_kind": null,
      "expected_behavior": null,
      "expected_answer": "1921. The prize was awarded for his discovery of the law of the photoelectric effect rather than for relativity.",
      "required_aspects": [
        "Einstein received the Nobel Prize in Physics in 1921.",
        "The prize recognized his discovery of the law of the photoelectric effect rather than relativity."
      ],
      "supporting_quotes": [
        {
          "text": "In 1921 he received the Nobel Prize in Physics for his services to theoretical physics, and especially for his discovery of the law of the photoelectric effect.",
          "source_file": "Albert_Einstein.html"
        }
      ],
      "relevant_files": ["Albert_Einstein.html"],
      "difficulty_notes": "Common misconception that the prize was for relativity; tests whether the system reads the stated rationale rather than defaulting to prior assumption."
    }
  ]
}
```

### Field specifications

| Field | Type | Rule |
|---|---|---|
| `id` | string | `Q001`–`Q100`, unique, zero-padded. |
| `query` | string | The question as a reader would type it, in the voice of its `motivation`. |
| `information_need` | enum | `fact_lookup` \| `overview` \| `in_depth` |
| `motivation` | enum | `work_or_school` \| `personal_decision` \| `current_event` \| `media_reference` \| `conversation` \| `bored_random` \| `intrinsic_learning` \| `other` |
| `prior_familiarity` | enum | `familiar` \| `unfamiliar` |
| `scope` | enum | `single_document` \| `multi_document` |
| `answerable` | boolean | `false` only for adversarial records the system should decline. |
| `adversarial_kind` | enum or null | `unanswerable_from_corpus` \| `ambiguous_entity` \| `false_premise` \| `temporally_stale` \| `null` |
| `expected_behavior` | string or null | Required and non-empty when `adversarial_kind` is set; otherwise `null`. |
| `expected_answer` | string | The reference answer, grounded entirely in the quotes. |
| `required_aspects` | array of strings | Atomic factual claims required for a complete answer. Every aspect must be supported by `supporting_quotes`. |
| `supporting_quotes` | array | Objects with `text` and `source_file`. Empty only for `unanswerable_from_corpus`. |
| `relevant_files` | array of strings | Ranked most- to least-relevant. Must be empty only when `answerable` is `false` and nothing in the corpus is relevant. |
| `difficulty_notes` | string | Why this query is a useful test — what it stresses, what a weak system gets wrong. |

## SELF-CHECK BEFORE OUTPUT

Run this checklist and correct any failures before emitting JSON. Do not report the
checklist; just satisfy it.

1. Exactly 100 records; ids `Q001`–`Q100`, no duplicates, no gaps.
2. Every distribution table above matches exactly. Count them; do not estimate.
3. At least 40 records have `scope: "multi_document"`, and each cites 2+ distinct files
   in `relevant_files` and draws quotes from 2+ distinct files.
4. All 32 `in_depth` records are `multi_document`.
5. At least 15 `familiar` records omit the target article's exact title from `query`.
6. Exactly 10 records carry an `adversarial_kind`, split 3/3/2/2 as specified, each with
   a non-empty `expected_behavior`.
7. Every `unanswerable_from_corpus` record has `answerable: false` and an empty
   `supporting_quotes` array.
8. Every `answerable: false` record has an `adversarial_kind` set.
9. Every filename referenced exists in the corpus, spelled and capitalized exactly.
10. Every `source_file` also appears in the same record's `relevant_files`.
11. Every quote was copied from the file you actually opened, is 25–300 characters, and
    contains no reference markers or stray markup.
12. Every `expected_answer` is fully supported by that record's quotes — no claim
    appears in the answer that the quotes do not establish.
13. Every `required_aspects` entry is atomic, appears in or is entailed by the
  `expected_answer`, and is fully supported by the attached quotes.
14. At least 60 distinct primary articles are represented across the suite.
15. No two queries are near-paraphrases of each other.
16. Output is valid JSON, parseable, with no text outside the JSON object.
