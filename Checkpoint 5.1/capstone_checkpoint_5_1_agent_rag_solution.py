r"""Capstone Checkpoint 5.1 - Agent-based RAG over the Wikipedia corpus.

A LangGraph agent that plans over the Checkpoint 4.1 retrievers instead of
committing to one. Design: ``capstone_checkpoint_5_1_agent_design.md``.

    seed_retrieve -> fuse -> [steps left?] -> plan -> chunks | decompose | graph
                                                      | title_search (v2) | clarify
                                                      | answer
    every retrieval tool -> fuse -> [steps left?] -> plan ...

The 4.1 script is imported, not copied: the chunk corpus, hybrid index, parent
expander, graph, judges and deterministic metrics are the same code that scored
the 4.1 runs, so every 4.1 metric is computed identically on the agent's final
context. The 4.1 script itself is not modified; the graph relation filter is a
proxy over its ``WikipediaGraph``.

| Version | Tools | Answer prompt |
|---|---|---|
| v1 (initial) | chunks, decompose, graph, clarify, answer | 4.1 ANSWER_SYSTEM + clarifications |
| v2 (refined) | + title_search, read_section; verified facts; grounded decompose | + reason-then-answer, clue facts |

Modes: ``--input`` batch evaluation (clarify never blocks), ``--question`` a
single batch query with its trace, ``--chat`` interactive (clarify asks you).
"""

# %%
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
import time
import warnings
from collections import defaultdict
from datetime import datetime
from operator import add
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

warnings.filterwarnings("ignore")

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

CHECKPOINT_4_1_DIR = Path(__file__).parents[1] / "Checkpoint 4.1"
_ADV_PATH = CHECKPOINT_4_1_DIR / "capstone_checkpoint_4_1_advanced_retrieval_solution.py"
_spec = importlib.util.spec_from_file_location("advanced_retrieval_4_1", _ADV_PATH)
adv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = adv          # dataclasses resolve annotations through sys.modules
_spec.loader.exec_module(adv)

Hit = adv.Hit

# %%
SCENARIO = "wikipedia"
AGENT_VERSIONS = ("v0", "v1", "v2")   # v0 = the fixed 3.1/4.1 whole-article baseline, no agent
BASELINE_TOP_K = adv.RETRIEVER_CONFIGS["baseline"]["top_k"]         # 3 whole articles
BASELINE_POOL = adv.RETRIEVER_CONFIGS["baseline"]["candidate_pool"] # 10

SEED_TOP_K = adv.RETRIEVER_CONFIGS["chunks"]["top_k"]              # 8, as the 4.1 chunks run
SEED_POOL = adv.RETRIEVER_CONFIGS["chunks"]["candidate_pool"]      # 40
MAX_PLANNED_STEPS = 3            # retrievals after the free seed (starter MAX_STEPS = 3)
MAX_CLARIFY = 1
PLANNER_EVIDENCE_CHARS = 16_000  # evidence shown to the planner, ~4k tokens
CONTEXT_BUDGET = adv.PARENT_MAX_CONTEXT_CHARS                      # 40,000, as 4.1
RRF_K = 60
STEP_GUARANTEE = 3               # each step's top units always reach the context
TITLE_MAX_FILES = 5
READ_MAX_CHUNKS = 6              # read_section: consecutive chunks returned (~12k chars)
ARTICLE_MAX_CHARS = 20_000       # parent=article above this reads lead_section instead
FACET_MAX = 3                    # graph facets per call (v2 round 2)
FACET_CATEGORIES = 3             # categories matched per facet
GRAPH_RELATIONS = ("category", "infobox", "link")
HISTORY_TURNS = 3                # chat mode: prior turns shown to planner and answerer

# v2 round-2 refinements, each switchable with --disable for attribution runs.
V2_FEATURES = ("tables", "sections", "clues", "facets")
# The tables feature reads a second chunk index built with the 2.1 module's
# render_tables=True, so v0, v1 and the 4.1 runs keep their original index.
TABLES_CACHE_DIR = adv.CHECKPOINT_2_1_DIR / f"wikipedia_chunks{adv.MAX_CHUNK_CHARS}_tables_cache"
TABLES_CHROMA_DIR = adv.CHECKPOINT_2_1_DIR / f"wikipedia_chunks{adv.MAX_CHUNK_CHARS}_tables_chroma_db"

GOLDEN_SUITE_PATH = CHECKPOINT_4_1_DIR / "mini-4.1-test-suite.json"
RESULTS_DIR = Path(__file__).with_name("evaluation_results")
LOG_PATH = Path(__file__).with_name("checkpoint_5_1_agent.log")

ActionName = Literal["chunks", "decompose", "graph", "title_search", "read_section", "clarify", "answer"]
StopReason = Literal["planner_answer", "step_budget", "parse_failure", "repeat_action",
                     "clarify_limit", "unknown_action", "unverified_answer", "fixed_pipeline"]
ACTIONS_BY_VERSION = {
    "v0": {"answer"},
    "v1": {"chunks", "decompose", "graph", "clarify", "answer"},
    "v2": {"chunks", "decompose", "graph", "title_search", "read_section", "clarify", "answer"},
}
RETRIEVAL_ACTIONS = {"chunks", "decompose", "graph", "title_search", "read_section"}


def log(label: str, text: str) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {label}\n{text}\n{'-' * 72}\n")


# %% [markdown]
# ## Prompts

# %%
_PLANNER_INTRO = """\
You are the planning step of a retrieval agent over a fixed collection of 2,419 English \
Wikipedia articles. Each turn you see the user's question, any clarifications, the actions \
already taken, and the evidence gathered so far. Decide the single next action.

First assess the evidence. List each piece of information the question needs that the \
evidence does not yet state explicitly. Judge only from the evidence text, never from your \
own knowledge: a fact you believe but cannot see in the evidence is missing.

Actions:"""

_PLANNER_CHUNKS = """\
- chunks {"query": str, "parent": str}: keyword and semantic search over article passages. \
Best for a single named entity or fact. "parent" widens each passage found: "none" (the \
passage only), "window" (neighbouring passages), "section" (the whole section; use when a \
passage shows the right article but the answer sits in a nearby table or list), \
"lead_section" (the article introduction plus the section), "article" (the whole article; \
costly, use last)."""

_PLANNER_DECOMPOSE = """\
- decompose {"query": str}: splits a question into sub-queries and searches each. Best when \
the question names several entities to compare or combine, such as two ceremonies or three \
Olympic Games."""

_PLANNER_GRAPH = """\
- graph {"query": str, "relations": [str]}: expands the best-matching articles through \
Wikipedia's structure. "relations" is any of: "category" (articles sharing categories, and \
categories whose names match the query; best for "which X was both A and B"); "infobox" \
(typed facts such as Education, Spouse, Successor, Mother; best for "the university where X \
studied" or "X's successor"); "link" (hyperlinked articles; broad and noisy)."""

_PLANNER_TITLE_SEARCH = """\
- title_search {"pattern": str, "query": str}: case-insensitive regular expression over \
article filenames, with underscores for spaces, e.g. "^95th_Academy_Awards" or \
"^1964_.*Nobel". Returns each matching article's opening passage and its passage that best \
matches "query". Use it when the question or evidence gives an ordinal, a year or a \
predictable title. It makes no model call and is the cheapest action."""

_PLANNER_CLARIFY_ANSWER = """\
- clarify {"question": str, "interpretations": [str]}: ask the user to choose, only when the \
evidence shows two or more distinct things the question could refer to and nothing in the \
question or clarifications selects one. At most once.
- answer {}: stop searching and answer from the evidence."""

_PLANNER_RULES = """\
Rules:
1. Build search queries only from names and facts that appear in the question or the \
evidence. Never introduce an entity you recall from memory. If an entity is unknown, \
describe it ("university where Barack Obama earned his law degree") and let retrieval find it.
2. When the evidence reveals an intermediate fact the question depends on (a year, a name, \
a place), use it explicitly in the next query.
3. Never repeat an action with the same arguments. Change the query, the tool, the parent \
or the relations instead.
4. Choose answer when nothing is missing, or when more searching is unlikely to help; the \
answerer will state what the evidence does not cover."""

_PLANNER_RULE_5 = {
    "v1": "5. Prefer the cheapest action likely to close the gap: chunks before decompose, "
          "a narrower parent before a wider one.",
    "v2": "5. Prefer the cheapest action likely to close the gap: read_section when the right "
          "article is already in the evidence, title_search when a title is predictable, then "
          "chunks, then decompose; a narrower parent before a wider one. Exception: when the "
          "question describes its answer only by a combination of properties rather than a name "
          "(\"which president served in both centuries\", \"another director who won X\", \"films "
          "by English directors that won Y\"), use graph with \"category\" first: Wikipedia's "
          "categories group articles by exactly such properties, and a passage search for the "
          "description rarely finds the entity. graph also makes no model call. A step that "
          "returned 0 new passages will not help if repeated with small changes.",
}

_PLANNER_READ_SECTION = """\
- read_section {"file": str, "section": str, "query": str}: reads consecutive passages, in \
order, from one section of an article already in the evidence, e.g. {"file": \
"95th_Academy_Awards.html", "section": "Winners and nominees", "query": "Best Actor"}. \
Section names follow "§" in the evidence labels. Use it when the evidence shows the right \
article but not the table, list or detail the question needs: long tables are split across \
passages, and a passage in the middle of a table may not repeat its headings, so searching \
cannot find it. "query" picks the part of a long section to read. No model call."""

_PLANNER_RULE_6_V2 = """\
6. In "clues", list every condition the question sets, in the question's own words: for \
"the director of the film that won Best Picture the year the stadium opened" the clues are \
"the year the stadium opened", "the film that won Best Picture that year" and "its director". \
Before choosing answer, give in "facts" at least one fact for every clue: the clue's number, \
the fact, the evidence filename that states it, and a short verbatim quote (under 25 words) \
copied exactly from that file's passage; for a table, quote a single cell's text. Each fact \
must be about the entity the question asks about, not a part of it or a related one: if the \
question asks about a university, a fact about one of its schools does not answer it. Facts \
from different articles combine: if one article dates the stadium's opening and another \
dates the award, the shared year links them, and no single article needs to state the link. \
A clue you cannot support with a quote from the evidence is missing: search for it instead of \
answering. Quotes are checked against the evidence, and an answer that leaves a clue without \
a verified fact is sent back to you."""

_PLANNER_FORMAT = {
    "v1": """\
Respond with ONLY a JSON object:
{"assessment": "<one sentence on what the evidence covers>", "missing": ["<gap>", ...], \
"action": "<action name>", "args": {...}}""",
    "v2": """\
Respond with ONLY a JSON object:
{"assessment": "<one sentence on what the evidence covers>", "missing": ["<gap>", ...], \
"clues": ["<condition from the question>", ...], \
"facts": [{"clue": <clue number, from 1>, "fact": "<fact>", "source": "<filename.html>", \
"quote": "<verbatim excerpt>"}, ...], "action": "<action name>", "args": {...}}""",
}

VERIFY_FACTS_FEEDBACK = """\
These facts could not be verified against the evidence (the quote must be copied exactly):
{failures}"""

VERIFY_CLUES_FEEDBACK = """\
These clues have no verified fact yet:
{clues}"""

VERIFY_CLOSING = """\
Fix the quotes if the evidence does state these facts; otherwise choose a retrieval action \
that could find them (following the rules). Answer only when every clue has a verified fact. \
Reply with a single complete JSON object in the same format (assessment, missing, clues, \
facts, action, args)."""


# --- v2 round 2: each text below replaces or extends round-1 text only while
# its feature is on, so --disable reproduces the round-1 prompt exactly. ---

_PLANNER_CHUNKS_SECTIONS = """\
- chunks {"query": str, "parent": str}: keyword and semantic search over article passages. \
Best for a single named entity or fact. "parent" widens each passage found: "none" (the \
passage only), "window" (neighbouring passages), "section" (the passage's whole section \
including its subsections, e.g. a table under a sub-heading; a long section is read as the \
part that best matches the query), "lead_section" (the article introduction plus that \
section), "article" (the whole article; costly, use last)."""                       # sections

_PLANNER_GRAPH_FACETS = """\
- graph {"query": str, "relations": [str], "facets": [str]}: expands the best-matching \
articles through Wikipedia's structure. "relations" is any of: "category" (articles sharing \
categories, and categories whose names match the query); "infobox" (typed facts such as \
Education, Spouse, Successor, Mother; best for "the university where X studied" or "X's \
successor"); "link" (hyperlinked articles; broad and noisy). "facets" (optional, up to 3) \
finds articles that meet several properties at once: give one short category-style phrase \
per property, e.g. for "a German-born composer who won an Oscar" the facets ["German \
composers", "Academy Award for Best Original Score winners"]. Each facet is matched to \
Wikipedia categories separately and only articles in categories for every facet are \
returned first."""                                                                  # facets

