r"""Capstone Checkpoint 4.1 - Advanced Retrieval Implementation.

Built from the Checkpoint 3.1 evaluation script: the golden-suite loader, the
LLM judges, and the deterministic metrics are carried over unchanged so that
every retrieval configuration is scored by exactly the same instruments. What
is new is a retrieval switch (``--retriever``) with four strategies that all
sit behind one seam, ``retrieve(query) -> list[Hit]``:

| Strategy    | Unit          | Index                              | Technique |
|-------------|---------------|------------------------------------|-----------|
| baseline    | whole article | Checkpoint 2.1 whole-article Chroma | BM25 + vector fusion (the 3.1 baseline, unchanged) |
| chunks      | text chunk    | chunk Chroma (built here)          | same fusion over section/size-split chunks |
| decompose   | text chunk    | chunk Chroma                       | Lab 4.1: LLM sub-queries, per-chunk score summing |
| graph       | text chunk    | chunk Chroma + NetworkX graph      | Lab 4.2: seed chunks, then expand through category, infobox and hyperlink edges; primary vs. context labelling |

Metric changes relative to Checkpoint 3.1 (chunk units make several
article-level formulas ambiguous - see the consolidated baseline report):

| Metric | Status | Definition here |
|---|---|---|
| source_hit_at_k / source_recall_at_k / source_recall_strict | comparable | computed over the set of *unique* retrieved articles |
| unique_articles_retrieved | new | distinct articles among the k retrieved units |
| source_recall_at_3_articles | new | recall over the first 3 unique articles in rank order - the matched-count comparison with the 3.1 baseline |
| chunk_precision_at_k (= source_precision_at_k) | revised | on-topic units / k; identical to the old formula when units are articles |
| article_precision | new | on-topic unique articles / unique articles retrieved |
| evidence_recall | new | fraction of the record's supporting_quotes found verbatim in the retrieved context (right passage, not just right article) |
| context_chars | new | size of the context handed to the answer model |
| quote_fidelity_rate / quote_attribution_accuracy | comparable | retrieved text is now aggregated per article before matching |
"""

# %%
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")

import networkx as nx
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from rank_bm25 import BM25Okapi

CHECKPOINT_2_1_DIR = Path(__file__).parents[1] / "Checkpoint 2.1"
if str(CHECKPOINT_2_1_DIR) not in sys.path:
    sys.path.insert(0, str(CHECKPOINT_2_1_DIR))

from Extract_text_and_links_from_wikis import (  # noqa: E402
    extract_wikipedia_text,
    process_wikipedia_with_nodes_and_edges,
)

# %%
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
LLM_MODEL = "openai/gpt-5.4-mini"
EMBEDDING_MODEL = "openai/text-embedding-3-small"
TEMPERATURE = 0.2
# OpenRouter reserves the model's full default output allowance (65k tokens)
# when checking affordability, so an uncapped request is refused whenever the
# balance is low; 4k is ample for the longest judge response.
MAX_OUTPUT_TOKENS = 4096
# New OpenRouter accounts are capped at 20 requests/minute per model; each
# record makes five chat calls, so calls are paced and 429s are retried.
LLM_MIN_INTERVAL_SECONDS = 3.1
LLM_MAX_RETRIES = 6
WEIGHT_BM25 = 0.5
WEIGHT_VECTOR = 0.5
MAX_CHUNK_CHARS = 2000

# Per-strategy defaults. The baseline keeps the exact 3.1 settings so it
# reproduces the consolidated baseline; the chunk strategies retrieve more,
# smaller units and fuse from a deeper candidate pool.
RETRIEVER_CONFIGS: dict[str, dict[str, Any]] = {
    "baseline": {"top_k": 3, "candidate_pool": 10, "unit": "article"},
    "chunks": {"top_k": 8, "candidate_pool": 40, "unit": "chunk"},
    "decompose": {"top_k": 8, "candidate_pool": 40, "unit": "chunk"},
    "graph": {"top_k": 8, "candidate_pool": 40, "unit": "chunk"},
}

# Graph strategy knobs.
GRAPH_SEED_K = 4              # distinct articles (best chunk each) that seed the traversal
GRAPH_MAX_CATEGORY_SIZE = 150 # skip co-membership through catch-all categories (e.g. "Living people")
GRAPH_CATEGORY_MATCH_TOP = 8  # categories whose titles are matched against the query
GRAPH_CATEGORY_MIN_OVERLAP = 2
GRAPH_RELATION_WEIGHTS = {"category_match": 4.0, "infobox": 3.0, "category": 2.0, "link": 1.0}
# A candidate scores its single best relation plus a small, capped bonus for
# further relations - summing every shared category would let any article
# with a dozen incidental categories in common outrank the one typed edge
# the query is actually about (Obama -> Education -> Harvard).
GRAPH_EXTRA_RELATION_BONUS = 0.5
GRAPH_EXTRA_RELATION_CAP = 4
GRAPH_CATEGORY_MATCH_CAP = 3  # matched-category intersections counted per article
GRAPH_QUERY_BOOST = 2.0       # neighbour title or edge label shares a content word with the query
INDEX_BATCH_SIZE = 1000

# Parent-child expansion for the chunk strategies: chunks rank the articles,
# then each hit is widened to its neighbours ("window"), to the section it
# came from ("section", capped so a 20-chunk section cannot swamp the
# context), or to the whole article ("article"). A total context budget keeps
# the answer prompt bounded whatever the parents' sizes.
PARENT_MODES = ("none", "window", "section", "lead_section", "article")
PARENT_MAX_CHUNKS = {"window": 3, "section": 5, "lead_section": 4, "article": 10_000}
# "lead_section" also prepends the article's lead (intro + infobox table, the
# chunks with no section header) once per article: the entity's identity
# facts - dates, nationality, former names - sit there, not in the body
# section that happened to match the query.
LEAD_MAX_CHUNKS = 3
PARENT_MAX_CONTEXT_CHARS = 40_000

LOG_PATH = Path.cwd() / "checkpoint_4_1_evaluation.log"
CHECKPOINT_1_1_DIR = Path(__file__).parents[1] / "Checkpoint 1.1"
CHECKPOINT_3_1_DIR = Path(__file__).parents[1] / "Checkpoint 3.1"
WIKIPEDIA_DIR = str(CHECKPOINT_1_1_DIR / "Wikipedia")
WIKIPEDIA_CHROMA_DIR = str(CHECKPOINT_2_1_DIR / "wikipedia_chroma_db")
CHUNK_CACHE_DIR = CHECKPOINT_2_1_DIR / f"wikipedia_chunks{MAX_CHUNK_CHARS}_cache"
CHUNK_CHROMA_DIR = CHECKPOINT_2_1_DIR / f"wikipedia_chunks{MAX_CHUNK_CHARS}_chroma_db"
GOLDEN_SUITE_PATH = Path(__file__).with_name("golden_suite_4.1.json")
RESULTS_DIR = Path(__file__).with_name("evaluation_results")

SCENARIO = "wikipedia"

DECOMPOSE_SYSTEM = (
    "You are a query decomposition assistant for a Wikipedia retrieval system. "
    "Break the user's question into 2-4 focused sub-queries that together cover "
    "everything needed to answer it. Each sub-query should target a distinct aspect "
    "or entity, phrased as a search over encyclopedia articles. "
    'Return ONLY a JSON array of strings, e.g., ["sub-query 1", "sub-query 2"].'
)
ANSWER_SYSTEM = (
    "You are a helpful assistant. Answer the question using ONLY the provided "
    "documents, which may be excerpts of longer articles. Documents marked "
    "(context: ...) were added because they are related to a primary document; "
    "use them when they help. Cite factual claims with the exact source filename "
    "in square brackets. When quoting, use the form [filename.html] \"verbatim "
    "quotation\". If the documents do not contain the answer, say so rather than "
    "guessing."
)
CLOSED_BOOK_SYSTEM = (
    "Answer the question using your own general knowledge, with no reference "
    "material provided. Answer as best you can from what you already know, or "
    "say you don't know if you genuinely don't - don't fabricate specifics."
)
JUDGE_SYSTEM = (
    "You are a strict evaluator of retrieval-augmented answers. Use only the supplied "
    "reference answer, required aspects, and retrieved context. Return valid JSON only."
)
QUALITY_LEVELS = {"complete", "substantially_complete", "partial", "incorrect"}
REFUSAL_OUTCOMES = {"appropriate_refusal", "over_refusal", "hallucinated"}

STOPWORDS = {
    "a", "an", "and", "another", "any", "are", "as", "at", "be", "besides", "both",
    "by", "did", "do", "does", "for", "from", "give", "had", "has", "have", "he",
    "her", "his", "how", "in", "is", "it", "its", "me", "name", "of", "on", "or",
    "other", "same", "she", "that", "the", "their", "them", "there", "these",
    "they", "this", "to", "two", "was", "were", "what", "when", "where", "which",
    "who", "whom", "with", "you",
}


# %%
def check_api_key() -> str:
    load_dotenv()
    if not os.getenv("OPENROUTER_API_KEY"):
        # The .env used by Checkpoint 3.1 lives next to that script; reuse it.
        load_dotenv(CHECKPOINT_3_1_DIR / ".env")
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Use the OpenRouter API key "
            "provided for this program, put it in a .env file next to this "
            "script, and rerun."
        )
    return key


