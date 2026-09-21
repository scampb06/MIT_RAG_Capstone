"""
Extract text and links from Wikipedia HTML files.

Install dependencies with:
python -m pip install beautifulsoup4 lxml trafilatura langchain-core langchain-text-splitters networkx

Provides functions to:
1. Extract the main text from HTML files.
2. Process HTML files into document chunks that include links and come with metadata.
3. Create nodes and edges needed to build a graph of articles and their hyperlink relationships.

1. To extract the main text from HTML files, use the `extract_wikipedia_text` function e.g.

WIKIPEDIA_DOCS = extract_wikipedia_text(WIKIPEDIA_DIR)

2. To process HTML files into document chunks that include links and come with metadata, 
use the `process_wikipedia_with_links` function e.g.

WIKIPEDIA_CHUNKS = process_wikipedia_with_links(WIKIPEDIA_DIR)

3. To build a graph using the NetworkX builder run the following code:

import networkx as nx

WIKIPEDIA_GRAPH_DATA = process_wikipedia_with_nodes_and_edges(WIKIPEDIA_DIR)
graph = nx.DiGraph()

for node in WIKIPEDIA_GRAPH_DATA.nodes:
    graph.add_node(node["id"], **node)

for edge in WIKIPEDIA_GRAPH_DATA.edges:
    graph.add_edge(edge["source"], edge["target"], **edge)

The WIKIPEDIA_GRAPH_DATA object groups three related results: WIKIPEDIA_GRAPH_DATA.documents contains the text chunks as 
LangChain Document objects, WIKIPEDIA_GRAPH_DATA.nodes contains normalized Wikipedia article nodes, and 
WIKIPEDIA_GRAPH_DATA.edges contains hyperlink relationships between those articles.

Because all three results are packaged in one object, later code can build a NetworkX graph from WIKIPEDIA_GRAPH_DATA.nodes
and WIKIPEDIA_GRAPH_DATA.edges while using WIKIPEDIA_GRAPH_DATA.documents for vector indexing and semantic retrieval. 
The function process_wikipedia_with_nodes_and_edges performs the extraction and normalization; it does not itself create a NetworkX graph.

"""
import os
import re
import hashlib
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup
import trafilatura
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter


@dataclass
class WikipediaGraphData:
    """Graph-ready Wikipedia content without a dependency on a graph library."""

    documents: list[Document]
    nodes: list[dict[str, object]]
    edges: list[dict[str, object]]


# Page furniture whose links carry little meaning (navboxes alone can add
# dozens of edges per article). Removed before scanning for links.
BOILERPLATE_SELECTORS = [
    ".navbox", ".infobox", ".sidebar", ".hatnote", ".reflist",
    ".mw-editsection", ".catlinks", ".metadata", "#toc",
]

# Matches the target of a markdown link produced by trafilatura, including
# parenthesized titles such as "[Whiplash](./Whiplash_(2014_film))".
MARKDOWN_WIKI_LINK = re.compile(
    r"\]\((?:\./|/wiki/)((?:[^()?#]+|\([^()]*\))+)(?:[?#][^)]*)?\)"
)


def normalize_slug(name: str) -> str:
    """Make filenames and link targets comparable: decode %xx, spaces->_, casefold."""
    return unquote(name).replace(" ", "_").casefold()


def wiki_link_slug(href: str) -> str | None:
    """Return the article slug an <a href> points to, or None if it is not an article link.

    Handles both saved-page links ("/wiki/Foo") and Parsoid/REST-API links ("./Foo").
    """
    parsed = urlparse(href)
    hostname = parsed.hostname.casefold() if parsed.hostname else None
    if hostname and hostname != "wikipedia.org" and not hostname.endswith(".wikipedia.org"):
        return None
    path = parsed.path
    if path.startswith("/wiki/"):
        path = path[len("/wiki/"):]
    elif path.startswith("./"):
        path = path[2:]
    else:
        return None
    return path or None


def slugify_label(label: str) -> str:
    """Normalize an infobox row label (or similar free text) into an edge/property
    key: 'Directed by' -> 'directed_by', 'Spouse(s)' -> 'spouse_s', 'Born' -> 'born'.

    Light normalization only - no controlled vocabulary yet, so near-duplicate
    labels across different infobox templates (e.g. 'Produced by' vs
    'Production by') will slugify to different keys until a mapping is built
    from what actually occurs across the corpus.
    """
    text = re.sub(r"[^a-z0-9]+", "_", label.strip().lower())
    return text.strip("_")