_PLANNER_RULE_5_FACETS = (
    "5. Prefer the cheapest action likely to close the gap: read_section when the right "
    "article is already in the evidence, title_search when a title is predictable, then "
    "chunks, then decompose; a narrower parent before a wider one. Exception: when the "
    "question describes its answer only by a combination of properties rather than a name "
    "(\"a German-born composer who won an Oscar\", \"a novelist who also served as a "
    "diplomat\"), use graph with one facet per property first: Wikipedia's categories group "
    "articles by exactly such properties, and a passage search for the description rarely "
    "finds the entity. graph also makes no model call. A step that returned 0 new passages "
    "will not help if repeated with small changes."
)                                                                                   # facets

_PLANNER_RULE_6_CLUES = """\
The clue list is fixed before your first turn and shown in the message. Repeat those clues \
exactly and in the same order, numbered the same way; you may only append new ones."""   # clues


CLUES_SYSTEM = """\
You prepare a question for a retrieval agent over English Wikipedia articles. Do not answer it.

"indirect": list every value the question refers to only through another fact instead of \
stating it, as the phrase that identifies it. For "Who composed the anthem adopted the year \
the dam was completed?" the year is given only as "the year the dam was completed", so \
indirect = ["the year the dam was completed"]. For "Who designed the bridge in the city where \
the treaty was signed?" indirect = ["the city where the treaty was signed"]. If every value \
is stated, give [].

"clues": the other conditions the answer depends on, one per clue, in the question's words.

"facets": only when the question asks for people or things described by properties instead of \
names, as in "which painter was also a diplomat" or "name a composer born in Germany who won \
an Oscar": one short Wikipedia-category-style phrase per property. Otherwise [].

Do not add names, dates or facts from your own knowledge.
Respond with ONLY a JSON object: {"indirect": ["..."], "clues": ["..."], "facets": ["..."]}"""   # clues
# Asked directly to "split nested clues", gpt-5.4-mini kept Q009's bridge as one
# clue in 6 of 6 calls at temperature 0; asked which values are given only
# indirectly, it named the earthquake year in 3 of 3.


def planner_system(version: str, features: set[str] | frozenset[str] | None = None) -> str:
    """features: the round-2 refinements that are on (v2 only; default all)."""
    features = set(V2_FEATURES if features is None else features) if version == "v2" else set()
    chunks = _PLANNER_CHUNKS_SECTIONS if "sections" in features else _PLANNER_CHUNKS
    graph = _PLANNER_GRAPH_FACETS if "facets" in features else _PLANNER_GRAPH
    actions = [chunks, _PLANNER_DECOMPOSE, graph]
    rule_5 = _PLANNER_RULE_5_FACETS if "facets" in features else _PLANNER_RULE_5[version]
    rules = _PLANNER_RULES + "\n" + rule_5
    if version == "v2":
        actions += [_PLANNER_TITLE_SEARCH, _PLANNER_READ_SECTION]
        rules += "\n" + _PLANNER_RULE_6_V2
        if "clues" in features:
            rules += " " + _PLANNER_RULE_6_CLUES
    actions.append(_PLANNER_CLARIFY_ANSWER)
    if version == "v2":
        # G07 (round 2): the planner asked which of several Yale presidents was meant.
        actions.append("  Several correct answers are not ambiguity: when the question asks for "
                       "\"another\", \"an example\" or a number of items, choose from the evidence "
                       "instead of clarifying.")
    return "\n\n".join([
        _PLANNER_INTRO + "\n" + "\n".join(actions),
        rules,
        _PLANNER_FORMAT[version],
    ])


# 4.1's DECOMPOSE_SYSTEM (used unchanged by v1) does not forbid naming entities
# from memory; that is how 4.1 decompose cut chunk attribution from 0.62 to 0.48.
DECOMPOSE_GROUNDING_V2 = (
    " Use only the names, dates and facts stated in the question itself. Do not add "
    "entities, dates or answers from your own knowledge: if the question refers to "
    "something without naming it, describe it in the sub-query (e.g. \"university where "
    "Barack Obama earned his law degree\") rather than naming it."
)


def decompose_system(version: str) -> str:
    return adv.DECOMPOSE_SYSTEM + (DECOMPOSE_GROUNDING_V2 if version == "v2" else "")


ANSWER_CLARIFY = (
    " If clarifications are listed, follow them. If a clarification says no user was "
    "available, answer each listed interpretation separately and label each one."
)
ANSWER_REASON_FIRST = (
    " For yes/no, comparison and date-order questions, first state the relevant facts "
    "with citations, then give the conclusion in a final sentence."
    " When the question identifies its subject through a clue (such as 'the year something "
    "happened'), state the fact from the documents that satisfies each clue, with its "
    "citation, as part of the answer. When the question asks why, give every reason the "
    "documents state. When comparing dates, write each date as YYYY-MM-DD, say which is "
    "earlier, and only then answer the question as asked: \"did A happen before B?\" is yes "
    "when A's date is the earlier one. Answer other questions directly. Every sentence, "
    "including any conclusion, must cite its source; a concluding or comparing sentence may "
    "only restate facts already cited. Do not restate the question, add a summary judgement "
    "the documents do not state, or offer further help."
)


def answer_system(version: str) -> str:
    # The 4.1 ANSWER_SYSTEM is kept verbatim so answer-side differences come
    # from the evidence, not the wording.
    system = adv.ANSWER_SYSTEM + ANSWER_CLARIFY
    if version == "v2":
        system += ANSWER_REASON_FIRST
    return system


# %% [markdown]
# ## State

# %%
class PlannedAction(TypedDict):
    action: ActionName
    args: dict[str, Any]
    assessment: str
    missing: list[str]
    clues: list[str]              # v2: the conditions the question sets
    facts: list[dict[str, Any]]   # v2: {clue, fact, source, quote, verified, reason}


class StepRecord(TypedDict):
    step: int                     # 0 = seed
    action: ActionName | Literal["seed"]
    args: dict[str, Any]
    assessment: str
    missing: list[str]
    clues: list[str]
    facts: list[dict[str, Any]]
    ranked_unit_ids: list[str]
    new_unit_ids: list[str]
    files: list[str]
    trace: dict[str, Any]
    seconds: float                # tool time excluding any model call
    error: str | None


class EvidenceEntry(TypedDict):
    hit: Hit
    rrf: float
    first_step: int
    step_ranks: dict[int, int]


class AgentState(TypedDict):
    # inputs
    question: str
    mode: Literal["batch", "chat"]
    version: Literal["v1", "v2"]
    history: list[tuple[str, str]]
    # planning loop
    next_action: PlannedAction | None
    steps: Annotated[list[StepRecord], add]
    planned_steps: int
    clarify_count: int
    clues: list[str]                 # v2 round 2: frozen at the first planner reply
    features: list[str]              # v2 round-2 refinements active in this run
    auto_facets_pending: bool        # v2 round 2: run the clue step's facet search next
    clarifications: Annotated[list[str], add]
    stop_reason: StopReason | None
    verification_retries: int        # v2: answers sent back for unverifiable facts
    # evidence
    pending_hits: list[Hit]          # the last tool's ranked output, consumed by fuse
    evidence: dict[str, EvidenceEntry]
    context: list[Hit]
    # outputs and accounting
    response: str
    usage: Annotated[list[dict[str, Any]], add]


# %% [markdown]
# ## Tools (thin wrappers over the 4.1 retrievers)

# %%
class RelationFilteredGraph:
    """View of the 4.1 WikipediaGraph that exposes only the requested relation
    kinds to Retriever._graph, so the graph tool can be steered without
    changing the 4.1 code. 'category' covers both matched-category
    intersections and category co-membership."""

    def __init__(self, graph: Any, relations: set[str]):
        self._graph = graph
        self._relations = relations

    def __getattr__(self, name: str) -> Any:
        return getattr(self._graph, name)

    def match_categories(self, query: str) -> list[tuple[str, int]]:
        return self._graph.match_categories(query) if "category" in self._relations else []

    def neighbours(self, article_id: str) -> list[tuple[str, str, str]]:
        return [item for item in self._graph.neighbours(article_id) if item[1] in self._relations]


def load_or_build_tables_corpus() -> Any:
    """The 4.1 chunk cache builder, pointed at TABLES_CACHE_DIR and run with
    the 2.1 module's render_tables=True. The 4.1 module is not modified: its
    two module globals are swapped for the call and restored afterwards."""
    saved = adv.CHUNK_CACHE_DIR, adv.process_wikipedia_with_nodes_and_edges
    original = adv.process_wikipedia_with_nodes_and_edges
    adv.CHUNK_CACHE_DIR = TABLES_CACHE_DIR
    adv.process_wikipedia_with_nodes_and_edges = (
        lambda directory, max_chars: original(directory, max_chars, render_tables=True)
    )
    try:
        return adv.load_or_build_chunk_corpus()
    finally:
        adv.CHUNK_CACHE_DIR, adv.process_wikipedia_with_nodes_and_edges = saved