def make_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=LLM_MODEL,
        temperature=TEMPERATURE,
        max_tokens=MAX_OUTPUT_TOKENS,
        api_key=check_api_key(),
        base_url=OPENROUTER_BASE_URL,
    )


def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
        api_key=check_api_key(),
        base_url=OPENROUTER_BASE_URL,
    )


def log(label: str, text: str) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {label}\n{text}\n{'-' * 72}\n")


# %% [markdown]
# ## Retrieval units
#
# Every strategy returns a list of `Hit`s. `unit_id` is the filename for the
# whole-article baseline and the chunk id otherwise; `source_file` is always
# the article filename, which is what citations, recall and precision use.

# %%
@dataclass
class Hit:
    unit_id: str
    source_file: str
    text: str
    score: float
    role: str = "primary"          # "primary" or "context: <relation>"
    article_id: str | None = None

    @property
    def label(self) -> str:
        if self.role == "primary":
            return f"[{self.source_file}]"
        return f"[{self.source_file}] ({self.role})"


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _stem(token: str) -> str:
    """Just enough to let 'presidents' match 'president' and 'centuries' match
    'century' when matching query words against category titles."""
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


def _content_tokens(text: str) -> set[str]:
    return {_stem(token) for token in _tokens(text) if token not in STOPWORDS}


def _normalize(scores: list[float], invert: bool = False) -> list[float]:
    if not scores:
        return []
    low, high = min(scores), max(scores)
    if high == low:
        return [0.5] * len(scores)
    normalized = [(score - low) / (high - low) for score in scores]
    return [1.0 - score for score in normalized] if invert else normalized


# Link targets may contain one level of parentheses, e.g. ./King_Kong_(2005_film).
# Single-character alternation (no nested quantifier) so a chunk that ends
# mid-link cannot trigger catastrophic backtracking.
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)")


def _display_text(markdown: str) -> str:
    """Chunk text as shown to BM25, the embedder and the answer model: keep the
    anchor text of wiki links, drop the './slug' targets that only add tokens."""
    return _MARKDOWN_LINK.sub(r"\1", markdown)


# %% [markdown]
# ## Hybrid index (BM25 + vector fusion), shared by every strategy

# %%
class HybridIndex:
    """BM25 + Chroma fusion over arbitrary units, keyed by unit id so several
    chunks of one article never collapse into a single entry."""

    def __init__(
        self,
        units: list[tuple[str, str, str]],   # (unit_id, source_file, text)
        db: Chroma,
        metadata_id_key: str,
    ):
        self.unit_ids = [unit_id for unit_id, _file, _text in units]
        self.source_files = [source_file for _id, source_file, _text in units]
        self.texts = [text for _id, _file, text in units]
        self.index_of = {unit_id: index for index, unit_id in enumerate(self.unit_ids)}
        self._bm25 = BM25Okapi([_tokens(text) for text in self.texts])
        self._db = db
        self._metadata_id_key = metadata_id_key

    def bm25_scores(self, query: str) -> list[float]:
        return [float(score) for score in self._bm25.get_scores(_tokens(query))]

    def _bm25_top_k(self, query: str, k: int) -> list[tuple[str, float]]:
        scores = self._bm25.get_scores(_tokens(query))
        top = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)[:k]
        return [(self.unit_ids[index], float(scores[index])) for index in top]

    def _vector_top_k(self, query: str, k: int) -> list[tuple[str, float]]:
        results = self._db.similarity_search_with_score(query, k=k)
        return [
            (str(document.metadata.get(self._metadata_id_key, "unknown")), float(distance))
            for document, distance in results
        ]

    def fused_scores(self, query: str, pool: int) -> list[tuple[str, float]]:
        """All candidates from both retrievers with their fused (0-1) scores,
        best first."""
        bm25_results = self._bm25_top_k(query, pool)
        vector_results = self._vector_top_k(query, pool)
        bm25_normalized = dict(zip(
            [unit_id for unit_id, _score in bm25_results],
            _normalize([score for _unit_id, score in bm25_results]),
        ))
        vector_normalized = dict(zip(
            [unit_id for unit_id, _distance in vector_results],
            _normalize([distance for _unit_id, distance in vector_results], invert=True),
        ))
        candidates = list(dict.fromkeys(list(bm25_normalized) + list(vector_normalized)))
        fused = [
            (
                unit_id,
                WEIGHT_BM25 * bm25_normalized.get(unit_id, 0.0)
                + WEIGHT_VECTOR * vector_normalized.get(unit_id, 0.0),
            )
            for unit_id in candidates
            if unit_id in self.index_of
        ]
        fused.sort(key=lambda item: item[1], reverse=True)
        return fused

    def hit(self, unit_id: str, score: float, role: str = "primary") -> Hit:
        index = self.index_of[unit_id]
        return Hit(unit_id, self.source_files[index], self.texts[index], score, role)

    def get_top_k(self, query: str, k: int, pool: int) -> list[Hit]:
        return [self.hit(unit_id, score) for unit_id, score in self.fused_scores(query, pool)[:k]]


# %% [markdown]
# ## Baseline corpus: whole articles (unchanged from Checkpoint 3.1)

# %%
_wikipedia_docs: list[tuple[str, str]] | None = None


def _get_wikipedia_docs() -> list[tuple[str, str]]:
    global _wikipedia_docs
    if _wikipedia_docs is None:
        _wikipedia_docs = extract_wikipedia_text(WIKIPEDIA_DIR)
    return _wikipedia_docs


def build_or_load_wikipedia_db() -> Chroma:
    if os.path.isdir(WIKIPEDIA_CHROMA_DIR) and os.listdir(WIKIPEDIA_CHROMA_DIR):
        print(f"Loading existing whole-article vector DB from {WIKIPEDIA_CHROMA_DIR}")
        return Chroma(persist_directory=WIKIPEDIA_CHROMA_DIR, embedding_function=get_embeddings())
    print("Building whole-article vector DB (first run - embedding whole articles)...")
    documents = [
        Document(page_content=text, metadata={"source": filename})
        for filename, text in _get_wikipedia_docs()
    ]
    db = Chroma.from_documents(documents, get_embeddings(), persist_directory=WIKIPEDIA_CHROMA_DIR)
    print(f"Indexed {len(documents)} Wikipedia articles.")
    return db


# %% [markdown]
# ## Chunk corpus and graph data (from process_wikipedia_with_nodes_and_edges)
#
# The full-corpus parse takes ~35 minutes, so chunks, nodes and edges are
# cached to disk after the first run. The chunk vector index is built once,
# in batches, into its own persist directory so the whole-article index used
# by the baseline is never touched.

# %%
@dataclass
class ChunkCorpus:
    chunks: list[dict[str, Any]]            # {"page_content": ..., "metadata": {...}}
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    units: list[tuple[str, str, str]] = field(default_factory=list)  # (chunk_id, source_file, display text)


def load_or_build_chunk_corpus() -> ChunkCorpus:
    manifest_path = CHUNK_CACHE_DIR / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(
            f"Loading chunk cache from {CHUNK_CACHE_DIR} "
            f"({manifest['chunk_count']} chunks, {manifest['node_count']} nodes, "
            f"{manifest['edge_count']} edges)"
        )
        with (CHUNK_CACHE_DIR / "chunks.jsonl").open(encoding="utf-8") as file:
            chunks = [json.loads(line) for line in file if line.strip()]
        nodes = json.loads((CHUNK_CACHE_DIR / "nodes.json").read_text(encoding="utf-8"))
        edges = json.loads((CHUNK_CACHE_DIR / "edges.json").read_text(encoding="utf-8"))
    else:
        print(f"Building chunk cache (first run - parsing {WIKIPEDIA_DIR}, ~35 min)...")
        started = time.perf_counter()
        graph_data = process_wikipedia_with_nodes_and_edges(WIKIPEDIA_DIR, MAX_CHUNK_CHARS)
        chunks = [
            {"page_content": document.page_content, "metadata": document.metadata}
            for document in graph_data.documents
        ]
        nodes, edges = graph_data.nodes, graph_data.edges
        CHUNK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with (CHUNK_CACHE_DIR / "chunks.jsonl").open("w", encoding="utf-8") as file:
            for chunk in chunks:
                file.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        (CHUNK_CACHE_DIR / "nodes.json").write_text(json.dumps(nodes, ensure_ascii=False), encoding="utf-8")
        (CHUNK_CACHE_DIR / "edges.json").write_text(json.dumps(edges, ensure_ascii=False), encoding="utf-8")
        manifest_path.write_text(json.dumps({
            "corpus_dir": WIKIPEDIA_DIR,
            "max_chunk_chars": MAX_CHUNK_CHARS,
            "chunk_count": len(chunks),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "built_at": datetime.now().isoformat(timespec="seconds"),
            "build_seconds": round(time.perf_counter() - started, 1),
        }, indent=2), encoding="utf-8")
        print(f"Chunk cache written to {CHUNK_CACHE_DIR}")
    units = [
        (
            str(chunk["metadata"]["chunk_id"]),
            str(chunk["metadata"]["source_file"]),
            _display_text(chunk["page_content"]),
        )
        for chunk in chunks
    ]
    return ChunkCorpus(chunks=chunks, nodes=nodes, edges=edges, units=units)


def _scalar_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
    """Chroma accepts only scalar metadata values; linked_article_ids is a list."""
    cleaned: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, list):
            cleaned[key] = ",".join(str(item) for item in value)
        elif isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    return cleaned


