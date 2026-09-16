import os 
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
    pending_edges = {}
    filenames = sorted(
        filename for filename in os.listdir(directory_path) if filename.endswith(".html")
    )
    filename_lookup = {filename.casefold(): filename for filename in filenames}
    article_ids = {
        filename: hashlib.sha256(filename.encode("utf-8")).hexdigest()[:16]
        for filename in filenames
    }
    files_processed = 0
    failures = 0

    # 1. Create Structural Header Splitter object that can split text according to selected heading levels
    headers_to_split_on = [
        ("#", "Header 1"),
        ("##", "Header 2"),
        ("###", "Header 3"),
    ]
    header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)

    # 2. Create sub-splitter object for long sections that can divide text into smaller chunks
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_chunk_chars,
        chunk_overlap=200,
        separators=["\n\n", "\n", " ", ""]
    )

    for filename in filenames:
        file_path = os.path.join(directory_path, filename)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            soup = BeautifulSoup(html_content, "lxml") # create a DOM-like parse tree
            page_title = soup.title.get_text(strip=True) if soup.title else None

            if page_title and page_title.endswith(" - Wikipedia"):
                page_title = page_title.removesuffix(" - Wikipedia")

            article_title = page_title or filename.removesuffix(".html").replace("_", " ")
            article_id = article_ids[filename]

            nodes.append(
                {
                    "id": article_id,
                    "node_type": "article",
                    "title": article_title,
                    "source_file": filename,
                }
            )

            content_root = soup.select_one("#mw-content-text") or soup
            for anchor in content_root.select("a[href]"):
                href = anchor.get("href")
                if not isinstance(href, str):
                    continue

                parsed_url = urlparse(href)
                if parsed_url.netloc and not parsed_url.netloc.casefold().endswith("wikipedia.org"):
                    continue
                if not parsed_url.path.startswith("/wiki/"):
                    continue

                target_slug = unquote(parsed_url.path.removeprefix("/wiki/")).replace(" ", "_")
                if not target_slug or ":" in target_slug:
                    continue

                target_filename = filename_lookup.get(f"{target_slug}.html".casefold())
                if not target_filename or target_filename == filename:
                    continue

                target_id = article_ids[target_filename]
                edge_key = (article_id, target_id)
                anchor_text = anchor.get_text(" ", strip=True)
                if edge_key not in pending_edges:
                    pending_edges[edge_key] = {
                        "source": article_id,
                        "target": target_id,
                        "edge_type": "links_to",
                        "source_file": filename,
                        "target_file": target_filename,
                        "target_title": target_slug.replace("_", " "),
                        "target_url": f"https://en.wikipedia.org/wiki/{target_slug}",
                        "anchor_texts": [],
                    }
                if anchor_text and anchor_text not in pending_edges[edge_key]["anchor_texts"]:
                    pending_edges[edge_key]["anchor_texts"].append(anchor_text)

            # Extract main body text as markdown while preserving links.
            markdown_text = trafilatura.extract(
                html_content,
                output_format="markdown",
                include_links=True,
            )

            if not markdown_text:
                raise ValueError("Trafilatura extracted no article text")

            # Split by Wikipedia's internal headings, then split long sections.
            section_chunks = header_splitter.split_text(markdown_text)
            final_chunks = text_splitter.split_documents(section_chunks)

            for chunk_index, chunk in enumerate(final_chunks):
                chunk.metadata["article_id"] = article_id
                chunk.metadata["chunk_id"] = f"{article_id}-c{chunk_index:05d}"
                chunk.metadata["chunk_index"] = chunk_index
                chunk.metadata["source_file"] = filename
                chunk.metadata["article_title"] = article_title
                all_chunks.append(chunk)
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
            
    valid_node_ids = {node["id"] for node in nodes}
    edges = [
        edge
        for edge in pending_edges.values()
        if edge["source"] in valid_node_ids and edge["target"] in valid_node_ids
    ]
    return WikipediaGraphData(documents=all_chunks, nodes=nodes, edges=edges)