def build_or_load_tables_db(corpus: Any) -> Any:
    """Vector index for the tables corpus. A chunk whose embedded text is
    identical to a chunk of the original index reuses that chunk's stored
    embedding; only new or changed text is sent to the embedding model.
    Resumable, like the 4.1 builder."""
    from langchain_chroma import Chroma

    complete_marker = TABLES_CHROMA_DIR / "index_complete.json"
    db = Chroma(persist_directory=str(TABLES_CHROMA_DIR), embedding_function=adv.get_embeddings())
    if complete_marker.is_file():
        print(f"Loading existing tables chunk vector DB from {TABLES_CHROMA_DIR}")
        return db
    print("Loading the original chunk corpus to find reusable embeddings...")
    original_corpus = adv.load_or_build_chunk_corpus()
    original_id_by_text = {}
    for unit_id, _file, text in original_corpus.units:
        original_id_by_text.setdefault(text, unit_id)
    original_db = adv.build_or_load_chunk_db(original_corpus)
    embedder = adv.get_embeddings()
    total = len(corpus.units)
    existing = db._collection.count()
    start = (existing // adv.INDEX_BATCH_SIZE) * adv.INDEX_BATCH_SIZE
    print(f"Building tables chunk vector DB at {TABLES_CHROMA_DIR} ({total} chunks, {existing} already present)")
    reused = embedded = 0
    started = time.perf_counter()
    for begin in range(start, total, adv.INDEX_BATCH_SIZE):
        batch = corpus.chunks[begin:begin + adv.INDEX_BATCH_SIZE]
        units = corpus.units[begin:begin + adv.INDEX_BATCH_SIZE]
        ids = [unit_id for unit_id, _file, _text in units]
        texts = [text for _id, _file, text in units]
        metadatas = [adv._scalar_metadata(chunk["metadata"]) for chunk in batch]
        vectors: list[Any] = [None] * len(units)
        old_ids = {i: original_id_by_text[text] for i, text in enumerate(texts) if text in original_id_by_text}
        if old_ids:
            stored = original_db._collection.get(ids=list(dict.fromkeys(old_ids.values())), include=["embeddings"])
            by_id = dict(zip(stored["ids"], stored["embeddings"]))
            for i, old_id in old_ids.items():
                if old_id in by_id:
                    vectors[i] = list(by_id[old_id])
        missing = [i for i, vector in enumerate(vectors) if vector is None]
        if missing:
            for i, vector in zip(missing, embedder.embed_documents([texts[i] for i in missing])):
                vectors[i] = vector
        reused += len(units) - len(missing)
        embedded += len(missing)
        db._collection.add(ids=ids, embeddings=vectors, documents=texts, metadatas=metadatas)
        done = min(begin + adv.INDEX_BATCH_SIZE, total)
        print(f"  indexed {done}/{total} chunks ({reused} reused, {embedded} embedded, "
              f"{time.perf_counter() - started:.0f}s elapsed)")
    complete_marker.write_text(json.dumps({
        "chunk_count": total, "embedding_model": adv.EMBEDDING_MODEL,
        "reused_this_session": reused, "embedded_this_session": embedded,
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }, indent=2), encoding="utf-8")
    print(f"Indexed {total} chunks ({reused} reused, {embedded} newly embedded).")
    return db


class Toolbox:
    """Loads the chunk corpus, index, parent expander and graph once and
    exposes each agent action as a function returning (hits, trace).
    tables=True uses the table-rendered index (v2 round 2); otherwise the
    original 4.1 index."""

    def __init__(self, tables: bool = False) -> None:
        self.tables = tables
        if tables:
            corpus = load_or_build_tables_corpus()
            db = build_or_load_tables_db(corpus)
        else:
            corpus = adv.load_or_build_chunk_corpus()
            db = adv.build_or_load_chunk_db(corpus)
        print(f"Building BM25 index over {len(corpus.units)} chunks...")
        self.index = adv.HybridIndex(corpus.units, db, metadata_id_key="chunk_id")
        self.expander = adv.ParentExpander(corpus, self.index)
        print("Building NetworkX graph...")
        self.graph = adv.WikipediaGraph(corpus, self.index)
        self.retriever = adv.Retriever(
            mode="graph", top_k=SEED_TOP_K, candidate_pool=SEED_POOL,
            chunk_index=self.index, graph=self.graph, expander=self.expander,
        )
        self.files = sorted(self.expander.positions_by_file)
        self.stems = {file: file[:-5] if file.endswith(".html") else file for file in self.files}

    # --- chunks: 4.1 fused chunk search, optional parent expansion ---
    def chunks(self, query: str, parent: str = "none", article_fallback: bool = False,
               h2_sections: bool = False) -> tuple[list[Hit], dict[str, Any]]:
        hits = self.index.get_top_k(query, SEED_TOP_K, SEED_POOL)
        trace: dict[str, Any] = {}
        if parent != "none":
            trace["child_chunk_ids"] = [hit.unit_id for hit in hits]
            if parent == "article" and article_fallback:          # v2
                hits, trace["article_too_long"] = self._expand_articles(hits)
            elif parent in ("section", "lead_section") and h2_sections:   # v2 round 2
                hits = self._expand_h2_sections(hits, parent, query)
            else:
                hits = self.expander.expand(hits, parent, CONTEXT_BUDGET)
        return hits, trace

    def _h2_window(self, position: int, query_scores: list[float]) -> list[int]:
        """The hit's Header 2 section, subsections included, as at most
        READ_MAX_CHUNKS consecutive chunks: the window containing the hit with
        the highest BM25 score for the query. The 4.1 section parent keys on
        (Header 2, Header 3), so a hit in 'Winners and nominees' could never
        reach the 'Awards' table below it (Q049)."""
        file = self.index.source_files[position]
        positions = self.expander.positions_by_file[file]
        h1, h2, _h3 = self.expander.section_key[position]
        if h2 is None:                                  # lead or H1-level: nothing wider to read
            return [position]
        i = positions.index(position)
        lo = hi = i
        while lo > 0 and self.expander.section_key[positions[lo - 1]][:2] == (h1, h2):
            lo -= 1
        while hi < len(positions) - 1 and self.expander.section_key[positions[hi + 1]][:2] == (h1, h2):
            hi += 1
        span = positions[lo:hi + 1]
        if len(span) <= READ_MAX_CHUNKS:
            return span
        hit_at = i - lo
        starts = range(max(0, hit_at - READ_MAX_CHUNKS + 1), min(hit_at, len(span) - READ_MAX_CHUNKS) + 1)
        start = max(starts, key=lambda s: (sum(query_scores[p] for p in span[s:s + READ_MAX_CHUNKS]), -abs(s + READ_MAX_CHUNKS // 2 - hit_at)))
        return span[start:start + READ_MAX_CHUNKS]

    def _expand_h2_sections(self, hits: list[Hit], parent: str, query: str) -> list[Hit]:
        scores = self.index.bm25_scores(query)
        expanded: list[Hit] = []
        covered: set[int] = set()
        remaining = CONTEXT_BUDGET
        for hit in hits:
            position = self.index.index_of.get(hit.unit_id)
            if position is None or position in covered:
                continue
            window = self._h2_window(position, scores)
            if parent == "lead_section":
                positions = self.expander.positions_by_file[hit.source_file]
                lead = [p for p in positions if self.expander.section_key[p][1] is None
                        and self.expander.section_key[p][2] is None][:adv.LEAD_MAX_CHUNKS]
                window = sorted(set(lead) | set(window), key=lambda p: self.expander.chunk_index_of[p])
            window = [p for p in window if p not in covered]
            text = "\n\n".join(self.index.texts[p] for p in window)
            if len(text) > remaining:
                window, text = [position], self.index.texts[position]
                if len(text) > remaining:
                    break
            remaining -= len(text)
            covered.update(window)
            first, last = self.expander.chunk_index_of[window[0]], self.expander.chunk_index_of[window[-1]]
            unit_id = f"{hit.source_file}#c{first:05d}-c{last:05d}" if len(window) > 1 else hit.unit_id
            expanded.append(Hit(unit_id, hit.source_file, text, hit.score, hit.role, hit.article_id))
        return expanded

    def _expand_articles(self, hits: list[Hit]) -> tuple[list[Hit], list[str]]:
        """Whole-article parents where the article fits in ARTICLE_MAX_CHARS,
        lead_section otherwise. The 4.1 expander keeps only the child chunk
        when an article overflows its budget, which in G13 silently dropped
        Harvard University's infobox (its 'Former names' row)."""
        expanded: list[Hit] = []
        too_long: list[str] = []
        remaining = CONTEXT_BUDGET
        for hit in hits:
            positions = self.expander.positions_by_file.get(hit.source_file, [])
            size = sum(len(self.index.texts[p]) for p in positions)
            mode = "article" if size <= ARTICLE_MAX_CHARS else "lead_section"
            if mode != "article" and hit.source_file not in too_long:
                too_long.append(hit.source_file)
            for unit in self.expander.expand([hit], mode, remaining):
                if unit.unit_id not in {existing.unit_id for existing in expanded}:
                    expanded.append(unit)
                    remaining -= len(unit.text)
            if remaining <= 0:
                break
        return expanded, too_long

    # --- decompose: 4.1 Retriever._decompose with the sub-query call measured ---
    def decompose(self, llm: ChatOpenAI, query: str, system: str) -> tuple[list[Hit], dict[str, Any], dict[str, Any]]:
        messages = [SystemMessage(content=system), HumanMessage(content=query)]
        raw, usage = adv.invoke_measured(llm, messages)
        sub_queries = _parse_string_list(raw) or [query]
        score_map: dict[str, float] = defaultdict(float)
        passes = [query] + [sub for sub in sub_queries if sub.strip() and sub.strip() != query]
        for pass_query in passes:
            for unit_id, score in self.index.fused_scores(pass_query, SEED_POOL):
                score_map[unit_id] += score
        ranked = sorted(score_map.items(), key=lambda item: item[1], reverse=True)[:SEED_TOP_K]
        hits = [self.index.hit(unit_id, score) for unit_id, score in ranked]
        return hits, {"sub_queries": sub_queries}, usage

    # --- graph: 4.1 Retriever._graph over a relation-filtered view ---
    def graph_expand(self, query: str, relations: list[str]) -> tuple[list[Hit], dict[str, Any]]:
        self.retriever.graph = RelationFilteredGraph(self.graph, set(relations))
        try:
            hits, trace = self.retriever._graph(query)
        finally:
            self.retriever.graph = self.graph
        return hits, {**trace, "relations": relations}

    # --- graph facets (v2 round 2): per-property category intersection ---
    def graph_facets(self, facets: list[str], query: str) -> tuple[list[Hit], dict[str, Any]]:
        """Match each facet to categories on its own and rank articles by how
        many facets they satisfy. A single query cannot do this: on G10 the
        4.1 matcher filled all 8 category slots with 'Films that won the X
        Academy Award' and never matched 'English film directors'."""
        graph = self.graph
        facets = facets[:FACET_MAX]
        # Candidate categories per facet at three strictness levels:
        #   0: every facet word and the fewest extra words ("English film directors",
        #      not "English-language film directors");
        #   1: every category with the highest word overlap;
        #   2: the top FACET_CATEGORIES matches.
        # The strictest level whose intersection is non-empty is used, so
        # "21st-century presidents" does not also admit "19th-century presidents".
        levels_by_facet: list[list[list[tuple[str, int]]]] = []
        for facet in facets:
            facet_tokens = adv._content_tokens(facet)
            matched = graph.match_categories(facet)
            scored = [(c, overlap, len(adv._content_tokens(graph.category_title[c]) - facet_tokens))
                      for c, overlap in matched]
            best = max((o for _c, o, _e in scored), default=0)
            top = [(c, e) for c, o, e in scored if o == best]
            fewest = min((e for _c, e in top), default=0)
            levels_by_facet.append([
                [(c, e) for c, e in top if e == fewest],
                top,
                [(c, e) for c, _o, e in scored[:FACET_CATEGORIES]],
            ])
        counts: dict[str, int] = defaultdict(int)
        extra: dict[str, int] = defaultdict(int)
        level_used = None
        for level in range(3):
            counts.clear(); extra.clear()
            for levels in levels_by_facet:
                best_extra: dict[str, int] = {}
                for category_id, extra_words in levels[level]:
                    for article_id in graph.category_members.get(category_id, []):
                        best_extra[article_id] = min(extra_words, best_extra.get(article_id, extra_words))
                for article_id, extra_words in best_extra.items():
                    counts[article_id] += 1
                    extra[article_id] += extra_words
            level_used = level
            if any(n == len(facets) for n in counts.values()):
                break
        facet_trace = [{"facet": facet, "categories": [
            {"title": graph.category_title[c], "members": len(graph.category_members.get(c, []))}
            for c, _e in levels[level_used]]} for facet, levels in zip(facets, levels_by_facet)]
        ranked = sorted(
            (article_id for article_id in counts if article_id in graph.file_by_article),
            key=lambda article_id: (-counts[article_id], extra[article_id], graph.file_by_article[article_id]),
        )
        members_by_facet = facets
        bm25_scores = self.index.bm25_scores(query)
        hits: list[Hit] = []
        for article_id in ranked[:SEED_TOP_K]:
            position, _score = graph.best_chunk(graph.file_by_article[article_id], bm25_scores)
            if position < 0:
                continue
            met = counts[article_id]
            hit = self.index.hit(self.index.unit_ids[position], float(met),
                                 f"context: meets {met} of {len(members_by_facet)} facets")
            hit.article_id = article_id
            hits.append(hit)
        return hits, {"facets": facet_trace, "strictness_level": level_used,
                      "all_facets_met": [graph.file_by_article[a] for a in ranked if counts[a] == len(members_by_facet)][:20]}

    # --- title_search (v2): regex over filename stems, no model call ---
    def title_search(self, pattern: str, query: str) -> tuple[list[Hit], dict[str, Any]]:
        regex = re.compile(pattern, re.IGNORECASE)     # re.error is reported to the planner
        query_tokens = adv._content_tokens(query)
        matches = [file for file in self.files if regex.search(self.stems[file])]
        matches.sort(key=lambda file: (
            -len(query_tokens & adv._content_tokens(self.stems[file].replace("_", " "))),
            len(file),
        ))
        chosen = matches[:TITLE_MAX_FILES]
        bm25_scores = self.index.bm25_scores(query)
        hits: list[Hit] = []
        for file in chosen:
            positions = self.expander.positions_by_file[file]
            best, _score = self.graph.best_chunk(file, bm25_scores)
            for position in dict.fromkeys([positions[0], best]):
                if position >= 0:
                    hits.append(self.index.hit(self.index.unit_ids[position], 1.0))
        return hits, {"pattern": pattern, "match_count": len(matches), "matched_files": chosen}

    # --- read_section (v2): consecutive chunks of one section, no model call ---
    def read_section(self, file: str, section: str, query: str) -> tuple[list[Hit], dict[str, Any]]:
        """Chunks whose Header 2 or Header 3 contains `section`, in document
        order. A long section is read as the READ_MAX_CHUNKS-chunk window with
        the highest BM25 score for `query`. This reaches passages that search
        cannot rank, such as the middle of a table whose headings sit in an
        earlier chunk."""
        name = Path(file.strip().strip("[]")).name
        if not name.endswith(".html"):
            name += ".html"
        by_casefold = {candidate.casefold(): candidate for candidate in self.files}
        resolved = by_casefold.get(name.casefold())
        if resolved is None:
            return [], {"file": file, "error": f"no article named {file!r} in the collection"}
        positions = self.expander.positions_by_file[resolved]
        outline = list(dict.fromkeys(self.section_label(p) for p in positions))
        headers = {p: [(header or "").casefold() for header in self.expander.section_key[p][1:]] for p in positions}
        # The planner sometimes copies a whole evidence label ("§ lead / Notes",
        # "Winners and nominees › Awards"), so each part is matched on its own.
        needles = [part.strip().casefold() for part in re.split(r"[/›>]", section.replace("§", "")) if part.strip()]
        matched_set: set[int] = set()
        for needle in needles:
            if needle == "lead":
                found = [p for p in positions if not any(headers[p])]
            else:
                # An exact heading beats a substring: "Awards" should read the
                # Awards subsection, not every heading containing "awards".
                found = [p for p in positions if needle in headers[p]]
                if not found:
                    found = [p for p in positions if any(needle in header for header in headers[p])]
            matched_set.update(found)
        matched = [p for p in positions if p in matched_set]
        trace: dict[str, Any] = {"file": resolved, "section": section, "matched_chunks": len(matched)}
        if not matched:
            return [], {**trace, "outline": outline[:40],
                        "error": f"no section matching {section!r}; sections: {outline[:40]}"}
        if len(matched) > READ_MAX_CHUNKS:
            scores = self.index.bm25_scores(query)
            start = max(
                range(len(matched) - READ_MAX_CHUNKS + 1),
                key=lambda i: (sum(scores[p] for p in matched[i:i + READ_MAX_CHUNKS]), -i),
            )
            matched = matched[start:start + READ_MAX_CHUNKS]
        hits = [self.index.hit(self.index.unit_ids[p], 1.0) for p in matched]
        return hits, {**trace, "read_chunks": [self.expander.chunk_index_of[p] for p in matched]}

    def section_label(self, position: int) -> str:
        _h1, h2, h3 = self.expander.section_key[position]
        return " › ".join(header for header in (h2, h3) if header) or "lead"

    def positions(self, hit: Hit) -> set[int]:
        """Chunk positions covered by a hit (a chunk, or an expanded parent).
        A parent's id gives its first and last chunk, but a lead_section parent
        is not contiguous, so only chunks whose text it contains count."""
        position = self.index.index_of.get(hit.unit_id)
        if position is not None:
            return {position}
        match = re.match(r"^(.*)#c(\d{5})-c(\d{5})$", hit.unit_id)
        if not match:
            return set()
        first, last = int(match.group(2)), int(match.group(3))
        return {
            p for p in self.expander.positions_by_file.get(match.group(1), [])
            if first <= self.expander.chunk_index_of[p] <= last and self.index.texts[p] in hit.text
        }


def _parse_string_list(raw: str) -> list[str]:
    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    start = text.find("[")
    try:
        parsed = json.loads(text) if start == -1 else json.JSONDecoder().raw_decode(text, start)[0]
    except (json.JSONDecodeError, ValueError):
        return []
    if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
        return parsed
    return []


# %% [markdown]
# ## The agent

# %%
class WikipediaAgent:
    def __init__(self, llm: ChatOpenAI, toolbox: Toolbox, version: str = "v2", answer_enabled: bool = True,
                 disabled: set[str] | None = None, planner_model: str | None = None,
                 answer_model: str | None = None, reasoning_effort: str | None = None):
        self.llm = llm
        self.tools = toolbox
        self.version = version
        # Round-2 refinements active in this run (v2 only; --disable removes some).
        self.features = set(V2_FEATURES) - set(disabled or ()) if version == "v2" else set()
        # --planner-model: the planner and the clue step can use a different
        # model; decompose, the answer and every judge keep adv.LLM_MODEL.
        self.planner_model = planner_model or adv.LLM_MODEL
        self.planner_llm = llm if self.planner_model == adv.LLM_MODEL else llm.model_copy(update={"model_name": self.planner_model})
        # --answer-model: the answer and the closed-book answer used for chunk
        # attribution (which compares the answer with what the same model says
        # without retrieval). Decompose and every judge keep adv.LLM_MODEL.
        self.answer_model = answer_model or adv.LLM_MODEL
        self.answer_llm = llm if self.answer_model == adv.LLM_MODEL else llm.model_copy(update={"model_name": self.answer_model})
        # --reasoning-effort: OpenRouter's reasoning setting for the planner, the
        # clue step and the answer (not decompose or the judges). Reasoning uses
        # part of max_tokens for hidden thinking (about half at "medium"), so
        # these clients get REASONING_MAX_TOKENS to leave room for the reply.
        self.reasoning_effort = reasoning_effort
        if reasoning_effort:
            with_reasoning = {"extra_body": {"reasoning": {"effort": reasoning_effort}},
                              "max_tokens": REASONING_MAX_TOKENS}
            self.planner_llm = self.planner_llm.model_copy(update=with_reasoning)
            self.answer_llm = self.answer_llm.model_copy(update=with_reasoning)
        # temperature=0 is requested for the clue step, but OpenRouter lists no
        # temperature parameter for the gpt-5.4 models, so it has no effect there.
        self.clue_llm = self.planner_llm.model_copy(update={"temperature": 0.0}) if "clues" in self.features else None
        self.answer_enabled = answer_enabled
        self.app = self._build()

    # ------------------------------------------------------------------ graph
    def _build(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("seed_retrieve", self.seed_retrieve)
        workflow.add_node("fuse", self.fuse)
        workflow.add_node("plan", self.plan)
        workflow.add_node("chunks", self.chunks_node)
        workflow.add_node("decompose", self.decompose_node)
        workflow.add_node("graph", self.graph_node)
        workflow.add_node("title_search", self.title_search_node)
        workflow.add_node("read_section", self.read_section_node)
        workflow.add_node("clarify", self.clarify_node)
        workflow.add_node("answer", self.answer_node)
        workflow.set_entry_point("seed_retrieve")
        workflow.add_edge("seed_retrieve", "fuse")
        workflow.add_conditional_edges("fuse", self.route_after_fuse, {"plan": "plan", "answer": "answer", "graph": "graph"})
        workflow.add_conditional_edges(
            "plan", self.route_after_plan,
            {name: name for name in RETRIEVAL_ACTIONS | {"clarify", "answer"}},
        )
        for tool in RETRIEVAL_ACTIONS:
            workflow.add_edge(tool, "fuse")
        workflow.add_edge("clarify", "plan")
        workflow.add_edge("answer", END)
        return workflow.compile()

    def run(self, question: str, mode: str = "batch", history: list[tuple[str, str]] | None = None) -> AgentState:
        initial: AgentState = {
            "question": question, "mode": mode, "version": self.version,
            "history": list(history or [])[-HISTORY_TURNS:],
            "next_action": None, "steps": [], "planned_steps": 0, "clarify_count": 0, "clues": [],
            "features": sorted(self.features), "auto_facets_pending": False,
            "clarifications": [], "stop_reason": None, "verification_retries": 0,
            "pending_hits": [], "evidence": {}, "context": [], "response": "", "usage": [],
        }
        return self.app.invoke(initial, {"recursion_limit": 50})

    # ---------------------------------------------------------------- routing
    def route_after_fuse(self, state: AgentState) -> str:
        if state.get("auto_facets_pending"):
            return "graph"
        return "plan" if state["planned_steps"] < MAX_PLANNED_STEPS else "answer"

    def route_after_plan(self, state: AgentState) -> str:
        return state["next_action"]["action"]

    # ----------------------------------------------------------------- nodes
    def seed_retrieve(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        hits, trace = self.tools.chunks(state["question"], "none")
        record = self._step_record(state, 0, "seed", {"query": state["question"], "parent": "none"},
                                   None, hits, trace, time.perf_counter() - started, None)
        update: dict[str, Any] = {"steps": [record], "pending_hits": hits}
        if "clues" in self.features:
            update.update(self._extract_clues(state["question"]))
        return update

    def _extract_clues(self, question: str) -> dict[str, Any]:
        """v2 round 2: one question-only call splits the question into clues
        (frozen for the whole run) and, for questions that describe their
        answer by properties, category-style facets. The planner, asked to do
        this inside its own reply, bundled Q009's earthquake clue and never
        used facets. With facets, one graph facet search runs automatically
        before the first planner turn, outside the planned-step budget."""
        messages = [SystemMessage(content=CLUES_SYSTEM), HumanMessage(content=question)]
        raw, usage = adv.invoke_measured(self.clue_llm, messages)
        log(f"CLUES {question[:60]}", raw)
        try:
            reply = adv._json_object(raw)
        except (ValueError, json.JSONDecodeError):
            reply = {}
        def strings(key: str) -> list[str]:
            value = reply.get(key)
            return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []
        # Indirectly given values come first: each must be found before the
        # clues that depend on it can be checked.
        clues = list(dict.fromkeys(strings("indirect") + strings("clues")))
        facets = [str(f).strip() for f in reply.get("facets", []) if str(f).strip()] if isinstance(reply.get("facets"), list) else []
        update: dict[str, Any] = {"clues": clues, "usage": [{**usage, "role": "clues", "model": self.planner_model}]}
        if len(facets) >= 2 and "facets" in self.features:
            update["next_action"] = {
                "action": "graph",
                "args": {"query": question, "relations": ["category"], "facets": facets[:FACET_MAX]},
                "assessment": "[agent: facet search from the question's properties]",
                "missing": [], "clues": clues, "facts": [], "auto": True,
            }
            update["auto_facets_pending"] = True
        return update

    def fuse(self, state: AgentState) -> dict[str, Any]:
        # Keyed by the step's position, which is unique; step numbers are not
        # (the automatic facet search shares number 0 with the seed).
        step_key = len(state["steps"]) - 1
        hits = state["pending_hits"]
        evidence = {unit_id: dict(entry) for unit_id, entry in state["evidence"].items()}
        for rank, hit in enumerate(hits, 1):
            entry = evidence.get(hit.unit_id)
            if entry is None:
                entry = {"hit": hit, "rrf": 0.0, "first_step": step_key, "step_ranks": {}}
                evidence[hit.unit_id] = entry
            if step_key not in entry["step_ranks"]:
                entry["step_ranks"] = {**entry["step_ranks"], step_key: rank}
                entry["rrf"] += 1.0 / (RRF_K + rank)
        update: dict[str, Any] = {"pending_hits": [], "evidence": evidence, "context": self._assemble(evidence)}
        if state["planned_steps"] >= MAX_PLANNED_STEPS:
            update["stop_reason"] = "step_budget"
        return update

    def _assemble(self, evidence: dict[str, EvidenceEntry]) -> list[Hit]:
        """Each step's top STEP_GUARANTEE units first, then by fused rank, up
        to CONTEXT_BUDGET characters; units wholly covered by an earlier
        (usually wider) unit are skipped."""
        by_rrf = sorted(evidence.values(), key=lambda entry: entry["rrf"], reverse=True)
        guaranteed = [
            entry for entry in by_rrf
            if any(rank <= STEP_GUARANTEE for rank in entry["step_ranks"].values())
        ]
        guaranteed_ids = {entry["hit"].unit_id for entry in guaranteed}
        ordered = guaranteed + [entry for entry in by_rrf if entry["hit"].unit_id not in guaranteed_ids]
        chosen: list[EvidenceEntry] = []
        covered: set[int] = set()
        remaining = CONTEXT_BUDGET
        for entry in ordered:
            hit = entry["hit"]
            positions = self.tools.positions(hit)
            if positions and positions <= covered:
                continue
            if len(hit.text) > remaining:
                continue
            chosen.append(entry)
            covered |= positions
            remaining -= len(hit.text)
        chosen.sort(key=lambda entry: entry["rrf"], reverse=True)
        return [entry["hit"] for entry in chosen]

    def plan(self, state: AgentState) -> dict[str, Any]:
        messages = [
            SystemMessage(content=planner_system(self.version, self.features)),
            HumanMessage(content=self._planner_message(state)),
        ]
        usages: list[dict[str, Any]] = []
        retries = 0
        frozen = list(state["clues"])
        while True:
            raw, usage = adv.invoke_measured(self.planner_llm, messages)
            usages.append({**usage, "role": "plan", "model": self.planner_model})
            log(f"PLAN {state['question'][:60]}", raw)
            update = self._interpret(raw, state)
            planned = update["next_action"]
            if "clues" in self.features and (planned.get("clues") or frozen):
                # Applied even when the reply omits "clues", so the frozen list
                # is always what the coverage check uses.
                # v2 round 2: the first reply's clues are frozen; later replies
                # can only append, and each fact's clue number is mapped onto
                # the frozen list by the clue's text. On Q009 the planner split
                # the earthquake clue at one step and merged it back at the next.
                frozen, planned["facts"] = _align_clues(frozen, planned["clues"], planned["facts"])
                planned["clues"] = list(frozen)
            # v2: an answer must give every clue of the question at least one
            # fact whose quote is verified against the evidence. The first
            # answer that falls short is sent back with the problems named.
            # `missing` is not checked: the planner fills it with hedges
            # ("a passage explicitly linking ...") even when every clue is
            # already covered, and chasing those wasted Q009's steps.
            if self.version == "v2" and planned["action"] == "answer" and update.get("stop_reason") == "planner_answer":
                planned["facts"] = _verify_facts(planned["facts"], state["context"])
                failures = [fact for fact in planned["facts"] if not fact["verified"]]
                uncovered = _uncovered_clues(planned["clues"], planned["facts"])
                if (failures or uncovered or not planned["clues"]) and retries == 0:
                    retries += 1
                    log("VERIFY", json.dumps({"failures": failures, "uncovered": uncovered}, ensure_ascii=False))
                    feedback = []
                    if failures:
                        feedback.append(VERIFY_FACTS_FEEDBACK.format(failures="\n".join(
                            f"- {fact['fact']} [{fact['source']}] \"{fact['quote']}\": {fact['reason']}"
                            for fact in failures
                        )))
                    if uncovered:
                        feedback.append(VERIFY_CLUES_FEEDBACK.format(clues="\n".join(f"- {clue}" for clue in uncovered)))
                    if not planned["clues"]:
                        feedback.append('You gave no "clues". List every condition the question sets.')
                    feedback.append(VERIFY_CLOSING)
                    messages += [AIMessage(content=raw), HumanMessage(content="\n\n".join(feedback))]
                    continue
                if uncovered:
                    # Told once, the planner still answers with a clue
                    # unsupported. Search for that clue while steps remain; its
                    # wording comes from the question, so it adds nothing from
                    # the planner's memory. The next plan call re-checks.
                    search: PlannedAction = {
                        "action": "chunks",
                        "args": {"query": uncovered[0][:300], "parent": "none"},
                        "assessment": planned["assessment"] + " [agent: searching for an unsupported clue]",
                        "missing": planned["missing"], "clues": planned["clues"], "facts": planned["facts"],
                    }
                    if self._signature("chunks", search["args"]) not in {
                        self._signature(step["action"], step["args"]) for step in state["steps"]
                    }:
                        log("CLUE SEARCH", uncovered[0])
                        update = {"next_action": search, "stop_reason": None}
                        break
                if failures or uncovered:
                    update["stop_reason"] = "unverified_answer"
            break
        update["usage"] = usages
        if "clues" in self.features and frozen:
            update["clues"] = frozen
        if retries:
            update["verification_retries"] = state["verification_retries"] + retries
        return update

    def _interpret(self, raw: str, state: AgentState) -> dict[str, Any]:
        """Parse one planner reply and apply the guards; always returns a
        next_action, forcing answer when a guard trips."""
        try:
            reply = _planner_json(raw)
        except ValueError:
            reply = _args_only_reply(raw) if self.version == "v2" else None
            if reply is None:
                return self._force_answer("parse_failure", raw[:200])
            log("INFERRED ACTION", json.dumps(reply, ensure_ascii=False))
        action = str(reply.get("action", "")).strip()
        args = reply.get("args") if isinstance(reply.get("args"), dict) else {}
        planned: PlannedAction = {
            "action": action, "args": args,
            "assessment": str(reply.get("assessment", "")),
            "missing": [str(gap) for gap in reply.get("missing", []) if gap] if isinstance(reply.get("missing"), list) else [],
            "clues": [str(clue) for clue in reply.get("clues", []) if clue] if isinstance(reply.get("clues"), list) else [],
            "facts": _parse_facts(reply.get("facts")),
        }
        if action not in ACTIONS_BY_VERSION[self.version]:
            return self._force_answer("unknown_action", planned["assessment"], planned)
        if action == "answer":
            return {"next_action": planned, "stop_reason": "planner_answer"}
        if action == "clarify" and state["clarify_count"] >= MAX_CLARIFY:
            return self._force_answer("clarify_limit", planned["assessment"], planned)
        planned["args"] = self._normalise_args(action, args, state["question"])
        if action in RETRIEVAL_ACTIONS and self._signature(action, planned["args"]) in {
            self._signature(step["action"], step["args"]) for step in state["steps"]
        }:
            return self._force_answer("repeat_action", planned["assessment"], planned)
        return {"next_action": planned}

    @staticmethod
    def _force_answer(reason: str, note: str, planned: PlannedAction | None = None) -> dict[str, Any]:
        action: PlannedAction = {
            "action": "answer", "args": {},
            "assessment": (planned or {}).get("assessment", note),
            "missing": (planned or {}).get("missing", []),
            "clues": (planned or {}).get("clues", []),
            "facts": (planned or {}).get("facts", []),
        }
        log("GUARD", f"{reason}: {note}")
        return {"next_action": action, "stop_reason": reason}

    @staticmethod
    def _normalise_args(action: str, args: dict[str, Any], question: str) -> dict[str, Any]:
        query = str(args.get("query") or question).strip()
        if action == "chunks":
            parent = str(args.get("parent", "none"))
            return {"query": query, "parent": parent if parent in adv.PARENT_MODES else "none"}
        if action == "decompose":
            return {"query": query}
        if action == "graph":
            relations = [r for r in args.get("relations", []) if r in GRAPH_RELATIONS] if isinstance(args.get("relations"), list) else []
            normalised = {"query": query, "relations": relations or list(GRAPH_RELATIONS)}
            facets = [str(f).strip() for f in args.get("facets", []) if str(f).strip()] if isinstance(args.get("facets"), list) else []
            if facets:
                normalised["facets"] = facets[:FACET_MAX]
            return normalised
        if action == "title_search":
            return {"pattern": str(args.get("pattern", "")), "query": query}
        if action == "read_section":
            return {"file": str(args.get("file", "")), "section": str(args.get("section", "")), "query": query}
        if action == "clarify":
            interpretations = args.get("interpretations") if isinstance(args.get("interpretations"), list) else []
            return {"question": str(args.get("question", "")), "interpretations": [str(i) for i in interpretations]}
        return args

    @staticmethod
    def _signature(action: str, args: dict[str, Any]) -> str:
        name = "chunks" if action == "seed" else action
        normalised = {key: (value.strip().casefold() if isinstance(value, str) else value) for key, value in args.items()}
        if isinstance(normalised.get("relations"), list):
            normalised["relations"] = sorted(normalised["relations"])
        return name + json.dumps(normalised, sort_keys=True)

    def _run_tool(self, state: AgentState, action: str, call) -> dict[str, Any]:
        planned = state["next_action"]
        started = time.perf_counter()
        usage: list[dict[str, Any]] = []
        error = None
        try:
            result = call(planned["args"])
            if len(result) == 3:
                hits, trace, call_usage = result
                usage.append({**call_usage, "role": "decompose"})
            else:
                hits, trace = result
        except re.error as exc:
            hits, trace, error = [], {}, f"invalid regular expression: {exc}"
        if trace.get("error"):                  # a tool that reports its own failure
            trace = dict(trace)
            error = trace.pop("error")
        seconds = time.perf_counter() - started - sum(
            float(u["latency_seconds"]) + float(u.get("throttle_seconds", 0.0)) for u in usage
        )
        auto = bool(planned.get("auto"))        # the free facet search after the seed
        step_number = state["planned_steps"] + (0 if auto else 1)
        record = self._step_record(state, step_number, action, planned["args"], planned,
                                   hits, trace, seconds, error)
        update = {"steps": [record], "planned_steps": step_number, "usage": usage, "pending_hits": hits}
        if auto:
            update["auto_facets_pending"] = False
        return update

    def chunks_node(self, state: AgentState) -> dict[str, Any]:
        return self._run_tool(state, "chunks", lambda a: self.tools.chunks(
            a["query"], a["parent"], self.version == "v2", h2_sections="sections" in self.features))

    def decompose_node(self, state: AgentState) -> dict[str, Any]:
        return self._run_tool(state, "decompose", lambda a: self.tools.decompose(self.llm, a["query"], decompose_system(self.version)))

    def graph_node(self, state: AgentState) -> dict[str, Any]:
        def call(a: dict[str, Any]):
            if a.get("facets") and "facets" in self.features:          # v2 round 2
                return self.tools.graph_facets(a["facets"], a["query"])
            return self.tools.graph_expand(a["query"], a["relations"])
        return self._run_tool(state, "graph", call)

    def title_search_node(self, state: AgentState) -> dict[str, Any]:
        return self._run_tool(state, "title_search", lambda a: self.tools.title_search(a["pattern"], a["query"]))

    def read_section_node(self, state: AgentState) -> dict[str, Any]:
        return self._run_tool(state, "read_section",
                              lambda a: self.tools.read_section(a["file"], a["section"], a["query"]))

    def clarify_node(self, state: AgentState) -> dict[str, Any]:
        planned = state["next_action"]
        question = planned["args"].get("question") or "Which one do you mean?"
        interpretations = planned["args"].get("interpretations", [])
        if state["mode"] == "chat":
            print(f"\nAgent asks: {question}")
            for number, option in enumerate(interpretations, 1):
                print(f"  {number}. {option}")
            reply = input("Your answer: ").strip()
            if reply.isdigit() and 1 <= int(reply) <= len(interpretations):
                reply = interpretations[int(reply) - 1]
            note = f"{question} -> {reply}" if reply else f"{question} -> (no reply)"
        else:
            note = (
                f"{question} -> no user was available (batch mode); interpretations: "
                + " | ".join(interpretations)
            )
        record: StepRecord = {
            "step": state["planned_steps"], "action": "clarify", "args": planned["args"],
            "assessment": planned["assessment"], "missing": planned["missing"],
            "clues": planned.get("clues", []), "facts": planned.get("facts", []), "ranked_unit_ids": [], "new_unit_ids": [], "files": [], "trace": {"clarification": note},
            "seconds": 0.0, "error": None,
        }
        return {"steps": [record], "clarifications": [note], "clarify_count": state["clarify_count"] + 1}

    def answer_node(self, state: AgentState) -> dict[str, Any]:
        if not self.answer_enabled:
            return {"response": ""}
        hits = state["context"]
        if not hits:
            return {"response": "(no documents retrieved)"}
        parts = [f"Documents:\n{adv._format_context(hits)}"]
        if state["history"]:
            parts.append(self._history_text(state["history"]))
        if state["clarifications"]:
            parts.append("Clarifications:\n" + "\n".join(f"- {note}" for note in state["clarifications"]))
        if "clues" in self.features and state["clues"]:
            # v2 round 2: the frozen clues as a checklist, so every part of the
            # question is answered (Q009 dropped one of Sartre's two reasons).
            parts.append("The answer must address each of these parts of the question:\n"
                         + "\n".join(f"- {clue}" for clue in state["clues"]))
        parts.append(f"Question: {state['question']}")
        messages = [SystemMessage(content=answer_system(self.version)), HumanMessage(content="\n\n".join(parts))]
        response, usage = adv.invoke_measured(self.answer_llm, messages)
        return {"response": response, "usage": [{**usage, "role": "answer", "model": self.answer_model}]}

    # --------------------------------------------------------------- helpers
    def _step_record(self, state: AgentState, step: int, action: str, args: dict[str, Any],
                     planned: PlannedAction | None, hits: list[Hit], trace: dict[str, Any],
                     seconds: float, error: str | None) -> StepRecord:
        seen_files = {entry["hit"].source_file for entry in state["evidence"].values()}
        files = list(dict.fromkeys(hit.source_file for hit in hits))
        return {
            "step": step, "action": action, "args": args,
            "assessment": planned["assessment"] if planned else "",
            "missing": planned["missing"] if planned else [],
            "clues": planned.get("clues", []) if planned else [],
            "facts": planned.get("facts", []) if planned else [],
            "ranked_unit_ids": [hit.unit_id for hit in hits],
            "new_unit_ids": [hit.unit_id for hit in hits if hit.unit_id not in state["evidence"]],
            "files": files,
            "trace": {**trace, "new_files": [file for file in files if file not in seen_files]},
            "seconds": round(max(seconds, 0.0), 3),
            "error": error,
        }

    @staticmethod
    def _history_text(history: list[tuple[str, str]]) -> str:
        return "Earlier in this conversation:\n" + "\n".join(
            f"Q: {question}\nA: {answer[:600]}" for question, answer in history
        )

    def _planner_message(self, state: AgentState) -> str:
        lines = [f"Question: {state['question']}"]
        if state["history"]:
            lines.append(self._history_text(state["history"]))
        lines.append("Clarifications: " + ("; ".join(state["clarifications"]) or "(none)"))
        if "clues" in self.features and state["clues"]:
            lines.append("Clues (fixed before your first turn; repeat them exactly, in this order, and "
                         "number facts by them; you may only append new ones):")
            lines.extend(f"  {number}. {clue}" for number, clue in enumerate(state["clues"], 1))
        lines.append(f"Planned retrieval steps used: {state['planned_steps']} of {MAX_PLANNED_STEPS}")
        lines.append("\nActions taken:")
        for step in state["steps"]:
            args = json.dumps(step["args"], ensure_ascii=False)
            if step["action"] == "clarify":
                lines.append(f"{step['step']}. clarify {args} -> {step['trace'].get('clarification')}")
                continue
            new_files = step["trace"].get("new_files", [])
            fresh = f"{len(step['new_unit_ids'])} new, " if self.version == "v2" else ""   # v2: shows a repeat read that added nothing
            lines.append(
                f"{step['step']}. {step['action']} {args} -> {len(step['ranked_unit_ids'])} passages ({fresh}"
                f"{len(new_files)} new files): {step['files'][:8]}"
                if self.version == "v2" else
                f"{step['step']}. {step['action']} {args} -> {len(step['ranked_unit_ids'])} passages, "
                f"{len(new_files)} new files: {step['files'][:8]}"
            )
            if step["trace"].get("sub_queries"):
                lines.append(f"   sub-queries: {step['trace']['sub_queries']}")
            if step["trace"].get("article_too_long"):
                lines.append(f"   (too long to read whole, read lead + section instead: {step['trace']['article_too_long']})")
            if step["error"]:
                lines.append(f"   (error: {step['error']})")
        context = state["context"]
        context_chars = sum(len(hit.text) for hit in context)
        lines.append(
            f"\nEvidence ({len(context)} passages, {context_chars:,} chars, ordered by fused rank; "
            f"first {PLANNER_EVIDENCE_CHARS:,} chars shown):"
        )
        # v2 labels each passage with its section so read_section can name it;
        # v1 sees exactly what the answerer sees.
        label = self._section_labelled if self.version == "v2" else None
        lines.append(_truncate_context(context, PLANNER_EVIDENCE_CHARS, label))
        return "\n".join(lines)

    def _section_labelled(self, hit: Hit) -> str:
        positions = sorted(self.tools.positions(hit), key=lambda p: self.tools.expander.chunk_index_of[p])
        if not positions:
            return hit.label
        sections = list(dict.fromkeys(self.tools.section_label(p) for p in positions))
        where = f"[{hit.source_file} § {' / '.join(sections)}]"
        return where if hit.role == "primary" else f"{where} ({hit.role})"


def _parse_facts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    facts = []
    for fact in value:
        if not isinstance(fact, dict):
            continue
        try:
            clue = int(fact.get("clue"))
        except (TypeError, ValueError):
            clue = None
        facts.append({"clue": clue, "fact": str(fact.get("fact", "")),
                      "source": str(fact.get("source", "")), "quote": str(fact.get("quote", ""))})
    return facts


def _args_only_reply(raw: str) -> dict[str, Any] | None:
    """v2: a reply that is only an args object (seen on Q003 and Q009) is
    read as the action its keys identify unambiguously; anything else is
    still a parse failure."""
    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start < 0:
        return None
    try:
        args, _end = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        return None
    if not isinstance(args, dict):
        return None
    keys = set(args)
    if "pattern" in keys:
        action = "title_search"
    elif {"file", "section"} <= keys:
        action = "read_section"
    elif keys & {"facets", "relations"}:
        action = "graph"
    elif "query" in keys and "parent" in keys:
        action = "chunks"
    else:
        return None
    return {"action": action, "args": args, "assessment": "[agent: action inferred from an args-only reply]",
            "missing": [], "facts": []}


def _clue_key(clue: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", clue.casefold()).strip()


def _align_clues(frozen: list[str], reply_clues: list[str],
                 facts: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    """Merge a reply's clues into the frozen list (unknown ones are appended,
    none are dropped or merged) and renumber the reply's facts by the merged
    list, matching each fact's clue through its text."""
    merged = list(frozen)
    keys = [_clue_key(clue) for clue in merged]
    for clue in reply_clues:
        if _clue_key(clue) not in keys:
            merged.append(clue)
            keys.append(_clue_key(clue))
    aligned = []
    reference = reply_clues or frozen     # no list in the reply: its numbers refer to the frozen one
    for fact in facts:
        number = fact.get("clue")
        text = reference[number - 1] if isinstance(number, int) and 1 <= number <= len(reference) else None
        aligned.append({**fact, "clue": keys.index(_clue_key(text)) + 1 if text is not None else None})
    return merged, aligned


def _uncovered_clues(clues: list[str], facts: list[dict[str, Any]]) -> list[str]:
    """Clues (numbered from 1) with no verified fact."""
    covered = {fact["clue"] for fact in facts if fact.get("verified") and fact.get("clue") is not None}
    return [clue for number, clue in enumerate(clues, 1) if number not in covered]


_INLINE_TAG = re.compile(r"<(?!/?sup\b)[^>]+>", re.IGNORECASE)   # <sub>, <br>, <i> ...; <sup> blocks are cites
_ELLIPSIS = re.compile(r"\.\.\.|…")


def _match_form(text: str) -> str:
    """The 4.1 evidence matcher's normalisation, after dropping inline HTML
    tags it keeps as letters ('M<sub>w</sub>' would otherwise not match 'Mw')."""
    return adv._normalize_for_match(_INLINE_TAG.sub("", text))


def _verify_facts(facts: list[dict[str, Any]], context: list[Hit]) -> list[dict[str, Any]]:
    """A fact is verified when its quote appears in the cited file's passages
    in the context (markup, reference markers, whitespace and case ignored;
    a quote elided with '...' must match fragment by fragment, in order).
    This checks the quote is real and correctly attributed; whether it
    supports the fact is left to the planner."""
    text_by_file: dict[str, list[str]] = defaultdict(list)
    for hit in context:
        text_by_file[hit.source_file.casefold()].append(hit.text)
    normalised: dict[str, str] = {}
    checked = []
    for fact in facts:
        source = Path(fact["source"].strip().strip("[]").strip()).name.casefold()
        fragments = [part for part in (_match_form(piece) for piece in _ELLIPSIS.split(fact["quote"])) if part]
        short = re.sub(r"[*_`\s]", "", fact["quote"]).casefold()
        if source not in text_by_file:
            verified, reason = False, "source is not in the evidence"
        elif not short:
            verified, reason = False, "no quote given"
        elif sum(len(part) for part in fragments) < 4:
            # A short table cell ("41", "Falun"), which rule 6 asks for. It
            # would match inside almost anything, so it must stand alone as a
            # token in the cited file rather than appear as a substring.
            plain = re.sub(r"[*_`]", "", " ".join(text_by_file[source])).casefold()
            verified = re.search(rf"(?<![0-9a-z]){re.escape(short)}(?![0-9a-z])", plain) is not None
            reason = "" if verified else "short quote not found as a standalone value in that source"
        else:
            if source not in normalised:
                normalised[source] = _match_form(" ".join(text_by_file[source]))
            text, position, verified = normalised[source], 0, True
            for part in fragments:
                found = text.find(part, position)
                if found < 0:
                    verified = False
                    break
                position = found + len(part)
            reason = "" if verified else "quote not found in that source"
        checked.append({**fact, "verified": verified, "reason": reason})
    return checked


def _planner_json(raw: str) -> dict[str, Any]:
    """The planner's JSON reply. Tolerates code fences and extra objects (the
    model sometimes echoes an args object first): the first object with an
    "action" key wins."""
    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _end = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "action" in value:
            return value
    raise ValueError(f"planner reply has no JSON object with an action: {raw[:200]!r}")


def _truncate_context(hits: list[Hit], limit: int, label=None) -> str:
    parts: list[str] = []
    remaining = limit
    for hit in hits:
        block = f"{label(hit) if label else hit.label} {hit.text}"
        if len(block) > remaining:
            if remaining > 200:
                parts.append(block[:remaining] + " ...")
            break
        parts.append(block)
        remaining -= len(block) + 2
    return "\n\n".join(parts) or "(none yet)"


# %% [markdown]
# ## v0: the fixed baseline pipeline (Checkpoint 3.1 retriever, as run in 4.1)

# %%
class BaselinePipeline:
    """The worksheet's fixed-pipeline comparison point: one retrieval over
    whole articles (text from extract_wikipedia_text(), BM25 + vector fusion,
    top 3 of a pool of 10) and one answer with the 4.1 ANSWER_SYSTEM, using
    the 4.1 module's own baseline retriever and answer(). No planner, no
    loop, no clarify, no memory between chat turns. run() returns an
    AgentState-shaped dict so the evaluation, metrics and printing code
    treat it exactly like the agents."""

    version = "v0"

    def __init__(self, llm: ChatOpenAI, answer_enabled: bool = True):
        self.llm = llm
        self.answer_enabled = answer_enabled
        self.retriever = adv.build_retriever("baseline")

    def run(self, question: str, mode: str = "batch", history: list[tuple[str, str]] | None = None) -> AgentState:
        started = time.perf_counter()
        hits, trace = self.retriever.retrieve(question)
        seconds = time.perf_counter() - started
        step: StepRecord = {
            "step": 0, "action": "seed",
            "args": {"query": question, "retriever": "baseline", "top_k": BASELINE_TOP_K},
            "assessment": "", "missing": [], "clues": [], "facts": [],
            "ranked_unit_ids": [hit.unit_id for hit in hits],
            "new_unit_ids": [hit.unit_id for hit in hits],
            "files": list(dict.fromkeys(hit.source_file for hit in hits)),
            "trace": {**trace, "new_files": list(dict.fromkeys(hit.source_file for hit in hits))},
            "seconds": round(seconds, 3), "error": None,
        }
        usage: list[dict[str, Any]] = []
        response = ""
        if self.answer_enabled:
            if hits:
                response, answer_usage = adv.answer(self.llm, question, hits)
                usage.append({**answer_usage, "role": "answer"})
            else:
                response = "(no documents retrieved)"
        return {
            "question": question, "mode": mode, "version": "v0", "history": list(history or []),
            "next_action": None, "steps": [step], "planned_steps": 0, "clarify_count": 0, "clues": [], "features": [], "auto_facets_pending": False,
            "clarifications": [], "stop_reason": "fixed_pipeline", "verification_retries": 0,
            "pending_hits": [],
            "evidence": {hit.unit_id: {"hit": hit, "rrf": 1.0 / (RRF_K + rank), "first_step": 0,
                                       "step_ranks": {0: rank}} for rank, hit in enumerate(hits, 1)},
            "context": hits, "response": response, "usage": usage,
        }


# %% [markdown]
# ## Agent metrics

# %%
def agent_metrics(item: dict[str, Any] | None, state: AgentState) -> dict[str, Any]:
    usage = state["usage"]
    by_role = defaultdict(list)
    for entry in usage:
        by_role[entry["role"]].append(entry)
    retrieval_steps = [step for step in state["steps"] if step["action"] != "clarify"]
    actions = []
    for step in state["steps"]:
        name = step["action"]
        if name == "chunks" and step["args"].get("parent", "none") != "none":
            name += ":" + step["args"]["parent"]
        if name == "graph":
            name += ":" + "+".join(step["args"].get("relations", []))
        actions.append(name)
    actions.append("answer")
    all_hits = [entry["hit"] for entry in state["evidence"].values()]
    final = state["next_action"] or {}
    answer_facts = final.get("facts", []) if final.get("action") == "answer" else []
    metrics: dict[str, Any] = {
        "agent_version": state["version"],
        "agent_features": state.get("features", []),
        "frozen_clues": state.get("clues", []),
        "agent_actions": actions,
        "planned_steps": state["planned_steps"],
        "stop_reason": state["stop_reason"],
        "seed_only_answer": len(retrieval_steps) == 1,
        "planner_calls": len(by_role["plan"]),
        "tool_llm_calls": len(by_role["decompose"]) + len(by_role["clues"]),   # decompose + v2 clue step
        "llm_calls_total": len(usage),
        "planner_input_tokens": sum(int(u["input_tokens"]) for u in by_role["plan"]),
        "planner_output_tokens": sum(int(u["output_tokens"]) for u in by_role["plan"]),
        "planner_latency_seconds": sum(float(u["latency_seconds"]) for u in by_role["plan"]),
        "clarify_used": any(step["action"] == "clarify" for step in state["steps"]),
        "clarifications": state["clarifications"],
        "verification_retries": state["verification_retries"],
        "answer_facts": answer_facts,
        "answer_facts_verified": sum(bool(fact.get("verified")) for fact in answer_facts),
        "answer_missing": final.get("missing", []) if final.get("action") == "answer" else [],
        "answer_clues": final.get("clues", []) if final.get("action") == "answer" else [],
        "answer_clues_uncovered": (
            _uncovered_clues(final.get("clues", []), answer_facts) if final.get("action") == "answer" else []
        ),
        "units_retrieved_total": len(all_hits),
        "units_in_context": len(state["context"]),
        "agent_steps": state["steps"],
    }
    if item is not None:
        metrics["source_recall_any_step"] = adv._source_metrics(
            item["required_sources"], item["expected_sources"], all_hits,
        )["source_recall_at_k"]
        metrics["evidence_recall_any_step"] = adv._evidence_recall(item["supporting_quotes"], all_hits)
    return metrics


def _print_trace(state: AgentState) -> None:
    for step in state["steps"]:
        args = json.dumps(step["args"], ensure_ascii=False)
        print(f"  [{step['step']}] {step['action']} {args}")
        if step["assessment"]:
            print(f"      assessment: {step['assessment']}")
        if step["missing"]:
            print(f"      missing: {step['missing']}")
        if step["action"] == "clarify":
            print(f"      -> {step['trace'].get('clarification')}")
        else:
            print(f"      -> {len(step['ranked_unit_ids'])} units, new files: {step['trace'].get('new_files')}")
            if step["trace"].get("facets"):
                print(f"      facets met by: {step['trace'].get('all_facets_met', [])[:6]} "
                      f"(strictness level {step['trace'].get('strictness_level')})")
        if step["error"]:
            print(f"      error: {step['error']}")
    final = state["next_action"]
    if final and final["action"] == "answer" and final.get("assessment"):
        print(f"  [answer] assessment: {final['assessment']}")
    for fact in (final or {}).get("facts", []) if (final or {}).get("action") == "answer" else []:
        mark = {True: "verified", False: f"UNVERIFIED ({fact.get('reason')})"}.get(fact.get("verified"), "unchecked")
        print(f"      fact: {fact['fact']} [{fact['source']}] - {mark}")
    if state["verification_retries"]:
        print(f"  verification retries: {state['verification_retries']}")
    print(f"  stop_reason={state['stop_reason']}  context={len(state['context'])} units, "
          f"{sum(len(hit.text) for hit in state['context']):,} chars")


# %% [markdown]
# ## Evaluation (4.1 judges and metrics on the agent's final context)

# %%
def _evaluate_item(agent: WikipediaAgent, llm: ChatOpenAI, item: dict[str, Any],
                   judge_repeats: int = 1) -> tuple[dict[str, Any], AgentState]:
    started = time.perf_counter()
    state = agent.run(item["question"], mode="batch")
    wall_seconds = time.perf_counter() - started
    hits = state["context"]
    response = state["response"]
    retrieved_context = adv._format_context(hits)
    retrieval_seconds = sum(step["seconds"] for step in state["steps"])
    answer_llm = getattr(agent, "answer_llm", llm)
    closed_book_response, closed_book_usage = adv.answer_closed_book(answer_llm, item["question"])
    closed_book_usage = {**closed_book_usage, "model": getattr(agent, "answer_model", adv.LLM_MODEL)}
    quality, quality_usage = adv.judge(
        llm, response, item["expected_answer"], item["required_aspects"], retrieved_context,
    )
    # Extra correctness verdicts on the same response and context. The first
    # verdict stays in the 4.1 fields; the repeats measure judge noise and
    # give a majority vote. Their tokens are kept out of the cost totals so
    # cost stays comparable with 4.1.
    votes = [quality]
    rejudge_tokens = [0, 0]
    for _ in range(judge_repeats - 1):
        extra, extra_usage = adv.judge(
            llm, response, item["expected_answer"], item["required_aspects"], retrieved_context,
        )
        votes.append(extra)
        rejudge_tokens[0] += int(extra_usage["input_tokens"])
        rejudge_tokens[1] += int(extra_usage["output_tokens"])
    claim_judgment, claim_usage = adv.judge_claims(llm, response, retrieved_context, closed_book_response)
    refusal_outcome, refusal_usage = adv.judge_refusal_behavior(llm, item, response, retrieved_context)
    citation_metrics = adv._citation_metrics(response, hits, item["expected_sources"])
    agent_usage = state["usage"]
    judge_usages = (closed_book_usage, quality_usage, claim_usage, refusal_usage)
    usages = list(agent_usage) + list(judge_usages)
    answer_usage = next((u for u in agent_usage if u["role"] == "answer"), {"latency_seconds": 0.0})
    input_tokens = sum(int(usage["input_tokens"]) for usage in usages)
    output_tokens = sum(int(usage["output_tokens"]) for usage in usages)
    total_latency = sum(float(usage["latency_seconds"]) for usage in usages) + retrieval_seconds
    result = {
        "id": item["id"],
        "question": item["question"],
        "retriever": f"agent_{agent.version}",
        "group": item.get("group"),
        "source_suite": item.get("source_suite"),
        "mechanism": item.get("mechanism"),
        "information_need": item["information_need"],
        "motivation": item["motivation"],
        "prior_familiarity": item["prior_familiarity"],
        "scope": item["scope"],
        "answerable": item["answerable"],
        "adversarial_kind": item.get("adversarial_kind"),
        "required_sources": item["required_sources"],
        "expected_sources": item["expected_sources"],
        **adv._retrieval_record(item, hits, {"steps": state["steps"]}, retrieval_seconds),
        "required_aspects": item["required_aspects"],
        "response": response,
        "closed_book_response": closed_book_response,
        **quality,
        **claim_judgment,
        **citation_metrics,
        "refusal_outcome": refusal_outcome,
        "answer_latency_seconds": answer_usage["latency_seconds"],
        "judge_latency_seconds": (
            float(quality_usage["latency_seconds"])
            + float(claim_usage["latency_seconds"])
            + float(refusal_usage["latency_seconds"])
        ),
        "total_latency_seconds": total_latency,
        "agent_wall_seconds": wall_seconds,
        "throttle_seconds": sum(float(usage.get("throttle_seconds", 0.0)) for usage in usages),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "estimated_cost_usd": _usage_cost(usages),
        "planner_model": agent.planner_model if isinstance(agent, WikipediaAgent) else None,
        "answer_model": agent.answer_model if isinstance(agent, WikipediaAgent) else adv.LLM_MODEL,
        "reasoning_effort": getattr(agent, "reasoning_effort", None),
        "answer_cost_usd": _usage_cost([u for u in list(agent_usage) + [closed_book_usage] if u.get("role") == "answer" or u is closed_book_usage]),
        "planner_cost_usd": _usage_cost([u for u in agent_usage if u.get("role") in ("plan", "clues")]),
        "judge_votes": [vote["correctness"] for vote in votes],
        "graded_correctness_votes": [vote["graded_correctness_score"] for vote in votes],
        "correctness_majority": (
            "pass" if sum(vote["correctness"] == "pass" for vote in votes) * 2 > len(votes) else "fail"
        ),
        "graded_correctness_mean": sum(float(vote["graded_correctness_score"]) for vote in votes) / len(votes),
        "rejudge_cost_usd": adv._estimated_cost_usd(*rejudge_tokens) if judge_repeats > 1 else 0.0,
        **agent_metrics(item, state),
    }
    return result, state


_RUN_FEATURES: list[str] = []     # set by main(): the v2 round-2 refinements on in this run
_RUN_PLANNER_MODEL: list[str] = []  # set by main() when --planner-model differs from adv.LLM_MODEL
_RUN_ANSWER_MODEL: list[str] = []   # set by main() when --answer-model differs from adv.LLM_MODEL
_RUN_REASONING: list[str] = []      # set by main() when --reasoning-effort is given
REASONING_MAX_TOKENS = 8192

# OpenRouter list prices, USD per million tokens (input, output), read from
# https://openrouter.ai/api/v1/models on 2026-09-29. The default model's rates
# come from .env as in 4.1; these cover calls made with --planner-model.
MODEL_PRICES = {
    "openai/gpt-5.4-mini": (0.75, 4.50),
    "openai/gpt-5.4": (2.50, 15.00),
    "anthropic/claude-haiku-4.5": (1.00, 5.00),
}


def _usage_cost(usages: list[dict[str, Any]]) -> float | None:
    """Estimated cost with each call priced at its own model's rates."""
    total = 0.0
    for usage in usages:
        model = usage.get("model", adv.LLM_MODEL)
        if model == adv.LLM_MODEL:
            cost = adv._estimated_cost_usd(int(usage["input_tokens"]), int(usage["output_tokens"]))
        elif model in MODEL_PRICES:
            rate_in, rate_out = MODEL_PRICES[model]
            cost = (int(usage["input_tokens"]) * rate_in + int(usage["output_tokens"]) * rate_out) / 1_000_000
        else:
            return None
        if cost is None:
            return None
        total += cost
    return total


def _run_label(version: str) -> str:
    """'v2' with every refinement on; 'v2-without-clues+facets' when some are disabled."""
    if version != "v2":
        return version
    off = [name for name in V2_FEATURES if name not in _RUN_FEATURES]
    label = version + ("-without-" + "+".join(off) if off else "")
    if _RUN_PLANNER_MODEL:
        label += "-planner-" + _RUN_PLANNER_MODEL[0].split("/")[-1]
    if _RUN_ANSWER_MODEL:
        label += "-answer-" + _RUN_ANSWER_MODEL[0].split("/")[-1]
    if _RUN_REASONING:
        label += "-reasoning-" + _RUN_REASONING[0]
    return label


def _configuration(version: str) -> dict[str, Any]:
    return {
        "run_label": _run_label(version),
        "planner_model": _RUN_PLANNER_MODEL[0] if _RUN_PLANNER_MODEL else adv.LLM_MODEL,
        "answer_model": _RUN_ANSWER_MODEL[0] if _RUN_ANSWER_MODEL else adv.LLM_MODEL,
        "judge_model": adv.LLM_MODEL,
        "reasoning_effort": _RUN_REASONING[0] if _RUN_REASONING else None,
        "v2_features": list(_RUN_FEATURES) if version == "v2" else None,
        "chunk_index": str(TABLES_CACHE_DIR.name if version == "v2" and "tables" in _RUN_FEATURES else adv.CHUNK_CACHE_DIR.name),
        "retriever": f"agent_{version}",
        "agent_version": version,
        "actions": sorted(ACTIONS_BY_VERSION[version]),
        "seed": (
            {"retriever": "baseline (whole articles)", "top_k": BASELINE_TOP_K, "candidate_pool": BASELINE_POOL}
            if version == "v0" else
            {"retriever": "chunks", "top_k": SEED_TOP_K, "candidate_pool": SEED_POOL, "parent": "none"}
        ),
        "max_planned_steps": MAX_PLANNED_STEPS,
        "max_clarify": MAX_CLARIFY,
        "planner_evidence_chars": PLANNER_EVIDENCE_CHARS,
        "context_budget_chars": CONTEXT_BUDGET,
        "rrf_k": RRF_K,
        "step_guarantee": STEP_GUARANTEE,
        "title_max_files": TITLE_MAX_FILES if version == "v2" else None,
        "weight_bm25": adv.WEIGHT_BM25,
        "weight_vector": adv.WEIGHT_VECTOR,
        "max_chunk_chars": adv.MAX_CHUNK_CHARS,
        "graph": {
            "seed_k": adv.GRAPH_SEED_K,
            "max_category_size": adv.GRAPH_MAX_CATEGORY_SIZE,
            "relation_weights": adv.GRAPH_RELATION_WEIGHTS,
        },
        "llm_model": adv.LLM_MODEL,
        "embedding_model": adv.EMBEDDING_MODEL,
        "temperature": adv.TEMPERATURE,
        "run_at": datetime.now().isoformat(timespec="seconds"),
    }


def _write_results(results: list[dict[str, Any]], output_path: Path, version: str) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps({"configuration": _configuration(version), "results": results},
                   ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    csv_path = output_path.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(results[0]))
        writer.writeheader()
        for result in results:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (list, dict)) else value
                for key, value in result.items()
            })
    return csv_path


class _SummaryShim:
    """Stands in for the 4.1 module's Retriever so its _print_summary can
    report the agent run with the exact 4.1 wording and formulas."""

    def __init__(self, version: str):
        self.mode = f"agent_{version}"
        self.top_k = BASELINE_TOP_K if version == "v0" else SEED_TOP_K
        self.candidate_pool = BASELINE_POOL if version == "v0" else SEED_POOL


def _print_summary(results: list[dict[str, Any]], version: str) -> None:
    previous = adv._retriever
    adv._retriever = _SummaryShim(version)
    try:
        adv._print_summary(results)
    finally:
        adv._retriever = previous
    mean = adv._mean
    print("-" * 72)
    print(f"Agent {version}: mean planned steps={mean(results, 'planned_steps'):.2f}  "
          f"mean model calls (excl. judges)={mean(results, 'llm_calls_total'):.2f}  "
          f"mean planner calls={mean(results, 'planner_calls'):.2f}")
    action_mix: dict[str, int] = defaultdict(int)
    stops: dict[str, int] = defaultdict(int)
    for result in results:
        for action in result["agent_actions"]:
            action_mix[action.split(":")[0]] += 1
        stops[str(result["stop_reason"])] += 1
    print(f"Action mix: {dict(sorted(action_mix.items()))}")
    print(f"Stop reasons: {dict(sorted(stops.items()))}")
    seed_only = sum(bool(result["seed_only_answer"]) for result in results)
    print(f"Answered from the seed alone: {seed_only}/{len(results)}")
    repeats = len(results[0].get("judge_votes", [])) if results else 0
    if repeats > 1:
        majority = sum(result["correctness_majority"] == "pass" for result in results)
        split = sum(len(set(result["judge_votes"])) > 1 for result in results)
        print(f"Judge repeats={repeats}: majority pass {majority}/{len(results)}, "
              f"mean graded {mean(results, 'graded_correctness_mean'):.3f}; "
              f"{split}/{len(results)} records got split verdicts")
    if version == "v2":
        retried = sum(1 for result in results if result["verification_retries"])
        facts = sum(len(result["answer_facts"]) for result in results)
        verified = sum(result["answer_facts_verified"] for result in results)
        print(f"Fact verification: {verified}/{facts} answer facts verified; "
              f"{retried}/{len(results)} answers sent back at least once")
    any_recall = mean(results, "source_recall_any_step")
    any_evidence = mean(results, "evidence_recall_any_step")
    if any_recall is not None:
        print(f"Mean source recall over everything retrieved: {any_recall:.1%} "
              f"(in final context: {mean(results, 'source_recall_at_k'):.1%})")
    if any_evidence is not None:
        print(f"Mean evidence recall over everything retrieved: {any_evidence:.1%} "
              f"(in final context: {(mean(results, 'evidence_recall') or 0):.1%})")
    latencies = sorted(float(result["total_latency_seconds"]) for result in results)
    if latencies:
        p50 = latencies[len(latencies) // 2]
        p90 = latencies[min(len(latencies) - 1, int(round(0.9 * (len(latencies) - 1))))]
        print(f"Latency p50={p50:.1f}s p90={p90:.1f}s (model + retrieval time, excluding throttle)")
    costs = [result["estimated_cost_usd"] for result in results]
    if all(cost is not None for cost in costs):
        print(f"Total estimated cost: ${sum(costs):.4f}  (mean ${sum(costs) / len(costs):.4f} per query)")


def _load_items(input_path: Path, ids: list[str] | None, limit: int | None) -> list[dict[str, Any]]:
    items = adv.my_eval_set(input_path)
    if ids:
        wanted = {identifier.strip() for identifier in ids}
        items = [item for item in items if item["id"] in wanted]
        missing = wanted - {item["id"] for item in items}
        if missing:
            raise SystemExit(f"ids not found in {input_path.name}: {sorted(missing)}")
    return items[:limit] if limit else items


def run_evaluation(agent: WikipediaAgent, llm: ChatOpenAI, items: list[dict[str, Any]], output_path: Path | None,
                   judge_repeats: int = 1) -> None:
    if output_path is None:
        output_path = RESULTS_DIR / f"evaluation_agent_{_run_label(agent.version)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    print(f"Checkpoint 5.1 - evaluation  |  scenario: {SCENARIO}  |  agent: {agent.version}  |  {len(items)} records\n")
    results: list[dict[str, Any]] = []
    for index, item in enumerate(items, 1):
        result, state = _evaluate_item(agent, llm, item, judge_repeats)
        results.append(result)
        adv._print_progress(item, result, state["context"], index, len(items))
        _print_trace(state)
        log(f"{item['id']}: {item['question']}", json.dumps(result, ensure_ascii=False, default=str))
        _write_results(results, output_path, agent.version)     # incremental save
    csv_path = _write_results(results, output_path, agent.version)
    _print_summary(results, agent.version)
    print(f"Results JSON: {output_path.resolve()}")
    print(f"Results CSV:  {csv_path.resolve()}")


def run_retrieval_only(agent: WikipediaAgent, items: list[dict[str, Any]], output_path: Path | None) -> None:
    """Run the agent's retrieval loop (planner included) without the answer
    model or judges. Planner calls still cost money, but only ~3 per query."""
    if output_path is None:
        output_path = RESULTS_DIR / f"retrieval_agent_{_run_label(agent.version)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    results: list[dict[str, Any]] = []
    for index, item in enumerate(items, 1):
        state = agent.run(item["question"], mode="batch")
        seconds = sum(step["seconds"] for step in state["steps"])
        record = {
            "id": item["id"],
            "question": item["question"],
            "retriever": f"agent_{agent.version}",
            "required_sources": item["required_sources"],
            "expected_sources": item["expected_sources"],
            **adv._retrieval_record(item, state["context"], {"steps": state["steps"]}, seconds),
            **agent_metrics(item, state),
        }
        results.append(record)
        print(f"{item['id']} ({index}/{len(items)}): {record['retrieved_sources']}")
        _print_trace(state)
        print(
            f"   recall@k={record['source_recall_at_k']:.2f} (any step {record['source_recall_any_step']:.2f}) "
            f"evidence={record['evidence_recall']} (any step {record['evidence_recall_any_step']}) "
            f"art_prec={record['article_precision']:.2f} context={record['context_chars']:,} chars"
        )
        _write_results(results, output_path, agent.version)
    mean = adv._mean
    print(
        f"\nMean recall@k={mean(results, 'source_recall_at_k'):.1%}  "
        f"strict={mean(results, 'source_recall_strict'):.1%}  "
        f"evidence recall={(mean(results, 'evidence_recall') or 0):.1%}  "
        f"article precision={mean(results, 'article_precision'):.1%}  "
        f"mean planned steps={mean(results, 'planned_steps'):.2f}"
    )
    print(f"Retrieval JSON: {output_path.resolve()}")


# %% [markdown]
# ## Batch query and interactive chat

# %%
def query(agent: WikipediaAgent, question: str) -> str:
    """Batch mode: one question, clarify never blocks, trace printed."""
    state = agent.run(question, mode="batch")
    print(f"\nQuestion: {question}")
    _print_trace(state)
    metrics = agent_metrics(None, state)
    print(f"  model calls={metrics['llm_calls_total']} (planner {metrics['planner_calls']}, "
          f"tool {metrics['tool_llm_calls']})  sources={adv._unique_files(state['context'])}")
    print(f"\nAnswer:\n{state['response']}")
    log(f"QUERY {question}", json.dumps(metrics, ensure_ascii=False, default=str) + "\n\n" + state["response"])
    return state["response"]


def chat(agent: WikipediaAgent) -> None:
    """Interactive mode: clarify asks you; earlier turns resolve follow-ups."""
    print("Wikipedia agent - ask a question, or 'quit' to exit.")
    history: list[tuple[str, str]] = []
    while True:
        try:
            question = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question.casefold() in {"quit", "exit", "q"}:
            break
        state = agent.run(question, mode="chat", history=history)
        _print_trace(state)
        print(f"\nAgent: {state['response']}")
        print(f"  sources: {adv._unique_files(state['context'])}")
        history.append((question, state["response"]))
        log(f"CHAT {question}", json.dumps(agent_metrics(None, state), ensure_ascii=False, default=str)
            + "\n\n" + state["response"])


# %% [markdown]
# ## My agent plan (starter Step 2)

# %%
def my_agent_plan() -> dict[str, Any]:
    return {
        "tools": ["chunks", "decompose", "graph", "title_search", "read_section", "clarify", "answer"],
        "stop_condition": (
            "The planner lists no missing information in the evidence, or 3 planned "
            "retrievals after the free seed search are used, or its reply cannot be "
            "parsed or repeats an earlier action."
        ),
        "system_prompt_idea": (
            "Assess the evidence using only its text, list what the question still needs, "
            "and choose the cheapest tool likely to fill that gap, building queries only "
            "from names in the question or evidence, never from memory."
        ),
        "test_tasks": [
            "Who won Best Actor at the 95th ceremony and what was notable about the whole "
            "nominee field that year?",
            "The author who won the Nobel Prize in Literature the same year a magnitude-9 "
            "earthquake struck Alaska initially refused the honor - who was he, and why "
            "did he decline?",
            "What was the former name of the university where Barack Obama earned his law "
            "degree?",
        ],
    }


# %%
def main() -> None:
    parser = argparse.ArgumentParser(description="Agent-based RAG over the Wikipedia corpus (Checkpoint 5.1).")
    parser.add_argument("--agent-version", choices=AGENT_VERSIONS, default="v2",
                        help="v0: fixed 3.1/4.1 whole-article baseline (no agent); v1: chunks/decompose/graph/"
                             "clarify agent; v2: adds title_search, read_section, verified facts")
    parser.add_argument("--input", type=Path, default=GOLDEN_SUITE_PATH,
                        help=f"golden-suite JSON to evaluate (default: {GOLDEN_SUITE_PATH.name})")
    parser.add_argument("--ids", help="comma-separated record ids to evaluate, e.g. Q049,Q009,G13")
    parser.add_argument("--limit", type=int, help="evaluate only the first N (selected) records")
    parser.add_argument("--output", type=Path, help="path for results JSON")
    parser.add_argument("--retrieval-only", action="store_true",
                        help="run the retrieval loop (planner included) without answering or judging")
    parser.add_argument("--question", help="answer one question in batch mode and print the agent's trace")
    parser.add_argument("--chat", action="store_true", help="interactive mode; clarify questions are asked of you")
    parser.add_argument("--plan", action="store_true", help="print my_agent_plan() and exit")
    parser.add_argument("--judge-repeats", type=int, default=1,
                        help="correctness verdicts per record (majority vote reported; first verdict fills the 4.1 fields)")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high"),
                        help="OpenRouter reasoning effort for the planner, clue step and answer (not decompose or judges)")
    parser.add_argument("--answer-model",
                        help=f"model for the answer and the closed-book answer (default {adv.LLM_MODEL}); judges keep the default")
    parser.add_argument("--planner-model",
                        help=f"model for the planner and clue step (default {adv.LLM_MODEL}); decompose, answer and judges keep the default")
    parser.add_argument("--disable", default="",
                        help=f"v2 only: comma-separated round-2 refinements to switch off, from {','.join(V2_FEATURES)}")
    parser.add_argument("--build-tables-index", action="store_true",
                        help="build the table-rendered chunk cache and vector index used by v2, then exit")
    args = parser.parse_args()
    disabled = {name.strip() for name in args.disable.split(",") if name.strip()}
    unknown = disabled - set(V2_FEATURES)
    if unknown:
        parser.error(f"--disable: unknown feature(s) {sorted(unknown)}; choose from {list(V2_FEATURES)}")
    if args.build_tables_index:
        build_or_load_tables_db(load_or_build_tables_corpus())
        return
    if args.plan:
        print(json.dumps(my_agent_plan(), indent=2))
        return
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if not args.input.is_file():
        parser.error(f"--input file not found: {args.input}")

    llm = adv.make_llm()
    if args.agent_version == "v0":
        agent = BaselinePipeline(llm, answer_enabled=not args.retrieval_only)
    else:
        tables = args.agent_version == "v2" and "tables" not in disabled
        _RUN_FEATURES[:] = [name for name in V2_FEATURES if name not in disabled] if args.agent_version == "v2" else []
        if args.planner_model and args.planner_model != adv.LLM_MODEL:
            if args.planner_model not in MODEL_PRICES:
                parser.error(f"--planner-model: no price for {args.planner_model}; add it to MODEL_PRICES")
            _RUN_PLANNER_MODEL[:] = [args.planner_model]
        if args.answer_model and args.answer_model != adv.LLM_MODEL:
            if args.answer_model not in MODEL_PRICES:
                parser.error(f"--answer-model: no price for {args.answer_model}; add it to MODEL_PRICES")
            _RUN_ANSWER_MODEL[:] = [args.answer_model]
        if args.reasoning_effort:
            _RUN_REASONING[:] = [args.reasoning_effort]
        agent = WikipediaAgent(llm, Toolbox(tables=tables), args.agent_version,
                               answer_enabled=not args.retrieval_only, disabled=disabled,
                               planner_model=args.planner_model, answer_model=args.answer_model,
                               reasoning_effort=args.reasoning_effort)
    if args.chat:
        chat(agent)
        return
    if args.question:
        query(agent, args.question)
        return
    items = _load_items(args.input, args.ids.split(",") if args.ids else None, args.limit)
    if args.retrieval_only:
        run_retrieval_only(agent, items, args.output)
        return
    run_evaluation(agent, llm, items, args.output, args.judge_repeats)


if __name__ == "__main__":
    main()