def extract_categories(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Return (display name, link slug) for each real topical category on the
    page, skipping hidden/maintenance categories (e.g. "Articles with short
    description", "Use dmy dates from...") which carry no topical meaning.
    """
    links = soup.select(".mw-normal-catlinks a[href^='/wiki/Category:']")
    results = []
    for anchor in links:
        slug = wiki_link_slug(anchor.get("href", ""))
        if slug is None:
            continue
        results.append((anchor.get_text(strip=True), slug))
    return results


def extract_infobox_data(
    content_root: BeautifulSoup,
    article_id: str,
    filename: str,
    article_ids: dict[str, str],
    file_by_slug: dict[str, str],
) -> tuple[list[dict], dict[str, str]]:
    """Walk the article's infobox once, if it has one, and return:

    - edges: one per <a href> found inside a data cell that resolves to
      another article in this corpus (one edge per link, not one per row -
      a "Starring" row with five linked actors produces five edges).
    - properties: a flat label -> raw text dict covering every row
      regardless of whether it contained any links, for use as attributes
      on the article's own node. No attempt is made to resolve unlinked
      names (e.g. an uncredited co-producer with no wikilink here) to
      other corpus articles - that is a deliberately separate, deferred
      enhancement.

    Must be called before the caller decomposes ".infobox" out of
    content_root as boilerplate.
    """
    infobox = content_root.select_one("table.infobox")
    if infobox is None:
        return [], {}

    edges: list[dict] = []
    properties: dict[str, str] = {}
    for row in infobox.select("tr"):
        label_cell = row.find("th", class_="infobox-label")
        data_cell = row.find("td", class_="infobox-data")
        if label_cell is None or data_cell is None:
            continue
        raw_label = label_cell.get_text(strip=True)
        key = slugify_label(raw_label)
        if not key:
            continue

        properties[key] = data_cell.get_text(" ", strip=True)

        for anchor in data_cell.select("a[href]"):
            slug = wiki_link_slug(anchor.get("href", ""))
            if slug is None:
                continue
            target_filename = file_by_slug.get(normalize_slug(slug))
            if not target_filename or target_filename == filename:
                continue
            edges.append({
                "source": article_id,
                "target": article_ids[target_filename],
                "edge_type": key,
                "source_file": filename,
                "target_file": target_filename,
                "infobox_label": raw_label,
            })
    return edges, properties


def extract_wikipedia_text(directory_path: str) -> list[tuple[str, str]]:
    """Return the filename and extracted main text for each HTML file."""
    articles = []

    for filename in sorted(os.listdir(directory_path)):
        if not filename.endswith(".html"):
            continue

        file_path = os.path.join(directory_path, filename)
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                html_content = file.read()

            text = trafilatura.extract(html_content)
            if text:
                articles.append((filename, text))
        except Exception as error:
            print(f"Failed to extract {filename}: {error}")

    return articles


def process_wikipedia_with_links(
    directory_path: str, max_chunk_chars: int = 2000
) -> list[Document]:
    """Process Wikipedia HTML files into chunks of text with metadata."""
    return process_wikipedia_with_nodes_and_edges(
        directory_path, max_chunk_chars
    ).documents


def process_wikipedia_with_nodes_and_edges(
    directory_path: str, max_chunk_chars: int = 2000
) -> WikipediaGraphData:
    """Extract document chunks plus normalized article nodes and hyperlink edges."""
    all_chunks = []
    nodes = []
    edges = []

    filenames = sorted(
        filename for filename in os.listdir(directory_path) if filename.endswith(".html")
    )
    article_ids = {
        filename: hashlib.sha256(filename.encode("utf-8")).hexdigest()[:16]
        for filename in filenames
    }
    # Look up a file from a link slug; same normalisation applied to both sides.
    file_by_slug = {
        normalize_slug(filename.removesuffix(".html")): filename for filename in filenames
    }
    # Category nodes aren't discovered from a file listing like articles are -
    # a category becomes a node the first time any article references it.
    category_ids: dict[str, str] = {}
    category_nodes_created: set[str] = set()

    files_processed = 0
    failures = 0

    # 1. Split on Wikipedia's section headings. strip_headers=False keeps the
    #    heading text inside the chunk so BM25 and embeddings can see it.
    headers_to_split_on = [("#", "Header 1"), ("##", "Header 2"), ("###", "Header 3")]
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=headers_to_split_on, strip_headers=False
    )

    # 2. Sub-split long sections.
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_chunk_chars,
        chunk_overlap=200,
        separators=["\n\n", "\n", " ", ""],
    )

    for filename in filenames:
        file_path = os.path.join(directory_path, filename)
        article_id = article_ids[filename]
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            # --- Title ---
            soup = BeautifulSoup(html_content, "lxml")
            page_title = soup.title.get_text(strip=True) if soup.title else None
            if page_title:
                page_title = page_title.removesuffix(" - Wikipedia")
            article_title = page_title or filename.removesuffix(".html").replace("_", " ")

            # --- Categories (article -> category edges) ---
            categories = extract_categories(soup)
            category_edges = []
            for name, slug in categories:
                category_id = category_ids.setdefault(
                    slug, hashlib.sha256(slug.encode("utf-8")).hexdigest()[:16]
                )
                category_edges.append({
                    "source": article_id,
                    "target": category_id,
                    "edge_type": "in_category",
                    "source_file": filename,
                    "category_name": name,
                })

            # --- Infobox (typed edges + raw properties) ---
            # Must run before the BOILERPLATE_SELECTORS decompose below, which
            # removes ".infobox" from content_root as part of scrubbing
            # navboxes/sidebars ahead of the generic body-link scan.
            content_root = soup.select_one("#mw-content-text") or soup
            infobox_edges, infobox_properties = extract_infobox_data(
                content_root, article_id, filename, article_ids, file_by_slug
            )

            # --- Links (article -> article edges) ---
            for element in content_root.select(", ".join(BOILERPLATE_SELECTORS)):
                element.decompose()

            article_edges: dict[str, dict] = {}   # target_id -> edge
            candidate_links = 0
            for anchor in content_root.select("a[href]"):
                slug = wiki_link_slug(anchor.get("href", ""))
                if slug is None:
                    continue
                candidate_links += 1

                target_filename = file_by_slug.get(normalize_slug(slug))
                if not target_filename or target_filename == filename:
                    continue

                target_id = article_ids[target_filename]
                edge = article_edges.setdefault(
                    target_id,
                    {
                        "source": article_id,
                        "target": target_id,
                        "edge_type": "links_to",
                        "source_file": filename,
                        "target_file": target_filename,
                        "count": 0,
                        "anchor_texts": [],
                    },
                )
                edge["count"] += 1
                anchor_text = anchor.get_text(" ", strip=True)
                if anchor_text and anchor_text not in edge["anchor_texts"]:
                    edge["anchor_texts"].append(anchor_text)

            if candidate_links == 0:
                print(
                    f"Warning: no recognizable Wikipedia article links found in "
                    f"{filename} (unexpected HTML format?)"
                )

            # --- Text chunks ---
            markdown_text = trafilatura.extract(
                html_content, output_format="markdown", include_links=True
            )
            if not markdown_text:
                raise ValueError("Trafilatura extracted no article text")

            section_chunks = header_splitter.split_text(markdown_text)
            final_chunks = text_splitter.split_documents(section_chunks)

            for chunk_index, chunk in enumerate(final_chunks):
                # Which articles does this particular chunk link to?
                linked_files = {
                    file_by_slug.get(normalize_slug(slug))
                    for slug in MARKDOWN_WIKI_LINK.findall(chunk.page_content)
                }
                linked_ids = sorted(
                    article_ids[f] for f in linked_files if f and f != filename
                )
                chunk.metadata.update(
                    article_id=article_id,
                    chunk_id=f"{article_id}-c{chunk_index:05d}",
                    chunk_index=chunk_index,
                    source_file=filename,
                    article_title=article_title,
                    linked_article_ids=linked_ids, # a list of IDs for local Wikipedia articles linked from the chunk’s text
                )

            # --- Commit: only reached if the whole article succeeded ---
            article_node = {
                "id": article_id,
                "node_type": "article",
                "title": article_title,
                "source_file": filename,
                "chunk_count": len(final_chunks),
            }
            if infobox_properties:
                article_node["infobox"] = infobox_properties
            nodes.append(article_node)
            for name, slug in categories:
                category_id = category_ids[slug]
                if category_id not in category_nodes_created:
                    category_nodes_created.add(category_id)
                    nodes.append({"id": category_id, "node_type": "category", "title": name})
            edges.extend(article_edges.values())
            edges.extend(infobox_edges)
            edges.extend(category_edges)
            all_chunks.extend(final_chunks)

        except Exception as error:
            failures += 1
            print(f"Failed to process {filename}: {error}")
        finally:
            files_processed += 1
            if files_processed % 100 == 0 or files_processed == len(filenames):
                print(
                    f"Progress: {files_processed}/{len(filenames)} files processed, "
                    f"{len(all_chunks)} chunks produced, {failures} failures"
                )

    # Keep only edges whose target article was processed successfully, and
    # take the target title from the real node rather than from the URL slug.
    title_by_id = {node["id"]: node["title"] for node in nodes}
    valid_node_ids = set(title_by_id)
    edges = [edge for edge in edges if edge["target"] in title_by_id]
    for edge in edges:
        edge["target_title"] = title_by_id[edge["target"]]
    for chunk in all_chunks:
        chunk.metadata["linked_article_ids"] = [
            article_id
            for article_id in chunk.metadata["linked_article_ids"]
            if article_id in valid_node_ids
        ]

    return WikipediaGraphData(documents=all_chunks, nodes=nodes, edges=edges)