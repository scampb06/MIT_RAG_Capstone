r"""Capstone Checkpoint 2.1 — Retrieval Strategy Design and Baseline Implementation (starter).
Jupytext-style cell markers (# %% / # %% [markdown]) — runnable as a
plain script AND openable as cells in VS Code / PyCharm / Jupytext.
"""

# %% [markdown]
# # Capstone Checkpoint 2.1 — Retrieval Strategy Design and Baseline Implementation
# **MO-LLM Module 2 / Required Capstone Checkpoint (120 minutes)**
#
# ## What this checkpoint is
#
# In Checkpoint 1.1, you showed that a plain LLM can't reliably answer questions about
# your corpus. Now, you will **add retrieval**: Design a retrieval strategy for your scenario
# and build a **baseline retrieval system** that finds the most relevant documents for
# a query, so the model can ground its answers in them.
#
# This mirrors the Module 2 labs — keyword (BM25), vector (semantic), and hybrid
# retrieval — applied to your own capstone corpus. The graded deliverable is the completed 
# Capstone Checkpoint 2.1 worksheet, which includes your written responses and evidence of your 
# retrieval system implementation and testing. This script provides a small working example of 
# baseline retrieval. Use it to understand the retrieval workflow, then adapt the code to implement 
# and test a baseline retriever using your selected capstone dataset.
#
# **Learning outcomes (Module 2):**
# 1. Design a retrieval strategy appropriate for a given dataset and query type.
# 2. Implement and test a baseline retrieval system using structured and/or semantic
#    approaches.

# %% [markdown]
# ## Step 1 — Keep your capstone scenario
#
# Use the **same scenario** you chose in Checkpoint 1.1.
#
# | Scenario | Corpus | Retrieval considerations |
# |---|---|---|
# | **Research Paper Navigator** | ~150 research-paper PDFs (`Labs/CapstoneDatasets/ResearchPapers/`) | long documents; you'll likely chunk them; questions often name a specific paper or compare papers. |
# | **Wikipedia Retrieval Engine** | ~2,400 Wikipedia HTML articles (`Labs/CapstoneDatasets/Wikipedia/`) | many short-to-medium articles; questions name a figure/place or span several articles. |
#
# A good baseline is keyword (BM25), semantic (embeddings + vector search), or a
# hybrid of both — exactly what you built in Labs 1.2–2.2.

# %% [markdown]
# ## Setup (~5 min)
#
# 1. **Python 3.11 or 3.12**
# 2. `pip install langchain-openai langchain-core langchain-chroma python-dotenv rank-bm25 trafilatura beautifulsoup4 lxml langchain-text-splitters`
# 3. Use the OpenRouter API key provided for this program. This checkpoint uses
#  the `openai/gpt-5.4-mini` chat model and `openai/text-embedding-3-small`
#  embedding model, with usage covered by the course credits.
# 4. Create a `.env` file next to this script: `OPENROUTER_API_KEY=sk-or-v1-...`
#
# This implementation loads the saved Wikipedia HTML corpus from Checkpoint 1.1.
# The first retrieval builds a persistent Chroma database and embeds each complete
# article. Later runs reuse that database, but still embed each incoming query.

# %%
from __future__ import annotations

import warnings
warnings.filterwarnings("ignore")

import os
import re
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from rank_bm25 import BM25Okapi

from Extract_text_from_wikis import extract_wikipedia_text

# %%
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
LLM_MODEL = "openai/gpt-5.4-mini"  # latest small OpenAI model, fast; covered by course credits
EMBEDDING_MODEL = "openai/text-embedding-3-small"
TEMPERATURE = 0.2
TOP_K = 3
CANDIDATE_POOL = 10
WEIGHT_BM25 = 0.5
WEIGHT_VECTOR = 0.5
LOG_PATH = Path.cwd() / "checkpoint_2_1_retrieval.log"
WIKIPEDIA_DIR = r"C:\Users\steph\OneDrive\Documents\MIT RAG\Capstone\Checkpoint 1.1\Wikipedia"
WIKIPEDIA_CHROMA_DIR = str(Path(__file__).with_name("wikipedia_chroma_db"))

# === SET THIS to the scenario you chose in Checkpoint 1.1 ===
SCENARIO = "wikipedia"   # "research_papers" or "wikipedia"

ANSWER_SYSTEM = (
    "You are a helpful assistant. Answer the question using ONLY the provided "
    "documents, and quote from them where you can. If the documents do not contain "
    "the answer, say so rather than guessing."
)


