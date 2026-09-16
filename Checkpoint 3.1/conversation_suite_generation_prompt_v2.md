# Conversational Test Suite Generation Prompt

**Purpose:** Instruct an advanced LLM with full corpus access to generate five
multi-turn conversational sessions (72 turns total) that stress-test chat-context
handling in a Wikipedia RAG chatbot.

**Companion to:** `golden_suite_generation_prompt.md` (single-turn suite).
**Validated by:** `validate_conversation_suite.py`.

**How to use:** Paste everything below the horizontal rule into the generating model,
with the corpus mounted or attached. Then run the validator on the output.

---

## ROLE

You are a retrieval-evaluation engineer constructing a multi-turn conversational test
suite for a retrieval-augmented generation (RAG) chatbot. Where a single-turn suite
measures retrieval and faithfulness, this suite measures something different and harder:
whether the system **carries context correctly across turns** — resolving references to
earlier turns, accumulating facts across an unfolding session, shifting retrieval focus
when the topic moves, and refusing to answer when a reference cannot be resolved.

Precision matters more than fluency. A fabricated quotation, a wrong filename, or a
mislabelled dependency invalidates the turn it appears in.

## CORPUS

You have access to a corpus of approximately 7,000 Wikipedia articles stored as
individual HTML files, covering biography, geography, film and awards, sport, history
and diplomacy, medicine and psychology, science and technology.

**You must read the actual files.** Every fact, quotation, and filename must be verified
against the HTML on disk. Do not rely on training memory. If memory and corpus disagree,
the corpus wins.

**Article disjointness requirement.** These sessions must draw on a **different set of
articles** from any single-turn golden suite generated previously. Do not reuse articles
already covered there. If you are unsure whether an article was used, prefer a different
one — the corpus is large enough that this costs you nothing. The purpose is to prevent
the system under test from getting credit for retrieval it memorised during single-turn
tuning.

## THE FIVE USER PROFILES

Each profile crosses two independent research dimensions.

**Session shape** comes from the log-linked behavioural signatures in Singer, Lemmerich,
West, Zia, Sáez-Trumper, Strohmaier and Leskovec's Wikipedia readership studies. Readers
who arrive bored or browsing randomly show long sessions with rapid internal-link
navigation; work-and-school readers show slower, deliberate pacing; readers triggered by
a conversation show short mobile sessions with brief dwell times. This governs turn
count, pacing, and follow-up density.

**Topical trajectory** comes from the curiosity-style architectures identified in the
*Science Advances* study of Wikipedia browsing: the **hunter** pursues goal-directed
gap-filling within a tight topical cluster; the **busybody** hops loosely between weakly
related topics; the **dancer** makes creative leaps across distant domains. This governs
how entities and topics move between turns.

Generate exactly one session per profile.

### 1. `assignment_researcher` — 18 turns, hunter

Anchors: `in_depth` / `work_or_school` / `unfamiliar`.

A student or analyst working through a research question methodically. Formal, complete,
well-specified queries. Full entity names. Stays within a tight topical cluster —
typically one historical event, one scientific field, or one figure and their immediate
context. Later turns build directly on facts established in earlier answers.

*Context stress:* deep accumulation. This session should contain your highest density of
`accumulative` turns. By turn 12 the user should be asking things that require the
system to have retained material from turns 3, 6, and 9 simultaneously.

*Arc guidance:* orientation → narrowing → detailed sub-questions → synthesis and
comparison across everything established.

### 2. `settling_an_argument` — 8 turns, hunter (compressed)

Anchors: `fact_lookup` / `conversation` / `familiar`.

Someone checking a disputed claim mid-discussion. Terse, colloquial, often sentence
fragments. Heavy ellipsis and pronouns. Lowercase, no punctuation, incomplete sentences
are all appropriate — this reader is typing quickly on a phone. Rapid-fire follow-ups
with almost no scene-setting.

*Context stress:* dense pronoun chains with minimal surrounding text to disambiguate
them. "what about her husband" / "and him?" / "which one won first".

*Arc guidance:* a claim is disputed → check it → check the counter-claim → a correction
→ resolution.

### 3. `late_night_wanderer` — 20 turns, busybody

Anchors: `overview` / `bored_random` / mixed familiarity.

Aimless late-night browsing. Loosely specified, exploratory, sometimes trivia-flavoured.
Topics drift by weak association rather than by plan. Threads get abandoned mid-stream
and occasionally resumed much later. This is the longest session, matching the observed
pattern that bored and randomly-browsing readers have the longest sessions.

*Context stress:* topic drift with weak referents, abandoned threads, and long-range
returns. This session should contain your `topic_return` turns with the largest gaps —
a turn referring back eight or ten turns.