def build_or_load_chunk_db(corpus: ChunkCorpus) -> Chroma:
    complete_marker = CHUNK_CHROMA_DIR / "index_complete.json"
    db = Chroma(persist_directory=str(CHUNK_CHROMA_DIR), embedding_function=get_embeddings())
    if complete_marker.is_file():
        print(f"Loading existing chunk vector DB from {CHUNK_CHROMA_DIR}")
        return db
    total = len(corpus.units)
    existing = db._collection.count()
    start = (existing // INDEX_BATCH_SIZE) * INDEX_BATCH_SIZE
    if existing:
        print(f"Resuming chunk index build: {existing}/{total} chunks already present")
    else:
        print(f"Building chunk vector DB at {CHUNK_CHROMA_DIR} ({total} chunks)...")
    started = time.perf_counter()
    for begin in range(start, total, INDEX_BATCH_SIZE):
        batch = corpus.chunks[begin:begin + INDEX_BATCH_SIZE]
        documents = [
            Document(page_content=_display_text(chunk["page_content"]), metadata=_scalar_metadata(chunk["metadata"]))
            for chunk in batch
        ]
        ids = [str(chunk["metadata"]["chunk_id"]) for chunk in batch]
        db.add_documents(documents, ids=ids)
        done = min(begin + INDEX_BATCH_SIZE, total)
        print(f"  indexed {done}/{total} chunks ({time.perf_counter() - started:.0f}s elapsed)")
    complete_marker.write_text(json.dumps({
        "chunk_count": total,
        "embedding_model": EMBEDDING_MODEL,
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }, indent=2), encoding="utf-8")
    print(f"Indexed {total} chunks.")
    return db


# %% [markdown]
# ## Graph layer (Lab 4.2 adapted to the real node/edge schema)
#
# Nodes are articles and categories; edges are `links_to`, `in_category` and
# the typed infobox edges (`education`, `directed_by`, `succeeded_by`, ...).
# Retrieval seeds with chunk hits, then expands each seed article through its
# edges; a second seed source matches the query words against category titles
# so that "another Best Picture-winning director" reaches the category members
# even when no seed chunk happens to be one of them.

# %%
class WikipediaGraph:
    def __init__(self, corpus: ChunkCorpus, index: HybridIndex):
        self.graph = nx.DiGraph()
        self.index = index
        self.file_by_article: dict[str, str] = {}
        self.article_by_file: dict[str, str] = {}
        self.category_title: dict[str, str] = {}
        for node in corpus.nodes:
            self.graph.add_node(node["id"], **node)
            if node.get("node_type") == "article":
                self.file_by_article[node["id"]] = node["source_file"]
                self.article_by_file[node["source_file"]] = node["id"]
            elif node.get("node_type") == "category":
                self.category_title[node["id"]] = node["title"]
        for edge in corpus.edges:
            self.graph.add_edge(edge["source"], edge["target"], **edge)
        self.chunk_indices_by_file: dict[str, list[int]] = defaultdict(list)
        for position, (_unit_id, source_file, _text) in enumerate(corpus.units):
            self.chunk_indices_by_file[source_file].append(position)
        self.category_members: dict[str, list[str]] = defaultdict(list)
        for source, target, data in self.graph.edges(data=True):
            if data.get("edge_type") == "in_category":
                self.category_members[target].append(source)
        self.category_ids = list(self.category_title)
        self._category_bm25 = BM25Okapi([
            [_stem(token) for token in _tokens(self.category_title[category_id])]
            for category_id in self.category_ids
        ])

    def match_categories(self, query: str) -> list[tuple[str, int]]:
        """Categories whose titles share at least GRAPH_CATEGORY_MIN_OVERLAP
        content words with the query, e.g. 'impeached president' ->
        'Impeached presidents of the United States'."""
        query_tokens = _content_tokens(query)
        if not query_tokens:
            return []
        scores = self._category_bm25.get_scores([_stem(token) for token in _tokens(query)])
        ranked = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
        eligible: list[tuple[int, float, str]] = []
        for index in ranked[:GRAPH_CATEGORY_MATCH_TOP * 5]:
            category_id = self.category_ids[index]
            overlap = len(query_tokens & _content_tokens(self.category_title[category_id]))
            members = self.category_members.get(category_id, [])
            if overlap >= GRAPH_CATEGORY_MIN_OVERLAP and 0 < len(members) <= GRAPH_MAX_CATEGORY_SIZE:
                eligible.append((overlap, float(scores[index]), category_id))
        # Overlap first: BM25 alone favours short one-member titles
        # ("20th-century presidents in Africa") over the category the query
        # is about ("20th-century presidents of the United States").
        eligible.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [(category_id, overlap) for overlap, _score, category_id in eligible[:GRAPH_CATEGORY_MATCH_TOP]]

    def neighbours(self, article_id: str) -> list[tuple[str, str, str]]:
        """(neighbour article id, relation kind, relation description)."""
        found: list[tuple[str, str, str]] = []
        seed_file = self.file_by_article.get(article_id, article_id)
        for _source, target, data in self.graph.out_edges(article_id, data=True):
            edge_type = data.get("edge_type")
            if edge_type == "in_category":
                members = self.category_members.get(target, [])
                if len(members) > GRAPH_MAX_CATEGORY_SIZE:
                    continue
                title = self.category_title.get(target, "?")
                for member in members:
                    if member != article_id:
                        found.append((member, "category", f"shares category '{title}' with {seed_file}"))
            elif edge_type == "links_to":
                found.append((target, "link", f"linked from {seed_file}"))
            else:
                label = data.get("infobox_label", edge_type)
                found.append((target, "infobox", f"'{label}' of {seed_file}"))
        for source, _target, data in self.graph.in_edges(article_id, data=True):
            edge_type = data.get("edge_type")
            if edge_type in {"in_category", "links_to"}:
                continue
            label = data.get("infobox_label", edge_type)
            found.append((source, "infobox", f"{seed_file} is '{label}' of {self.file_by_article.get(source, source)}"))
        return found

    def best_chunk(self, source_file: str, bm25_scores: list[float]) -> tuple[int, float]:
        """The article's chunk most relevant to the query by BM25, falling back
        to its first (lead/infobox) chunk when nothing overlaps."""
        positions = self.chunk_indices_by_file.get(source_file, [])
        if not positions:
            return -1, 0.0
        best = max(positions, key=lambda position: bm25_scores[position])
        return (best, bm25_scores[best]) if bm25_scores[best] > 0 else (positions[0], 0.0)


# %% [markdown]
# ## Parent-child expansion (search small, read big)

# %%
class ParentExpander:
    """Widens chunk hits to their window / section / article, reading the
    neighbouring chunks straight from the cached corpus so nothing is
    re-parsed or re-embedded."""

    def __init__(self, corpus: ChunkCorpus, index: HybridIndex):
        self.index = index
        self.positions_by_file: dict[str, list[int]] = defaultdict(list)
        self.section_key: list[tuple[Any, Any, Any]] = []
        self.chunk_index_of: list[int] = []
        for position, chunk in enumerate(corpus.chunks):
            metadata = chunk["metadata"]
            self.positions_by_file[str(metadata["source_file"])].append(position)
            self.section_key.append((metadata.get("Header 1"), metadata.get("Header 2"), metadata.get("Header 3")))
            self.chunk_index_of.append(int(metadata.get("chunk_index", position)))
        for positions in self.positions_by_file.values():
            positions.sort(key=lambda position: self.chunk_index_of[position])

    def _section_span(self, positions: list[int], i: int, cap: int) -> list[int]:
        """Chunks of the section containing positions[i], at most `cap` of
        them centred on the hit."""
        key = self.section_key[positions[i]]
        lo = hi = i
        while lo > 0 and self.section_key[positions[lo - 1]] == key:
            lo -= 1
        while hi < len(positions) - 1 and self.section_key[positions[hi + 1]] == key:
            hi += 1
        if hi - lo + 1 > cap:
            lo2 = max(lo, i - cap // 2)
            hi2 = min(hi, lo2 + cap - 1)
            lo, hi = max(lo, hi2 - cap + 1), hi2
        return positions[lo:hi + 1]

    def parent_positions(self, position: int, mode: str) -> list[int]:
        positions = self.positions_by_file[self.index.source_files[position]]
        i = positions.index(position)
        if mode == "window":
            half = PARENT_MAX_CHUNKS["window"] // 2
            return positions[max(0, i - half):i + half + 1]
        if mode == "section":
            return self._section_span(positions, i, PARENT_MAX_CHUNKS["section"])
        if mode == "lead_section":
            # The article title is "Header 1" on every chunk; the lead (infobox
            # table + intro) is the run of chunks with no Header 2/3.
            lead = [p for p in positions if self.section_key[p][1] is None and self.section_key[p][2] is None][:LEAD_MAX_CHUNKS]
            section = self._section_span(positions, i, PARENT_MAX_CHUNKS["lead_section"])
            return sorted(set(lead) | set(section), key=lambda p: self.chunk_index_of[p])
        if mode == "article":
            return list(positions)
        raise ValueError(f"unknown parent mode {mode!r}")

    def expand(self, hits: list[Hit], mode: str, budget: int = PARENT_MAX_CONTEXT_CHARS) -> list[Hit]:
        covered: dict[str, set[int]] = defaultdict(set)
        expanded: list[Hit] = []
        remaining = budget
        for hit in hits:
            position = self.index.index_of.get(hit.unit_id)
            if position is None:
                expanded.append(hit)
                continue
            source_file = self.index.source_files[position]
            if position in covered[source_file]:
                continue   # its passage is already inside an earlier parent
            parent = [p for p in self.parent_positions(position, mode) if p not in covered[source_file]]
            text = "\n\n".join(self.index.texts[p] for p in parent)
            if len(text) > remaining:
                parent = [position]                     # budget exhausted: keep the child only
                text = self.index.texts[position]
                if len(text) > remaining:
                    break
            remaining -= len(text)
            covered[source_file].update(parent)
            first, last = self.chunk_index_of[parent[0]], self.chunk_index_of[parent[-1]]
            unit_id = f"{source_file}#c{first:05d}-c{last:05d}" if len(parent) > 1 else hit.unit_id
            expanded.append(Hit(unit_id, source_file, text, hit.score, hit.role, hit.article_id))
        return expanded


# %% [markdown]
# ## The retrieval switch

# %%
@dataclass
class Retriever:
    mode: str
    top_k: int
    candidate_pool: int
    parent: str = "none"
    parent_budget: int = PARENT_MAX_CONTEXT_CHARS
    article_index: HybridIndex | None = None
    chunk_index: HybridIndex | None = None
    graph: WikipediaGraph | None = None
    expander: ParentExpander | None = None
    llm: ChatOpenAI | None = None

    def retrieve(self, query: str) -> tuple[list[Hit], dict[str, Any]]:
        if self.mode == "baseline":
            return self.article_index.get_top_k(query, self.top_k, self.candidate_pool), {}
        if self.mode == "chunks":
            hits, trace = self.chunk_index.get_top_k(query, self.top_k, self.candidate_pool), {}
        elif self.mode == "decompose":
            hits, trace = self._decompose(query)
        elif self.mode == "graph":
            hits, trace = self._graph(query)
        else:
            raise ValueError(f"unknown retriever mode {self.mode!r}")
        if self.parent != "none":
            child_ids = [hit.unit_id for hit in hits]
            hits = self.expander.expand(hits, self.parent, self.parent_budget)
            trace = {**trace, "child_chunk_ids": child_ids, "parent_units": len(hits)}
        return hits, trace

    # --- Lab 4.1: query decomposition with per-chunk score summing ---
    def _decompose(self, query: str) -> tuple[list[Hit], dict[str, Any]]:
        sub_queries = decompose_query(self.llm, query)
        score_map: dict[str, float] = defaultdict(float)
        passes = [query] + [sub for sub in sub_queries if sub.strip() and sub.strip() != query]
        for pass_query in passes:
            for unit_id, score in self.chunk_index.fused_scores(pass_query, self.candidate_pool):
                score_map[unit_id] += score
        ranked = sorted(score_map.items(), key=lambda item: item[1], reverse=True)[:self.top_k]
        hits = [self.chunk_index.hit(unit_id, score) for unit_id, score in ranked]
        return hits, {"sub_queries": sub_queries}

    # --- Lab 4.2: seed chunks, expand through the graph, fill to top_k ---
    def _graph(self, query: str) -> tuple[list[Hit], dict[str, Any]]:
        graph, index = self.graph, self.chunk_index
        bm25_scores = index.bm25_scores(query)
        query_tokens = _content_tokens(query)

        # Seeds: the best chunk of each of the first GRAPH_SEED_K distinct
        # articles in the fused ranking, so one long article cannot occupy
        # every seed slot with its own chunks.
        seeds: list[Hit] = []
        seed_articles: list[str] = []
        for unit_id, score in index.fused_scores(query, self.candidate_pool):
            hit = index.hit(unit_id, score)
            article_id = graph.article_by_file.get(hit.source_file)
            if article_id is None or article_id in seed_articles:
                continue
            hit.article_id = article_id
            seeds.append(hit)
            seed_articles.append(article_id)
            if len(seeds) >= min(GRAPH_SEED_K, self.top_k):
                break

        # Candidate context articles. Each keeps its best relation weight, a
        # query-aware boost, and a capped bonus for additional relations.
        candidates: dict[str, dict[str, Any]] = {}

        def add_candidate(article_id: str, kind: str, description: str, weight: float, boost_text: str = "") -> None:
            if article_id in seed_articles or article_id not in graph.file_by_article:
                return
            entry = candidates.setdefault(article_id, {"best": 0.0, "boost": 0.0, "extra": 0, "relations": []})
            if description in entry["relations"]:
                return
            title = graph.graph.nodes[article_id].get("title", "")
            if query_tokens & _content_tokens(f"{title} {boost_text}"):
                entry["boost"] = GRAPH_QUERY_BOOST
            if weight > entry["best"]:
                entry["best"] = weight
            elif entry["relations"]:
                entry["extra"] += 1
            entry["relations"].append(description)

        matched_categories = graph.match_categories(query)
        membership: dict[str, int] = defaultdict(int)
        for category_id, _overlap in matched_categories:
            for member in graph.category_members[category_id]:
                membership[member] += 1
        for article_id, count in membership.items():
            titles = [
                graph.category_title[category_id]
                for category_id, _overlap in matched_categories
                if article_id in graph.category_members[category_id]
            ]
            description = "member of " + " and ".join(f"'{title}'" for title in titles)
            weight = GRAPH_RELATION_WEIGHTS["category_match"] * min(count, GRAPH_CATEGORY_MATCH_CAP)
            add_candidate(article_id, "category_match", description, weight)

        for article_id in seed_articles:
            for neighbour, kind, description in graph.neighbours(article_id):
                label = description if kind == "infobox" else ""
                add_candidate(neighbour, kind, description, GRAPH_RELATION_WEIGHTS[kind], label)

        # Final score; tie-break by how well the article's best chunk matches the query.
        for article_id, entry in candidates.items():
            position, score = graph.best_chunk(graph.file_by_article[article_id], bm25_scores)
            entry["chunk_position"] = position
            entry["score"] = (
                entry["best"] + entry["boost"]
                + GRAPH_EXTRA_RELATION_BONUS * min(entry["extra"], GRAPH_EXTRA_RELATION_CAP)
                + 0.01 * score
            )
        ranked = sorted(candidates.items(), key=lambda item: item[1]["score"], reverse=True)

        hits: list[Hit] = list(seeds)
        seen_units = {hit.unit_id for hit in hits}
        expansions: list[dict[str, Any]] = []
        for article_id, entry in ranked:
            if len(hits) >= self.top_k:
                break
            position = entry["chunk_position"]
            if position < 0:
                continue
            unit_id = index.unit_ids[position]
            if unit_id in seen_units:
                continue
            seen_units.add(unit_id)
            role = "context: " + "; ".join(entry["relations"][:2])
            hit = index.hit(unit_id, entry["score"], role)
            hit.article_id = article_id
            hits.append(hit)
            expansions.append({
                "source_file": hit.source_file,
                "relations": entry["relations"],
                "score": round(entry["score"], 3),
            })
        trace = {
            "seed_files": [hit.source_file for hit in seeds],
            "matched_categories": [
                {"title": graph.category_title[category_id], "members": len(graph.category_members[category_id])}
                for category_id, _overlap in matched_categories
            ],
            "candidate_count": len(candidates),
            "expansions": expansions,
        }
        return hits, trace


def decompose_query(llm: ChatOpenAI, query: str) -> list[str]:
    """Ask the LLM to split the question into focused sub-queries; on any
    malformed response fall back to [query] so retrieval degrades to plain
    hybrid search instead of crashing (parsing fixed as in the Module 4 lab)."""
    messages = [SystemMessage(content=DECOMPOSE_SYSTEM), HumanMessage(content=query)]
    try:
        raw = _message_text(llm.invoke(messages)).strip()
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL | re.IGNORECASE)
        if fence:
            raw = fence.group(1).strip()
        start = raw.find("[")
        parsed = json.loads(raw) if start == -1 else json.JSONDecoder().raw_decode(raw, start)[0]
        if isinstance(parsed, list) and parsed and all(isinstance(item, str) for item in parsed):
            return parsed
    except Exception:
        pass
    return [query]


_retriever: Retriever | None = None


def build_retriever(
    mode: str,
    top_k: int | None = None,
    candidate_pool: int | None = None,
    parent: str = "none",
    parent_budget: int = PARENT_MAX_CONTEXT_CHARS,
) -> Retriever:
    config = RETRIEVER_CONFIGS[mode]
    if parent != "none" and mode == "baseline":
        raise ValueError("--parent applies to the chunk strategies only")
    retriever = Retriever(
        mode=mode,
        top_k=top_k or config["top_k"],
        candidate_pool=candidate_pool or config["candidate_pool"],
        parent=parent,
        parent_budget=parent_budget,
    )
    if mode == "baseline":
        docs = _get_wikipedia_docs()
        retriever.article_index = HybridIndex(
            [(filename, filename, text) for filename, text in docs],
            build_or_load_wikipedia_db(),
            metadata_id_key="source",
        )
        return retriever
    corpus = load_or_build_chunk_corpus()
    db = build_or_load_chunk_db(corpus)
    print(f"Building BM25 index over {len(corpus.units)} chunks...")
    retriever.chunk_index = HybridIndex(corpus.units, db, metadata_id_key="chunk_id")
    if parent != "none":
        retriever.expander = ParentExpander(corpus, retriever.chunk_index)
    if mode == "graph":
        print("Building NetworkX graph...")
        retriever.graph = WikipediaGraph(corpus, retriever.chunk_index)
        print(
            f"  {retriever.graph.graph.number_of_nodes()} nodes, "
            f"{retriever.graph.graph.number_of_edges()} edges"
        )
    if mode == "decompose":
        retriever.llm = make_llm()
    return retriever


def retrieve(query: str) -> tuple[list[Hit], dict[str, Any]]:
    """Retrieve with the configured strategy. build_retriever() must run first."""
    if _retriever is None:
        raise RuntimeError("build_retriever() has not been called")
    return _retriever.retrieve(query)


def _format_context(hits: list[Hit]) -> str:
    return "\n\n".join(f"{hit.label} {hit.text}" for hit in hits)


def answer(llm: ChatOpenAI, query: str, hits: list[Hit]) -> tuple[str, dict[str, float | int]]:
    messages = [
        SystemMessage(content=ANSWER_SYSTEM),
        HumanMessage(content=f"Documents:\n{_format_context(hits)}\n\nQuestion: {query}"),
    ]
    return invoke_measured(llm, messages)


def answer_closed_book(llm: ChatOpenAI, query: str) -> tuple[str, dict[str, float | int]]:
    """Answer with no retrieved context, as a chunk-attribution baseline: a
    grounded claim the model can also produce here came from its own training
    data rather than from retrieval, regardless of whether it happens to be
    supported by what was retrieved."""
    messages = [
        SystemMessage(content=CLOSED_BOOK_SYSTEM),
        HumanMessage(content=f"Question: {query}"),
    ]
    return invoke_measured(llm, messages)


# %% [markdown]
# ## My advanced-retrieval plan (Checkpoint 4.1 worksheet, Step 4)

# %%
def my_advanced_plan() -> dict[str, Any]:
    return {
        "technique": "both",
        "node_types": ["article", "category"],
        "edge_types": [
            "links_to", "in_category",
            "infobox typed edges: education, succeeded_by, preceded_by, directed_by, "
            "cinematography, starring, born, died, relatives, ...",
        ],
        "test_queries": [
            "Which president served in both the 20th and 21st centuries? (G08 - category intersection)",
            "What was the former name of the university where Barack Obama earned his law degree? (G13 - education edge bridge)",
            "Name another cinematographer who has won the same award as Andrew Lesnie. (G01 - category co-membership)",
        ],
        "rationale": (
            "The 3.1 baseline fails exactly when the answer lives in an article the "
            "query never names (G08, G13) or when a 150k-character article's single "
            "embedding is swamped (G16). Chunking fixes the second; Wikipedia's own "
            "categories and infobox rows are curated relationships that reach the "
            "unnamed second document without relying on the model's memory."
        ),
    }


# %% [markdown]
# ## Step 2 - Evaluation metrics (judges carried over from Checkpoint 3.1)

# %%
def _message_text(response: Any) -> str:
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def _token_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage_metadata", None) or {}
    metadata = getattr(response, "response_metadata", None) or {}
    fallback = metadata.get("token_usage", {})
    input_tokens = int(usage.get("input_tokens") or fallback.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or fallback.get("completion_tokens") or 0)
    total_tokens = int(
        usage.get("total_tokens")
        or fallback.get("total_tokens")
        or input_tokens + output_tokens
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


_last_llm_call = 0.0


def _is_rate_limit(error: Exception) -> bool:
    status = getattr(error, "status_code", None)
    return status == 429 or "rate limit" in str(error).casefold()


def invoke_measured(
    llm: ChatOpenAI,
    messages: list[SystemMessage | HumanMessage],
) -> tuple[str, dict[str, float | int]]:
    """Call the model, pacing calls to stay under the account's per-minute
    limit and backing off on 429s. latency_seconds covers only the successful
    attempt; time spent waiting is reported separately as throttle_seconds."""
    global _last_llm_call
    throttle = 0.0
    for attempt in range(LLM_MAX_RETRIES + 1):
        wait = LLM_MIN_INTERVAL_SECONDS - (time.perf_counter() - _last_llm_call)
        if wait > 0:
            time.sleep(wait)
            throttle += wait
        started = time.perf_counter()
        _last_llm_call = started
        try:
            response = llm.invoke(messages)
        except Exception as error:
            if not _is_rate_limit(error) or attempt == LLM_MAX_RETRIES:
                raise
            backoff = min(90.0, 10.0 * (2 ** attempt))
            print(f"  rate limited; retrying in {backoff:.0f}s (attempt {attempt + 1}/{LLM_MAX_RETRIES})")
            time.sleep(backoff)
            throttle += backoff
            continue
        usage: dict[str, float | int] = _token_usage(response)
        usage["latency_seconds"] = time.perf_counter() - started
        usage["throttle_seconds"] = throttle
        return _message_text(response), usage
    raise RuntimeError("unreachable")


def _json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise ValueError(f"Judge did not return JSON: {text[:200]!r}")
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Judge response must be a JSON object")
    return value


def judge(
    llm: ChatOpenAI,
    answer_text: str,
    expected_answer: str,
    required_aspects: list[str],
    retrieved_context: str,
) -> tuple[dict[str, Any], dict[str, float | int]]:
    """Return binary, graded, aspect-coverage, and relevance judgments."""
    messages = [
        SystemMessage(content=JUDGE_SYSTEM),
        HumanMessage(
            content=(
                "Evaluate the response and return exactly one JSON object with keys:\n"
                "binary_correctness: 'pass' or 'fail';\n"
                "graded_correctness: 'complete', 'substantially_complete', 'partial', "
                "or 'incorrect';\n"
                "covered_aspect_indices: a list of 1-based indices supported by the response;\n"
                "answer_relevance: 'pass' if the response addresses the question asked, "
                "even if incomplete or incorrect, 'fail' if it drifts onto a different "
                "question or ignores what was asked.\n\n"
                f"RESPONSE:\n{answer_text}\n\n"
                f"REFERENCE ANSWER:\n{expected_answer}\n\n"
                f"REQUIRED ASPECTS:\n{json.dumps(required_aspects, ensure_ascii=False)}\n\n"
                f"RETRIEVED CONTEXT:\n{retrieved_context}"
            )
        ),
    ]
    text, usage = invoke_measured(llm, messages)
    result = _json_object(text)
    binary = str(result.get("binary_correctness", "fail")).casefold()
    level = str(result.get("graded_correctness", "incorrect")).casefold()
    answer_relevance = str(result.get("answer_relevance", "fail")).casefold()
    covered = {
        index
        for index in result.get("covered_aspect_indices", [])
        if isinstance(index, int) and 1 <= index <= len(required_aspects)
    }
    if binary not in {"pass", "fail"}:
        binary = "fail"
    if level not in QUALITY_LEVELS:
        level = "incorrect"
    if answer_relevance not in {"pass", "fail"}:
        answer_relevance = "fail"
    return {
        "correctness": binary,
        "graded_correctness": level,
        "graded_correctness_score": {
            "complete": 1.0,
            "substantially_complete": 0.75,
            "partial": 0.5,
            "incorrect": 0.0,
        }[level],
        "covered_aspects": sorted(covered),
        "aspect_coverage": len(covered) / len(required_aspects) if required_aspects else 0.0,
        "answer_relevance": answer_relevance,
    }, usage


def judge_claims(
    llm: ChatOpenAI,
    answer_text: str,
    retrieved_context: str,
    closed_book_answer: str,
) -> tuple[dict[str, Any], dict[str, float | int]]:
    """Decompose the response into individual factual claims and judge each one:
    whether it is grounded in the retrieved context at all; if it carries a
    [filename.html] citation, whether that specific cited document (not just
    some document in the retrieved set) actually supports it; and - for claims
    that are grounded - whether the claim is also present in closed_book_answer,
    a response produced with no retrieved context at all. A grounded claim the
    model could also produce closed-book came from training data rather than
    from retrieval, regardless of whether the retrieved context happens to
    support it too - that's chunk attribution (provenance) as distinct from
    groundedness (consistency with what was retrieved). Faithfulness and the
    graded groundedness score are both derived from this single claim list
    rather than asked for separately, so the two judgments can't disagree."""
    messages = [
        SystemMessage(content=JUDGE_SYSTEM),
        HumanMessage(
            content=(
                "Decompose the RESPONSE below into its individual factual claims "
                "(roughly one per discrete assertion). Return exactly one JSON "
                "object with a single key 'claims': a list of objects, each with:\n"
                "text: the claim, quoted or closely paraphrased from the response;\n"
                "cited_source: the exact filename from the [filename.html] marker "
                "attached to this claim in the response, or null if the claim "
                "carries no citation;\n"
                "grounded: true if the claim is supported by the RETRIEVED CONTEXT "
                "(any document in it), false otherwise;\n"
                "citation_supported: if cited_source is set, true only if that "
                "SPECIFIC document's content supports the claim (not merely some "
                "other document in the retrieved context); null if cited_source "
                "is null;\n"
                "attributable_to_retrieval: only meaningful when grounded is true - "
                "true if the CLOSED-BOOK ANSWER below does not state this claim or "
                "states something different (the claim required the retrieved "
                "context to produce), false if the closed-book answer states the "
                "same claim (it's general/well-known enough that retrieval wasn't "
                "actually needed for it); null if grounded is false.\n\n"
                f"RESPONSE:\n{answer_text}\n\n"
                f"CLOSED-BOOK ANSWER (produced with no retrieved documents):\n{closed_book_answer}\n\n"
                f"RETRIEVED CONTEXT:\n{retrieved_context}"
            )
        ),
    ]
    text, usage = invoke_measured(llm, messages)
    result = _json_object(text)
    raw_claims = result.get("claims", [])
    claims = []
    for claim in raw_claims if isinstance(raw_claims, list) else []:
        if not isinstance(claim, dict):
            continue
        cited_source = claim.get("cited_source") or None
        citation_supported = (
            bool(claim.get("citation_supported")) if cited_source else None
        )
        grounded = bool(claim.get("grounded", False))
        attributable = (
            bool(claim.get("attributable_to_retrieval")) if grounded else None
        )
        claims.append({
            "text": str(claim.get("text", "")),
            "cited_source": cited_source,
            "grounded": grounded,
            "citation_supported": citation_supported,
            "attributable_to_retrieval": attributable,
        })
    grounded_claims = [claim for claim in claims if claim["grounded"]]
    cited_claims = [claim for claim in claims if claim["cited_source"]]
    supported_citations = [claim for claim in cited_claims if claim["citation_supported"]]
    attributable_claims = [claim for claim in grounded_claims if claim["attributable_to_retrieval"]]
    return {
        "claims": claims,
        "claim_count": len(claims),
        "graded_groundedness_score": len(grounded_claims) / len(claims) if claims else None,
        "faithfulness": "pass" if len(grounded_claims) == len(claims) else "fail",
        "citation_support_rate": (
            len(supported_citations) / len(cited_claims) if cited_claims else None
        ),
        "chunk_attribution_score": (
            len(attributable_claims) / len(grounded_claims) if grounded_claims else None
        ),
    }, usage


def judge_refusal_behavior(
    llm: ChatOpenAI,
    item: dict[str, Any],
    answer_text: str,
    retrieved_context: str,
) -> tuple[str, dict[str, float | int]]:
    """Judge refusals and special adversarial behavior independently of correctness."""
    messages = [
        SystemMessage(
            content=(
                "You evaluate refusal behavior in a RAG answer. Return JSON only as "
                "{\"outcome\": value}, where value is appropriate_refusal, "
                "over_refusal, or hallucinated. appropriate_refusal means the response "
                "followed the required behavior, including answering normally when no "
                "refusal was warranted. over_refusal means it declined an answerable "
                "request without justification. hallucinated means it should have "
                "declined, corrected, qualified, or disambiguated but instead asserted "
                "unsupported information."
            )
        ),
        HumanMessage(
            content=(
                f"ANSWERABLE: {item['answerable']}\n"
                f"ADVERSARIAL KIND: {item.get('adversarial_kind')}\n"
                f"EXPECTED BEHAVIOR: {item.get('expected_behavior')}\n"
                f"QUESTION: {item['question']}\n"
                f"RESPONSE: {answer_text}\n"
                f"RETRIEVED CONTEXT:\n{retrieved_context}"
            )
        ),
    ]
    text, usage = invoke_measured(llm, messages)
    outcome = str(_json_object(text).get("outcome", "hallucinated")).casefold()
    if outcome not in REFUSAL_OUTCOMES:
        outcome = "hallucinated"
    # appropriate_refusal also covers "correctly answered, nothing to decline" -
    # relabel that case to n/a so the column isn't misleading on normal items,
    # where refusal behavior was never actually being tested.
    if outcome == "appropriate_refusal" and item["answerable"] and item.get("adversarial_kind") is None:
        outcome = "n/a"
    return outcome, usage


# %% [markdown]
# ## Step 3 - Golden evaluation set

# %%
def _required_aspects(expected_answer: str) -> list[str]:
    """Create stable claim-sized aspects when an older suite lacks the field."""
    sentences = re.split(r"(?<=[.!?])\s+", expected_answer.strip())
    aspects = []
    for sentence in sentences:
        clauses = re.split(r";\s+", sentence)
        aspects.extend(clause.strip() for clause in clauses if clause.strip())
    return aspects


def my_eval_set(path: Path = GOLDEN_SUITE_PATH) -> list[dict[str, Any]]:
    """Load all records and expose the fields required by the evaluation harness."""
    data = json.loads(path.read_text(encoding="utf-8"))
    records = data.get("queries") if isinstance(data, dict) else data
    if not isinstance(records, list) or not records:
        raise ValueError(f"Expected a non-empty list of golden records in {path}")
    for item in records:
        question = item.get("question") or item.get("query")
        if not question:
            raise ValueError(f"Golden record {item.get('id', '<unknown>')} has no query")
        item["question"] = question
        item["grading_notes"] = item["expected_answer"]
        item["expected_sources"] = item.get("relevant_files", [])
        item["required_sources"] = item.get("required_files") or item["expected_sources"]
        item["required_aspects"] = item.get("required_aspects") or _required_aspects(
            item["expected_answer"]
        )
        item["supporting_quotes"] = item.get("supporting_quotes") or []
    return records


# %% [markdown]
# ## Deterministic metrics (retrieval, citations, evidence)

# %%
def _unique_files(hits: list[Hit]) -> list[str]:
    return list(dict.fromkeys(hit.source_file for hit in hits))


def _source_metrics(
    required_sources: list[str],
    relevant_sources: list[str],
    hits: list[Hit],
) -> dict[str, int | float | bool]:
    """Recall is scored against required_sources (what must be retrieved to
    fully answer) over the set of unique retrieved articles; precision is
    scored against relevant_sources (the broader set) at the unit level
    (chunk_precision_at_k) and the article level (article_precision).
    source_recall_at_3_articles is the matched-count comparison with the
    3.1 baseline's three whole articles."""
    required = {Path(source).name.casefold() for source in required_sources}
    relevant = {Path(source).name.casefold() for source in relevant_sources}
    unique = [name.casefold() for name in _unique_files(hits)]
    retrieved = set(unique)
    required_matches = required & retrieved
    all_required_present = bool(required) and required <= retrieved
    first_three = set(unique[:3])
    relevant_units = sum(hit.source_file.casefold() in relevant for hit in hits)
    chunk_precision = relevant_units / len(hits) if hits else 0.0
    return {
        "source_hit_at_k": int(bool(required_matches)),
        "source_recall_at_k": len(required_matches) / len(required) if required else 0.0,
        "source_recall_at_3_articles": (
            len(required & first_three) / len(required) if required else 0.0
        ),
        "source_precision_at_k": chunk_precision,
        "chunk_precision_at_k": chunk_precision,
        "article_precision": len(relevant & retrieved) / len(retrieved) if retrieved else 0.0,
        "unique_articles_retrieved": len(retrieved),
        "source_recall_strict": 1.0 if all_required_present else 0.0,
        "all_required_present": all_required_present,
    }


_PUNCT_TRANSLATION = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
# Same character map as validate_golden_suite.py, so a quote the validator
# accepted is matched here under identical normalisation.
_MATCH_PUNCT = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "‒": "-", "―": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    "​": "", "‌": "", "‍": "", "﻿": "", "­": "",
    "…": "...",
})
_BRACKET_CITE = re.compile(r"\[\s*(?:\d+|citation needed|note \d+|[a-c])\s*\]", re.IGNORECASE)