# %%
def check_api_key() -> str:
    load_dotenv()
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Use the OpenRouter API key "
            "provided for this course, put it in a .env file next to this "
            "script, and rerun."
        )
    return key


def make_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=LLM_MODEL,
        temperature=TEMPERATURE,
        api_key=check_api_key(),
        base_url=OPENROUTER_BASE_URL,
    )


def log(label: str, text: str) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"[{ts}] {label}\n{text}\n{'-' * 72}\n")


# %% [markdown]
# ## Wikipedia corpus
#
# Each saved HTML article is converted to a `(filename, extracted text)` tuple.
# The filename serves as the document ID used by retrieval and answer generation.


# %%
WIKIPEDIA_DOCS = extract_wikipedia_text(WIKIPEDIA_DIR)


# %% [markdown]
# ## Step 2 — The baseline hybrid retriever
#
# The retriever combines BM25 keyword scores with Chroma vector distances, following
# the hybrid approach from Lab 2.2. Each complete Wikipedia article is one document.

# %%
def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
        api_key=check_api_key(),
        base_url=OPENROUTER_BASE_URL,
    )


def build_or_load_wikipedia_db() -> Chroma:
    if os.path.isdir(WIKIPEDIA_CHROMA_DIR) and os.listdir(WIKIPEDIA_CHROMA_DIR):
        print(f"Loading existing Wikipedia vector DB from {WIKIPEDIA_CHROMA_DIR}")
        return Chroma(
            persist_directory=WIKIPEDIA_CHROMA_DIR,
            embedding_function=get_embeddings(),
        )

    print("Building Wikipedia vector DB (first run — embedding whole articles)...")
    documents = [
        Document(page_content=text, metadata={"source": filename})
        for filename, text in WIKIPEDIA_DOCS
    ]
    db = Chroma.from_documents(
        documents,
        get_embeddings(),
        persist_directory=WIKIPEDIA_CHROMA_DIR,
    )
    print(f"Indexed {len(documents)} Wikipedia articles.")
    return db


def _normalize(scores: list[float], invert: bool = False) -> list[float]:
    if not scores:
        return []
    low, high = min(scores), max(scores)
    if high == low:
        return [0.5] * len(scores)
    normalized = [(score - low) / (high - low) for score in scores]
    return [1.0 - score for score in normalized] if invert else normalized


class WikipediaHybridRetriever:
    def __init__(self, documents: list[tuple[str, str]], db: Chroma):
        self._filenames = [filename for filename, _text in documents]
        self._texts = [text for _filename, text in documents]
        self._bm25 = BM25Okapi([_tokens(text) for text in self._texts])
        self._db = db

    def _bm25_top_k(self, query: str, k: int) -> list[tuple[str, str, float]]:
        scores = self._bm25.get_scores(_tokens(query))
        top = sorted(
            range(len(scores)),
            key=lambda index: scores[index],
            reverse=True,
        )[:k]
        return [
            (self._filenames[index], self._texts[index], float(scores[index]))
            for index in top
        ]

    def _vector_top_k(self, query: str, k: int) -> list[tuple[str, str, float]]:
        results = self._db.similarity_search_with_score(query, k=k)
        return [
            (document.metadata.get("source", "unknown"), document.page_content, float(score))
            for document, score in results
        ]

    def get_top_k(self, query: str, k: int) -> list[tuple[str, str, float]]:
        bm25_results = self._bm25_top_k(query, CANDIDATE_POOL)
        vector_results = self._vector_top_k(query, CANDIDATE_POOL)

        content_by_name: dict[str, str] = {}
        bm25_normalized: dict[str, float] = {}
        vector_normalized: dict[str, float] = {}

        for (name, content, _score), value in zip(
            bm25_results,
            _normalize([score for _name, _content, score in bm25_results]),
        ):
            content_by_name[name] = content
            bm25_normalized[name] = value

        for (name, content, _distance), value in zip(
            vector_results,
            _normalize(
                [distance for _name, _content, distance in vector_results],
                invert=True,
            ),
        ):
            content_by_name[name] = content
            vector_normalized[name] = value

        fused = [
            (
                name,
                content,
                WEIGHT_BM25 * bm25_normalized.get(name, 0.0)
                + WEIGHT_VECTOR * vector_normalized.get(name, 0.0),
            )
            for name, content in content_by_name.items()
        ]
        fused.sort(key=lambda item: item[2], reverse=True)
        return fused[:k]


_hybrid_retriever: WikipediaHybridRetriever | None = None


