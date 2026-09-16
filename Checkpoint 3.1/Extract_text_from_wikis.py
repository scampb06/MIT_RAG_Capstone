import os 
import hashlib
from bs4 import BeautifulSoup
import trafilatura 
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter


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


def process_wikipedia_with_links(directory_path: str, max_chunk_chars: int = 2000) -> list[Document]:
    all_chunks = []
    filenames = sorted(
        filename for filename in os.listdir(directory_path) if filename.endswith(".html")
    )
    files_processed = 0
    failures = 0

    # 1. Structural Header Splitter
    headers_to_split_on = [
        ("#", "Header 1"),
        ("##", "Header 2"),
        ("###", "Header 3"),
    ]
    header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)

    # 2. Sub-splitter for long sections
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

            soup = BeautifulSoup(html_content, "lxml")
            page_title = soup.title.get_text(strip=True) if soup.title else None

            if page_title and page_title.endswith(" - Wikipedia"):
                page_title = page_title.removesuffix(" - Wikipedia")

            article_title = page_title or filename.removesuffix(".html").replace("_", " ")
            article_id = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:16]

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
            
    return all_chunks