def _normalize_evidence(text: str) -> str:
    text = unicodedata.normalize("NFKC", unescape(text)).translate(_PUNCT_TRANSLATION)
    return re.sub(r"\s+", " ", text).strip()


_SUP_BLOCK = re.compile(r"<sup\b[^>]*>.*?</sup>", re.IGNORECASE | re.DOTALL)


def _normalize_for_match(text: str) -> str:
    """Normalise for verbatim matching between a golden quote (validated
    against trafilatura's plain text) and a markdown chunk. Trafilatura's
    markdown renders reference markers as <sup>[\\[4\\]](...)</sup> and shifts
    spaces around link boundaries ("dwarfs , 1988", "$1.84billion",
    "statesgeorge"), so links, superscripts, escaped brackets and bracket
    citations are stripped and the comparison ignores whitespace entirely."""
    text = _SUP_BLOCK.sub("", text)
    text = text.replace("\\[", "[").replace("\\]", "]")
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _BRACKET_CITE.sub("", text)
    text = re.sub(r"[*_`#|<>]+", " ", text)
    text = unicodedata.normalize("NFKC", unescape(text)).translate(_MATCH_PUNCT)
    return re.sub(r"\s+", "", text).casefold()


def _evidence_recall(supporting_quotes: list[dict[str, str]], hits: list[Hit]) -> float | None:
    """Fraction of the record's golden quotes present verbatim in the retrieved
    context. Distinguishes 'retrieved the right article' from 'retrieved the
    passage that actually answers the question'."""
    if not supporting_quotes:
        return None
    context = _normalize_for_match(" ".join(hit.text for hit in hits))
    found = sum(_normalize_for_match(quote["text"]) in context for quote in supporting_quotes)
    return found / len(supporting_quotes)