def retrieve(query: str, k: int = TOP_K) -> list[tuple[str, str, float]]:
    """Return the top whole Wikipedia articles using BM25-vector fusion."""
    global _hybrid_retriever
    if _hybrid_retriever is None:
        _hybrid_retriever = WikipediaHybridRetriever(
            WIKIPEDIA_DOCS,
            build_or_load_wikipedia_db(),
        )
    return _hybrid_retriever.get_top_k(query, k)


def answer(
    llm: ChatOpenAI,
    query: str,
    documents: list[tuple[str, str, float]],
) -> str:
    context = "\n\n".join(
        f"[{filename}] {text}" for filename, text, _score in documents
    )
    messages = [
        SystemMessage(content=ANSWER_SYSTEM),
        HumanMessage(content=f"Documents:\n{context}\n\nQuestion: {query}"),
    ]
    return llm.invoke(messages).content


# %% [markdown]
# ## Step 3 — Your representative queries (TODO)
#
# Submission item #2 asks for **3-5 representative queries** for your scenario and the
# results your system retrieves for each. Write those queries here. Some good ones include questions that:
#
# - Are answerable from **one** document (tests precision),
# - Need **several** documents (tests recall / aggregation),
# - Have wording that **differs** from the document's wording (i.e., tests whether
#   keyword vs. semantic retrieval matters for your corpus)
#
# Return a list of 3-5 query strings.

# %%
def my_representative_queries() -> list[str]:
    """Return 3-5 representative queries for YOUR chosen scenario.

    TODO — your turn. See the guidance above. Each item is a query string. Pick
    queries that a real user of your system would ask and that require different
    retrieval behaviors (single-doc, multi-doc, paraphrased).

    Delete the raise NotImplementedError line once your code works.
    """
    return [
        "What was the title of Orhan Pamuk's Nobel lecture, in what language "
        "was it delivered, and what personal relationship did he use to "
        "discuss Eastern and Western civilizations?",

        "A major Japanese disaster in 2011 slightly accelerated the planet's "
        "rotation. By how much did it shorten each day?",

        "Compare the Academy Awards ceremonies held a decade apart: who "
        "hosted the 85th and 95th ceremonies, and which film won Best "
        "Picture at each?",

        "The yacht that Mohammed bin Salman bought from its original owner "
        "for approximately 500 million euros provides the first clue. Who "
        "was that original owner, what company does he own, which vodka "
        "brand is it best known for, and what did the Dutch Supreme Court "
        "rule about that brand's rights in 2020?",

        "For each of the 1996, 2004, and 2008 Summer Olympics, list every "
        "city mentioned as having submitted a bid but not winning that "
        "edition's hosting contest.",
    ]

def adversarial_queries() -> list[str]:
    """5 queries designed to stress specific weaknesses of WikipediaHybridRetriever."""
    return [
        # 1. Paraphrase mismatch: avoids "cholera," "Broad Street," and "Snow" entirely,
        #    so BM25 gets near-zero overlap; tests whether whole-article embeddings alone
        #    can still surface 1854_Broad_Street_cholera_outbreak.html
        "Which London physician traced a deadly waterborne gastrointestinal epidemic "
        "to a single contaminated public water pump, and how did he visually prove "
        "the connection?",

        # 2. Lexical false-positive trap: the word "disaster" also appears in unrelated
        #    articles (e.g. Pop_Disaster_Tour.html), and the query needs BOTH
        #    1955_Le_Mans_disaster.html and 1964_Alaska_earthquake.html in a top-3 fusion
        #    that has no cross-document awareness
        "Comparing a 1950s motor-racing catastrophe in France to a 1960s Alaskan "
        "natural disaster, which killed more people, and what safety regulations "
        "followed each?",

        # 3. Indirect date-linking: never says "1980," so BM25 can't match on the year;
        #    requires inferring the year from Ronald_Reagan.html and then re-retrieving
        #    1980_NFL_draft.html purely from an inferred fact, not a keyword
        "In the year Ronald Reagan was first elected U.S. president, which player was "
        "the first overall pick in the NFL's college draft, and which team chose him?",

        # 4. Cross-domain multi-hop via a shared but unstated year: needs
        #    1964_Alaska_earthquake.html AND 1964_Nobel_Prize_in_Literature.html, two
        #    articles with zero shared vocabulary, linked only by an implicit date
        "The author who won the Nobel Prize in Literature the same year a magnitude-9 "
        "earthquake struck Alaska initially refused the honor — who was he, and why "
        "did he decline?",

        # 5. No-match trap: no 1998 Winter Olympics or curling article exists in this
        #    corpus, but close lexical decoys do (1998_NFL_draft.html, other Olympics
        #    years) — tests whether the retriever/LLM will hallucinate from a
        #    superficially similar article instead of reporting no match
        "What was the final score of the men's curling gold-medal match at the 1998 "
        "Winter Olympics in Nagano?",
    ]