*Arc guidance:* start somewhere arbitrary → drift through three or four loosely linked
topics → abandon one → return to an early topic unexpectedly → drift onward.

### 4. `trip_planner` — 14 turns, dancer

Anchors: `overview` / `personal_decision` / mixed familiarity.

Someone weighing options for a trip. Comparative and evaluative framing throughout —
asking about tradeoffs, differences, suitability. Makes creative leaps across domains:
from a city to its cuisine to a historical event that happened there to a film set
there. All answers must still be grounded in corpus facts, never opinion.

*Context stress:* cross-domain leaps combined with comparative accumulation. The user
builds a mental shortlist across turns and then asks the system to compare items
introduced separately, many turns apart.

*Arc guidance:* candidate destinations → a leap into culture or history → back to
practicalities → another leap → a comparison drawing on everything raised.

### 5. `media_prompted_learner` — 12 turns, dancer

Anchors: `fact_lookup` progressing to `in_depth` / `media_reference` / `unfamiliar`.

Someone who encountered a topic in a film, novel, or documentary and is chasing down the
underlying reality. Approaches the subject **sideways** — via the depiction rather than
the subject itself — then progressively gains footing.

*Context stress:* familiarity shifts mid-session. Early turns are `unfamiliar` in
phrasing (naming the entity fully because that's all they have); by the later turns the
user is phrasing questions as a `familiar` reader would, using terms they learned from
the system's own earlier answers. This tests whether the system tracks what it has
already told the user.

*Arc guidance:* "in the film they showed X, was that real?" → correction or confirmation
→ the real underlying topic → deeper detail → a question using vocabulary the system
introduced earlier.

## TURN-LEVEL DIMENSIONS

### Context dependency (three graded levels)

**`standalone`** — Answerable cold, with no conversation history. Your control turns.
Every session must open with one, and should contain two or three more scattered
through. Set `antecedents` and `depends_on_turns` to empty.

**`referential`** — Needs history to resolve a **referring expression** ("his second
wife", "that treaty", "the older one", "there"), but once resolved the retrieval is
ordinary. Must declare `antecedents` and `referring_expressions`.

**`accumulative`** — Needs **facts established in earlier answers**, not merely entity
resolution. "Which of those three was oldest?" requires the system to have retained
three prior answers. This is the hardest tier and the one most systems fail. Must
declare `depends_on_turns` listing every turn whose answer content is required —
normally two or more.

Distribution guidance across all 72 turns: roughly 15 `standalone`, 35 `referential`,
22 `accumulative`. Every session needs at least one of each.

### Retrieval focus and drift

The most common multi-turn failure is **retrieval drift**: the system keeps retrieving
the topic from turn 3 long after the conversation moved on. Naive implementations either
concatenate all history into the retrieval query (retrieving stale documents) or use only
the latest turn (losing the referent). Both fail, differently.

Every turn declares:

- **`expected_retrieval_focus`** — the article(s) the system should now be centring
  retrieval on. Usually one or two filenames; a subset of `relevant_files`.
- **`retrieval_should_shift`** — `true` when this turn's focus introduces at least one
  document not in the previous turn's focus; `false` when the focus stays within the
  previous turn's documents. The first turn of every session is always `true`.

These must be internally consistent: if `retrieval_should_shift` is `true`, the focus
must add a document; if `false`, it must not.

Each session needs at least two shifts, and the longer sessions considerably more.

## ADVERSARIAL TURNS

Seed **two or three per session** — at least 12 across the suite, covering all five
kinds. These test failure modes unique to multi-turn interaction.

**`ambiguous_antecedent`** — A referring expression with two or more genuinely plausible
antecedents in the prior context ("was he the one who resigned?" after two men were
discussed). Must list **2+ entries** in `antecedents`, each a real candidate. Cannot be
`standalone`. Expected behaviour is a clarifying question naming both candidates.

**`unintroduced_referent`** — A referring expression pointing at something never
discussed and not recoverable from the session ("and what did she say about it?" where no
"she" was ever introduced). Set `answerable: false` and leave `antecedents` **empty**.
Expected behaviour is to say the reference cannot be resolved and ask what the user
means — not to guess.

**`user_correction`** — The user corrects a premise or a fact from several turns back
("wait, didn't he win that alone?" when the earlier answer said it was shared). Must
declare `depends_on_turns` naming the turn being corrected. Expected behaviour is to
address the correction against the corpus — confirming the original answer with evidence
if the user is wrong, or acknowledging the correction if right.

**`topic_return`** — The user returns to a topic abandoned several turns earlier ("back
to that treaty — who signed it?"). Must declare `depends_on_turns`. The gap should be
**at least 3 turns**, and in `late_night_wanderer` considerably more. Tests long-range
memory against recency bias.

**`stale_context_trap`** — A turn whose correct answer requires **ignoring** an earlier
topic that shares vocabulary with the current one. For example, after discussing a
person named Cambridge, asking about the city; or after a film adaptation, asking about
the historical event it depicted. Must set `retrieval_should_shift: true`. This is where
history-concatenation strategies visibly break. Expected behaviour describes which
document should be retrieved and which earlier one must be set aside.

## QUOTATION RULES

Identical to the single-turn suite. Every turn's `supporting_quotes` must:

1. Appear **character-for-character** in the source file after HTML tags are stripped and
   entities decoded. No paraphrase, no grammar fixes, no capitalisation changes.
2. Exclude superscript reference markers rendering as `[1]`, `[2]`,
   `[citation needed]`.
3. Come from **body prose**, not infoboxes, tables, navigation boxes, or captions —
   their text interleaves unpredictably once markup is stripped.
4. Run 25–300 characters.
5. Fully support the `expected_answer`. No claim in the answer may lack quote support.
6. Reference real filenames present in the corpus, exact in spelling and capitalisation,
   also listed in that turn's `relevant_files`.

For `unanswerable` turns, `supporting_quotes` is empty.

## OUTPUT SCHEMA

Return a single JSON object. No prose, no markdown fences, no commentary. Top-level key
`sessions` holds an array of exactly 5 session objects.

```json
{
  "sessions": [
    {
      "session_id": "S1",
      "profile": "settling_an_argument",
      "curiosity_style": "hunter",
      "information_need_anchor": "fact_lookup",
      "motivation_anchor": "conversation",
      "prior_familiarity_anchor": "familiar",
      "declared_turn_count": 8,
      "session_arc": "A terse phone-typed exchange settling a dispute about who discovered a given element, moving from one discoverer to their collaborator, then to the element itself, with a mid-session correction and a late return to the element.",
      "turns": [
        {
          "turn_index": 1,
          "user_query": "who actually discovered polonium",
          "context_dependency": "standalone",
          "information_need": "fact_lookup",
          "answerable": true,
          "expected_answer": "Marie and Pierre Curie discovered polonium in 1898.",
          "supporting_quotes": [
            {
              "text": "She discovered the elements polonium and radium with her husband Pierre Curie.",
              "source_file": "Marie_Curie.html"
            }
          ],
          "relevant_files": ["Marie_Curie.html"],
          "expected_retrieval_focus": ["Marie_Curie.html"],
          "retrieval_should_shift": true,
          "antecedents": [],
          "depends_on_turns": [],
          "referring_expressions": [],
          "adversarial_kind": null,
          "expected_behavior": null,
          "difficulty_notes": "Opening control turn; establishes both Curies for later reference."
        },
        {
          "turn_index": 2,
          "user_query": "what about her husband",
          "context_dependency": "referential",
          "information_need": "fact_lookup",
          "answerable": true,
          "expected_answer": "Pierre Curie was a French physicist who shared the 1903 Nobel Prize in Physics with Marie and Henri Becquerel.",
          "supporting_quotes": [
            {
              "text": "He shared the 1903 Nobel Prize in Physics with his wife Marie and with Henri Becquerel.",
              "source_file": "Pierre_Curie.html"
            }
          ],
          "relevant_files": ["Pierre_Curie.html"],
          "expected_retrieval_focus": ["Pierre_Curie.html"],
          "retrieval_should_shift": true,
          "antecedents": [
            {
              "expression": "her husband",
              "entity": "Pierre Curie",
              "introduced_in_turn": 1
            }
          ],
          "depends_on_turns": [],
          "referring_expressions": ["her husband"],
          "adversarial_kind": null,
          "expected_behavior": null,
          "difficulty_notes": "Possessive reference with no name given; retrieval must move to a new article."
        }
      ]
    }
  ]
}
```

### Session field specifications

| Field | Type | Rule |
|---|---|---|
| `session_id` | string | `S1`–`S5`, unique. |
| `profile` | enum | `assignment_researcher` \| `settling_an_argument` \| `late_night_wanderer` \| `trip_planner` \| `media_prompted_learner`. One session each. |
| `curiosity_style` | enum | `hunter` \| `busybody` \| `dancer`. Must match the profile table above. |
| `information_need_anchor` | enum | `fact_lookup` \| `overview` \| `in_depth` |
| `motivation_anchor` | enum | `work_or_school` \| `personal_decision` \| `current_event` \| `media_reference` \| `conversation` \| `bored_random` \| `intrinsic_learning` \| `other` |
| `prior_familiarity_anchor` | enum | `familiar` \| `unfamiliar` \| `mixed` |
| `declared_turn_count` | integer | Must equal the actual number of turns. |
| `session_arc` | string | 40+ characters describing the intended trajectory. |
| `turns` | array | Turn objects, in order. |

### Turn field specifications

| Field | Type | Rule |
|---|---|---|
| `turn_index` | integer | Contiguous from 1, in order, no gaps or duplicates. |
| `user_query` | string | Phrased in the profile's voice. |
| `context_dependency` | enum | `standalone` \| `referential` \| `accumulative` |
| `information_need` | enum | `fact_lookup` \| `overview` \| `in_depth`. May vary within a session. |
| `answerable` | boolean | `false` only where the system should decline. |
| `expected_answer` | string | Reference answer, fully grounded in the quotes. |
| `supporting_quotes` | array | `text` + `source_file`. Empty only when unanswerable. |
| `relevant_files` | array of strings | Ranked. Superset of quote sources and retrieval focus. |
| `expected_retrieval_focus` | array of strings | Article(s) retrieval should now centre on. |
| `retrieval_should_shift` | boolean | `true` iff focus adds a document not in the previous turn's focus. Always `true` on turn 1. |
| `antecedents` | array | Objects with `expression`, `entity`, `introduced_in_turn`. Required for `referential`; empty for `standalone` and for `unintroduced_referent`. |
| `depends_on_turns` | array of integers | Turns whose **answer content** is required. Required for `accumulative`, `user_correction`, `topic_return`. All values strictly less than `turn_index`. |
| `referring_expressions` | array of strings | The exact referring phrases used, as they appear in `user_query`. |
| `adversarial_kind` | enum or null | `ambiguous_antecedent` \| `unintroduced_referent` \| `user_correction` \| `topic_return` \| `stale_context_trap` \| `null` |
| `expected_behavior` | string or null | Required and non-empty when `adversarial_kind` is set. |
| `difficulty_notes` | string | What this turn stresses and what a weak system gets wrong. |

## SELF-CHECK BEFORE OUTPUT

Satisfy every item. Do not report the checklist; just comply.

1. Exactly 5 sessions, one per profile, `session_id` `S1`–`S5`.
2. Turn counts exactly: 18, 8, 20, 14, 12 — 72 turns total. Each `declared_turn_count`
   matches its actual turn count. None exceeds 20.
3. `curiosity_style` matches the profile table for every session.
4. Every `session_arc` is 40+ characters and describes the actual trajectory.
5. `turn_index` runs 1..N contiguously and in order in every session.
6. Every session's **first turn** is `standalone` with `retrieval_should_shift: true`.
7. Every session contains at least one `standalone`, one `referential`, and one
   `accumulative` turn.
8. Every `referential` turn declares non-empty `antecedents` and
   `referring_expressions` — except `unintroduced_referent` turns, which declare empty
   `antecedents` by design.
9. Every `accumulative` turn declares `depends_on_turns` with two or more entries.
10. Every value in `depends_on_turns` and every `introduced_in_turn` is strictly less
    than its own `turn_index` and names a turn that exists.
11. Every `referring_expressions` entry appears verbatim inside its own `user_query`.
12. Every entity named in an `antecedent` was genuinely introduced in the turn cited —
    check the earlier turn's query, answer, and quotes.
13. `retrieval_should_shift` is consistent with `expected_retrieval_focus` on every turn:
    `true` adds a document, `false` does not.
14. Every session has at least two retrieval shifts; the 18- and 20-turn sessions have
    at least four.
15. 12+ adversarial turns total, 2–3 per session, covering all five kinds at least once.
16. Every adversarial turn has a non-empty `expected_behavior`.
17. Every `ambiguous_antecedent` turn lists 2+ candidate antecedents and is not
    `standalone`.
18. Every `unintroduced_referent` turn has `answerable: false` and empty `antecedents`.
19. Every `topic_return` turn is at least 3 turns after the turn it returns to.
20. Every `stale_context_trap` turn sets `retrieval_should_shift: true`.
21. Every `answerable: false` turn has an `adversarial_kind`; every `answerable: true`
    turn has non-empty `relevant_files`, `supporting_quotes`, and
    `expected_retrieval_focus`.
22. Every filename exists in the corpus, exact in spelling and capitalisation; every
    quote source and retrieval-focus entry also appears in that turn's `relevant_files`.
23. Every quote is verbatim from the file you opened, 25–300 characters, free of
    reference markers and markup.
24. No article used here appears in the single-turn golden suite.
25. Output is valid JSON with no text outside the JSON object.