def _citation_metrics(
    response: str,
    hits: list[Hit],
    expected_sources: list[str],
) -> dict[str, float | int | None]:
    retrieved: dict[str, str] = defaultdict(str)
    for hit in hits:   # several chunks of one article are matched as one text
        retrieved[Path(hit.source_file).name.casefold()] += " " + hit.text
    expected = {Path(name).name.casefold() for name in expected_sources}
    citations = [
        Path(name).name.casefold()
        for name in re.findall(r"\[([^\]\n]+\.html)\]", response, flags=re.IGNORECASE)
    ]
    unique_citations = set(citations)
    citation_precision = (
        len(unique_citations & expected) / len(unique_citations)
        if unique_citations else None
    )
    unsupported_citation_rate = (
        len(unique_citations - set(retrieved)) / len(unique_citations)
        if unique_citations else None
    )

    quotes = [
        match.group(1) or match.group(2)
        for match in re.finditer(r'"([^"\n]{10,})"|“([^”\n]{10,})”', response)
    ]
    normalized_texts = {name: _normalize_for_match(text) for name, text in retrieved.items()}
    faithful = 0
    correctly_attributed = 0
    for quote in quotes:
        normalized_quote = _normalize_for_match(quote)
        matching_sources = {
            name for name, text in normalized_texts.items() if normalized_quote in text
        }
        if matching_sources:
            faithful += 1
        quote_position = response.find(quote)
        prefix = response[max(0, quote_position - 180):quote_position]
        nearby = re.findall(r"\[([^\]\n]+\.html)\]", prefix, flags=re.IGNORECASE)
        attributed = Path(nearby[-1]).name.casefold() if nearby else None
        if attributed and attributed in matching_sources:
            correctly_attributed += 1

    return {
        "response_quote_count": len(quotes),
        "quote_fidelity_rate": faithful / len(quotes) if quotes else None,
        "quote_attribution_accuracy": (
            correctly_attributed / len(quotes) if quotes else None
        ),
        "citation_count": len(unique_citations),
        "citation_precision": citation_precision,
        "unsupported_citation_rate": unsupported_citation_rate,
    }