def adversarial_queries_round2() -> list[str]:
    return [
        # 1. Deep detail, ~36k chars into a 160k-char article, phrased with no
        #    title vocabulary ("Tōhoku", "Japan", "earthquake", "tsunami").
        #    Whole-article embedding is a diluted average of ~5 chunks, and BM25's
        #    length normalization punishes this very long document, so short
        #    Norway/fjord-heavy articles should outrank it.
        "On the day of a 2011 Pacific megathrust quake, the water in several "
        "Scandinavian fjords appeared to seethe as if boiling and was caught on "
        "film. Which fjord was the most prominent example, and what did "
        "scientists conclude after two years of research had caused it?",

        # 2. Infobox link-only cells are emptied by trafilatura ('Opened by',
        #    'Closed by', 'Cauldron' rows are blank), and the article's
        #    'Opening ceremony' section body is empty in the extracted text.
        #    Retrieval may find the right article, but the answer isn't in it.
        "Who officially opened the 1992 Winter Olympics in Albertville, and "
        "which two people lit the Olympic cauldron at the opening ceremony?",

        # 3. Section-header dependent: the fact lives under
        #    'Honors, recognition and legacy' > 'Estonia', ~59k chars into a
        #    112k-char biography. The query avoids the subject's name so neither
        #    BM25 nor the averaged article embedding has an anchor.
        "Which Baltic prime minister, aged 32 when he took office, said a "
        "particular free-market economist's book was the only economics book "
        "he had read before taking office? Name the book, the country, the "
        "signature reform he introduced, and the prize he won in 2006.",

        # 4. Wikitable with a two-row header and a 'Run-off' column that only
        #    exists because of a round-4 tie. The last run failed a similar
        #    bidding question (generic Olympics list pages crowded out the
        #    year-specific article), and even if retrieved, the LLM must parse
        #    a flattened pipe table whose header row is split in two.
        "In the IOC vote that awarded the 1992 Winter Games, which two cities "
        "tied and were sent to a run-off, what were their run-off vote totals, "
        "and which city was eliminated after the very first round?",

        # 5. Wikilink structure: extract_wikipedia_text() drops all hyperlinks
        #    (include_links is False) and the retriever returns at most 3 whole
        #    articles, so inbound-link enumeration and link-target questions
        #    cannot be answered from the indexed text.
        "On Yuri Shefler's article, which page does the 'Known for' infobox "
        "entry link to, and which other article in the corpus contains a "
        "wikilink pointing to Yuri Shefler's article?",
    ]

# %% [markdown]
# ## Step 4 — Run the baseline and capture the evidence
#
# This runs each query through the baseline retriever and the LLM, printing the
# retrieved document ids/scores and the grounded answer, and logging everything to
# `checkpoint_2_1_retrieval.log`. The retrieved documents from the output are the rest of the evidence for
# submission item #2.

# %%
def run() -> None:
    llm = make_llm()
    # queries = my_representative_queries()
    # queries = adversarial_queries()
    queries = adversarial_queries_round2()
    print(f"Checkpoint 2.1 — baseline retrieval  |  scenario: {SCENARIO}\n")
    for i, query in enumerate(queries, 1):
        hits = retrieve(query, TOP_K)
        print("=" * 72)
        print(f"QUERY {i}: {query}")
        print(f"  retrieved: {hits}")
        if not hits:
            print("  (nothing matched — note this in your writeup)")
            continue
        ans = answer(llm, query, hits)
        print(f"  answer: {ans}\n")
        log(f"QUERY {i}: {query}", f"retrieved={hits}\nanswer={ans}")
    print("=" * 72)
    print("Done. Use the retrieved document results above as evidence in your writeup, and "
          "describe your REAL baseline (over your full corpus) in the submission.")


run()

# %% [markdown]
# ## Step 5 — Your written submission (the graded deliverable)
#
# Use your completed retrieval implementation and test results to complete the Capstone Checkpoint 2.1
# worksheet. In the worksheet, you will document your retrieval approach, provide evidence that your 
# system is functioning, include 3–5 representative queries and retrieved results, and reflect on where
# your approach performs well and where it struggles.  
 
# Save your completed Python file in the appropriate checkpoint folder in your GitHub repository. 
# Upload the completed worksheet only to the learning platform as your graded submission.