def _estimated_cost_usd(input_tokens: int, output_tokens: int) -> float | None:
    input_rate = os.getenv("OPENROUTER_INPUT_USD_PER_MILLION")
    output_rate = os.getenv("OPENROUTER_OUTPUT_USD_PER_MILLION")
    if input_rate is None or output_rate is None:
        return None
    return (
        input_tokens * float(input_rate) + output_tokens * float(output_rate)
    ) / 1_000_000


# %% [markdown]
# ## Step 4 - Run the evaluation with the selected retriever

# %%
def _retrieval_record(item: dict[str, Any], hits: list[Hit], trace: dict[str, Any], seconds: float) -> dict[str, Any]:
    return {
        "retrieved_sources": _unique_files(hits),
        "retrieved_units": [
            {"unit_id": hit.unit_id, "source_file": hit.source_file, "role": hit.role, "score": round(hit.score, 4)}
            for hit in hits
        ],
        "unit_count": len(hits),
        "context_chars": sum(len(hit.text) for hit in hits),
        "evidence_recall": _evidence_recall(item["supporting_quotes"], hits),
        "retrieval_trace": trace,
        "retrieval_latency_seconds": seconds,
        **_source_metrics(item["required_sources"], item["expected_sources"], hits),
    }


def _evaluate_item(llm: ChatOpenAI, item: dict[str, Any]) -> tuple[dict[str, Any], list[Hit]]:
    """Retrieve, answer, judge, and score a single golden-suite item."""
    started = time.perf_counter()
    hits, trace = retrieve(item["question"])
    retrieval_seconds = time.perf_counter() - started
    retrieved_context = _format_context(hits)
    if hits:
        response, answer_usage = answer(llm, item["question"], hits)
    else:
        response = "(no documents retrieved)"
        answer_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "latency_seconds": 0.0}
    closed_book_response, closed_book_usage = answer_closed_book(llm, item["question"])
    quality, quality_usage = judge(
        llm, response, item["expected_answer"], item["required_aspects"], retrieved_context,
    )
    claim_judgment, claim_usage = judge_claims(llm, response, retrieved_context, closed_book_response)
    refusal_outcome, refusal_usage = judge_refusal_behavior(llm, item, response, retrieved_context)
    citation_metrics = _citation_metrics(response, hits, item["expected_sources"])
    usages = (answer_usage, closed_book_usage, quality_usage, claim_usage, refusal_usage)
    input_tokens = sum(int(usage["input_tokens"]) for usage in usages)
    output_tokens = sum(int(usage["output_tokens"]) for usage in usages)
    total_latency = sum(float(usage["latency_seconds"]) for usage in usages) + retrieval_seconds
    result = {
        "id": item["id"],
        "question": item["question"],
        "retriever": _retriever.mode,
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
        **_retrieval_record(item, hits, trace, retrieval_seconds),
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
        "throttle_seconds": sum(float(usage.get("throttle_seconds", 0.0)) for usage in usages),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "estimated_cost_usd": _estimated_cost_usd(input_tokens, output_tokens),
    }
    return result, hits


def _print_progress(item: dict[str, Any], result: dict[str, Any], hits: list[Hit], index: int, total: int) -> None:
    retrieved = [(hit.source_file if hit.role == "primary" else f"{hit.source_file} ({hit.role})", round(hit.score, 3)) for hit in hits]
    print("=" * 72)
    print(f"{item['id']} ({index}/{total}): {item['question']}")
    print(f"  retrieved={retrieved}")
    trace = result.get("retrieval_trace") or {}
    if trace.get("sub_queries"):
        print(f"  sub-queries={trace['sub_queries']}")
    if trace.get("matched_categories"):
        print(f"  matched categories={[c['title'] for c in trace['matched_categories']]}")
    print(
        f"  correctness={result['correctness'].upper()} grade={result['graded_correctness']} "
        f"coverage={result['aspect_coverage']:.1%} evidence_recall={result['evidence_recall']} "
        f"unique_articles={result['unique_articles_retrieved']}"
    )
    print(f"  answer: {result['response']}")


def _configuration() -> dict[str, Any]:
    return {
        "retriever": _retriever.mode,
        "unit": RETRIEVER_CONFIGS[_retriever.mode]["unit"],
        "top_k": _retriever.top_k,
        "candidate_pool": _retriever.candidate_pool,
        "weight_bm25": WEIGHT_BM25,
        "weight_vector": WEIGHT_VECTOR,
        "max_chunk_chars": MAX_CHUNK_CHARS if _retriever.mode != "baseline" else None,
        "parent": {
            "mode": _retriever.parent,
            "max_chunks": PARENT_MAX_CHUNKS.get(_retriever.parent),
            "context_budget_chars": _retriever.parent_budget,
        } if _retriever.parent != "none" else None,
        "graph": {
            "seed_k": GRAPH_SEED_K,
            "max_category_size": GRAPH_MAX_CATEGORY_SIZE,
            "relation_weights": GRAPH_RELATION_WEIGHTS,
        } if _retriever.mode == "graph" else None,
        "llm_model": LLM_MODEL,
        "embedding_model": EMBEDDING_MODEL,
        "temperature": TEMPERATURE,
        "run_at": datetime.now().isoformat(timespec="seconds"),
    }


def _write_results(results: list[dict[str, Any]], output_path: Path | None, stem: str = "evaluation") -> tuple[Path, Path | None]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = RESULTS_DIR / f"{stem}_{_retriever.mode}_{stamp}.json"
    output_path.write_text(
        json.dumps({"configuration": _configuration(), "results": results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    csv_path = output_path.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(results[0]))
        writer.writeheader()
        for result in results:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                for key, value in result.items()
            })
    return output_path, csv_path


def _mean(results: list[dict[str, Any]], key: str) -> float | None:
    values = [float(result[key]) for result in results if result.get(key) is not None]
    return sum(values) / len(values) if values else None


def _print_summary(results: list[dict[str, Any]]) -> None:
    k = _retriever.top_k
    passes = sum(result["correctness"] == "pass" for result in results)
    relevant = sum(result["answer_relevance"] == "pass" for result in results)
    faithful = sum(result["faithfulness"] == "pass" for result in results)
    strict = sum(float(result["source_recall_strict"]) for result in results)
    normal_answerable = [
        result for result in results if result["answerable"] and result["adversarial_kind"] is None
    ]
    over_refusals = sum(result["refusal_outcome"] == "over_refusal" for result in normal_answerable)
    print("=" * 72)
    print(f"Retriever: {_retriever.mode}  (top_k={k}, candidate_pool={_retriever.candidate_pool})")
    print(f"Binary correctness: {passes}/{len(results)} ({passes / len(results):.1%})")
    print(f"Answer relevance: {relevant}/{len(results)} ({relevant / len(results):.1%})")
    print(f"Faithfulness (all claims grounded): {faithful}/{len(results)} ({faithful / len(results):.1%})")
    for label, key in [
        ("Mean graded groundedness", "graded_groundedness_score"),
        ("Mean citation support rate", "citation_support_rate"),
        ("Mean chunk attribution (grounded claims not reproducible closed-book)", "chunk_attribution_score"),
    ]:
        value = _mean(results, key)
        if value is not None:
            print(f"{label}: {value:.1%}")
    print(f"Strict source recall@{k} units: {strict / len(results):.1%}")
    print(f"Mean source recall@{k} units: {_mean(results, 'source_recall_at_k'):.1%}")
    print(f"Mean source recall@3 articles (matched-count vs baseline): {_mean(results, 'source_recall_at_3_articles'):.1%}")
    print(f"Mean chunk precision@{k}: {_mean(results, 'chunk_precision_at_k'):.1%}")
    print(f"Mean article precision: {_mean(results, 'article_precision'):.1%}")
    print(f"Mean unique articles retrieved: {_mean(results, 'unique_articles_retrieved'):.2f}")
    evidence = _mean(results, "evidence_recall")
    if evidence is not None:
        print(f"Mean evidence recall (golden quotes present in context): {evidence:.1%}")
    print(f"Mean context size: {_mean(results, 'context_chars'):,.0f} chars")
    for scope in ("single_document", "multi_document"):
        scoped = [result for result in results if result["scope"] == scope]
        if scoped:
            scoped_strict = sum(float(result["source_recall_strict"]) for result in scoped)
            print(f"  {scope}: {scoped_strict:.0f}/{len(scoped)} ({scoped_strict / len(scoped):.1%})")
    print(
        f"Over-refusal rate: {over_refusals}/{len(normal_answerable)} "
        f"({over_refusals / len(normal_answerable):.1%})"
        if normal_answerable else "Over-refusal rate: not available"
    )
    for label, key in [
        ("Mean quote fidelity", "quote_fidelity_rate"),
        ("Mean quote attribution accuracy", "quote_attribution_accuracy"),
        ("Mean citation precision", "citation_precision"),
        ("Mean unsupported citation rate", "unsupported_citation_rate"),
    ]:
        value = _mean(results, key)
        if value is not None:
            print(f"{label}: {value:.1%}")
    for need in sorted({result["information_need"] for result in results}):
        group = [result for result in results if result["information_need"] == need]
        mean_latency = _mean(group, "total_latency_seconds")
        mean_tokens = _mean(group, "total_tokens")
        costs = [result["estimated_cost_usd"] for result in group]
        mean_cost = sum(float(cost) for cost in costs) / len(costs) if all(cost is not None for cost in costs) else None
        cost_text = f", mean estimated cost=${mean_cost:.6f}" if mean_cost is not None else ""
        print(f"{need}: mean latency={mean_latency:.2f}s, mean tokens={mean_tokens:.0f}{cost_text}")


def run_evaluation(limit: int | None = None, output_path: Path | None = None, input_path: Path = GOLDEN_SUITE_PATH) -> None:
    llm = make_llm()
    eval_set = my_eval_set(input_path)
    if limit is not None:
        eval_set = eval_set[:limit]
    results: list[dict[str, Any]] = []
    if output_path is None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        output_path = RESULTS_DIR / f"evaluation_{_retriever.mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    print(f"Checkpoint 4.1 - evaluation  |  scenario: {SCENARIO}  |  retriever: {_retriever.mode}\n")
    for index, item in enumerate(eval_set, 1):
        result, hits = _evaluate_item(llm, item)
        results.append(result)
        _print_progress(item, result, hits, index, len(eval_set))
        log(f"{item['id']}: {item['question']}", json.dumps(result, ensure_ascii=False, default=str))
        # Checkpoint after every record so a crash (rate limit, credit, network)
        # never loses completed judgements.
        _write_results(results, output_path)
    output_path, csv_path = _write_results(results, output_path)
    _print_summary(results)
    print(f"Results JSON: {output_path.resolve()}")
    print(f"Results CSV:  {csv_path.resolve()}")


def run_retrieval_only(input_path: Path, output_path: Path | None, compare_to: Path | None) -> None:
    """Retrieve for every record without calling the answer model or judges:
    cheap enough to verify that a configuration reproduces an earlier run's
    retrieved_sources, or to inspect what the graph traversal adds."""
    eval_set = my_eval_set(input_path)
    reference: dict[str, list[str]] = {}
    if compare_to is not None:
        reference = {
            record["id"]: list(record.get("retrieved_sources", []))
            for record in json.loads(compare_to.read_text(encoding="utf-8"))["results"]
        }
    results: list[dict[str, Any]] = []
    mismatches = 0
    for index, item in enumerate(eval_set, 1):
        started = time.perf_counter()
        hits, trace = retrieve(item["question"])
        record = {
            "id": item["id"],
            "question": item["question"],
            "retriever": _retriever.mode,
            "required_sources": item["required_sources"],
            "expected_sources": item["expected_sources"],
            **_retrieval_record(item, hits, trace, time.perf_counter() - started),
        }
        results.append(record)
        line = f"{item['id']} ({index}/{len(eval_set)}): {record['retrieved_sources']}"
        if reference:
            expected = reference.get(item["id"])
            same = expected == record["retrieved_sources"]
            mismatches += not same
            line += "  MATCH" if same else f"  MISMATCH (reference: {expected})"
        print(line)
        if trace.get("sub_queries"):
            print(f"   sub-queries: {trace['sub_queries']}")
        if trace.get("expansions"):
            print(f"   expansions: {[(e['source_file'], e['relations'][0]) for e in trace['expansions']]}")
        print(
            f"   recall@k={record['source_recall_at_k']:.2f} recall@3art={record['source_recall_at_3_articles']:.2f} "
            f"chunk_prec={record['chunk_precision_at_k']:.2f} art_prec={record['article_precision']:.2f} "
            f"evidence={record['evidence_recall']} unique={record['unique_articles_retrieved']} "
            f"context={record['context_chars']:,} chars"
        )
    if reference:
        print(f"\nRetrieved-source comparison vs {compare_to.name}: {len(eval_set) - mismatches}/{len(eval_set)} records match")
    print(
        f"\nMean recall@k={_mean(results, 'source_recall_at_k'):.1%}  "
        f"recall@3 articles={_mean(results, 'source_recall_at_3_articles'):.1%}  "
        f"chunk precision={_mean(results, 'chunk_precision_at_k'):.1%}  "
        f"article precision={_mean(results, 'article_precision'):.1%}  "
        f"evidence recall={(_mean(results, 'evidence_recall') or 0):.1%}  "
        f"mean context={_mean(results, 'context_chars'):,.0f} chars"
    )
    output_path, _csv = _write_results(results, output_path, stem="retrieval")
    print(f"Retrieval JSON: {output_path.resolve()}")


# %% [markdown]
# ## Step 5 - Validate the framework: can it catch a manipulated answer?

# %%
def validate_framework() -> None:
    llm = make_llm()
    item = my_eval_set()[0]
    hits, _trace = retrieve(item["question"])
    context = _format_context(hits)
    good, _usage = answer(llm, item["question"], hits)
    manipulated = "The 68th Academy Awards did not present a Best Picture award."
    good_result, _usage = judge(llm, good, item["expected_answer"], item["required_aspects"], context)
    manipulated_result, _usage = judge(llm, manipulated, item["expected_answer"], item["required_aspects"], context)
    print("\n--- Framework validation ---")
    print(f"  correct answer     -> {good_result['correctness'].upper()}   (expected PASS)")
    print(f"  manipulated answer -> {manipulated_result['correctness'].upper()}   (expected FAIL)")
    print("  The framework works if it PASSES the correct answer and FAILS the manipulated one.")
    log("FRAMEWORK VALIDATION", f"good={good_result['correctness']} manipulated={manipulated_result['correctness']}")


# %%
def main() -> None:
    global _retriever
    parser = argparse.ArgumentParser(description="Evaluate the Wikipedia RAG system with a selectable retriever.")
    parser.add_argument(
        "--retriever", choices=sorted(RETRIEVER_CONFIGS), default="baseline",
        help="retrieval strategy: baseline (3.1 whole articles), chunks, decompose, graph",
    )
    parser.add_argument("--k", type=int, help="units to retrieve (default per strategy: baseline 3, others 8)")
    parser.add_argument("--pool", type=int, help="fusion candidate pool (default per strategy: baseline 10, others 40)")
    parser.add_argument(
        "--parent", choices=PARENT_MODES, default="none",
        help="widen each chunk hit to its window / section / article before answering (chunk strategies only)",
    )
    parser.add_argument(
        "--parent-budget", type=int, default=PARENT_MAX_CONTEXT_CHARS,
        help=f"total context budget in characters when --parent is used (default {PARENT_MAX_CONTEXT_CHARS})",
    )
    parser.add_argument("--limit", type=int, help="evaluate only the first N records (useful for a low-cost smoke test)")
    parser.add_argument("--output", type=Path, help="path for results JSON")
    parser.add_argument(
        "--input", type=Path, default=GOLDEN_SUITE_PATH,
        help=f"path to the golden-suite JSON to evaluate (default: {GOLDEN_SUITE_PATH.name})",
    )
    parser.add_argument("--build-index", action="store_true", help="build the chunk cache and chunk vector index, then exit")
    parser.add_argument("--retrieval-only", action="store_true", help="retrieve for every record without answering or judging")
    parser.add_argument("--compare-to", type=Path, help="with --retrieval-only: results JSON whose retrieved_sources to compare against")
    parser.add_argument("--validate-framework", action="store_true", help="run the manipulated-answer judge check after evaluation")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if not args.input.is_file():
        parser.error(f"--input file not found: {args.input}")
    if args.compare_to is not None and not args.compare_to.is_file():
        parser.error(f"--compare-to file not found: {args.compare_to}")
    if args.build_index:
        corpus = load_or_build_chunk_corpus()
        build_or_load_chunk_db(corpus)
        return
    if args.parent != "none" and args.retriever == "baseline":
        parser.error("--parent applies to the chunk strategies (chunks, decompose, graph)")
    _retriever = build_retriever(args.retriever, args.k, args.pool, args.parent, args.parent_budget)
    if args.retrieval_only:
        run_retrieval_only(args.input, args.output, args.compare_to)
        return
    run_evaluation(limit=args.limit, output_path=args.output, input_path=args.input)
    if args.validate_framework:
        validate_framework()


if __name__ == "__main__":
    main()

# %% [markdown]
# ## Step 6 - Complete the Capstone Checkpoint 4.1 worksheet
