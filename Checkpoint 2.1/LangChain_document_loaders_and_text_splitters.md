### Tech Architecture Log: LangChain Ingestion & Graph Building Pipeline

### 1. Modern LangChain Ingestion Architecture (Post-Community Sunset)

Following the mid-2026 archive and deprecation of the monolithic langchain-community package, the architecture has shifted away from internal community wrappers toward specialized, standalone parsing utilities wrapped directly inside langchain-core's Document object model. 

### PDF Recommendations

* **Standard Text PDFs (Fast/Lightweight):** Use native pypdf or PyMuPDF looped directly into langchain_core.documents.Document.
* **Complex/Visual Layouts & Tables (Accuracy):** Use IBM's **Docling** via the dedicated langchain-docling partner package.
* **Enterprise Heterogeneous Formats:** Use the standalone unstructured-client SDK or local loaders.

### HTML Recommendations

* **Basic Text Scraping:** Use BeautifulSoup (bs4) directly.
* **Main Body Content & RAG Optimization:** Use **Trafilatura** to extract text as structural Markdown while removing boilerplate (sidebars, footers, scripts).

### 2. Processing 7,000 Wikipedia HTML Files with Entity Links

### Strategy

For local processing of a large corpus like Wikipedia HTMLs, avoid cloud APIs (like Unstructured Client) to eliminate network latency, costs, and rate limits. Use **Trafilatura** locally to strip administrative web wrappers and maintain high-fidelity internal markdown links ([Anchor Text](URL)) to trace entity relationships. 

### Implementation Pipeline

python

import os
import trafilatura
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

def process_wikipedia_with_links(directory_path: str, max_token_chars: int = 2000) -> list[Document]:
    all_chunks = []
    
    # 1. Structural Header Splitter
    headers_to_split_on = [
        ("#", "Header 1"),
        ("##", "Header 2"),
        ("###", "Header 3"),
    ]
    header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    
    # 2. Sub-splitter for long sections
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_token_chars,
        chunk_overlap=200,
        separators=["\n\n", "\n", " ", ""]
    )

    for filename in os.listdir(directory_path):
        if not filename.endswith(".html"):
            continue
            
        file_path = os.path.join(directory_path, filename)
        
        with open(file_path, "r", encoding="utf-8") as f:
            html_content = f.read()
            
        # extract main body text as markdown keeping links
        markdown_text = trafilatura.extract(
            html_content, 
            output_format="markdown",
            include_links=True
        )
        
        if not markdown_text:
            continue
            
        # Split by Wikipedia's internal headings
        section_chunks = header_splitter.split_text(markdown_text)
        final_chunks = text_splitter.split_documents(section_chunks)
        
        # Inject source metadata to map entity relationships back to files
        for chunk in final_chunks:
            chunk.metadata["source_file"] = filename
            chunk.metadata["article_title"] = filename.replace(".html", "").replace("_", " ")
            all_chunks.append(chunk)
            
    return all_chunks

Use code with caution.

### 3. Building and Querying the Entity Relationship Knowledge Graph

Using the Markdown hyperlinks extracted by Trafilatura, a directed dependency graph can be built programmatically using Python's re module and NetworkX. 

### Graph Compilation Script

python

import re
import networkx as nx
from langchain_core.documents import Document

def build_wikipedia_knowledge_graph(chunks: list[Document]) -> nx.DiGraph:
    G = nx.DiGraph()
    
    # Regex to capture Markdown links: [Anchor Text](URL)
    markdown_link_pattern = re.compile(r'\[([^\]]+)\]\((/wiki/[^)]+|\./[^)]+|[^)]+\.html)\)')

    for chunk in chunks:
        source_article = chunk.metadata.get("article_title")
        source_file = chunk.metadata.get("source_file")
        
        if not source_article:
            continue
            
        if not G.has_node(source_article):
            G.add_node(source_article, type="Article", source_file=source_file)
            
        content = chunk.page_content
        matches = markdown_link_pattern.findall(content)
        
        for anchor_text, url in matches:
            target_entity = url.split("/")[-1].replace(".html", "").replace("_", " ")
            
            if not G.has_node(target_entity):
                G.add_node(target_entity, type="Entity")
                
            if G.has_edge(source_article, target_entity):
                G[source_article][target_entity]["weight"] += 1
            else:
                G.add_edge(source_article, target_entity, weight=1, anchor=anchor_text)
                
    return G

Use code with caution.

### Graph-Facilitated Query Types

1. **Global Reasoning & Multi-Hop Retrieval:** Connects disconnected document concepts through intermediate relational nodes (e.g., walking through Topic A -> Inventor -> Birthplace).
2. **Multi-Entity Intersection Queries:** Identifies shared traits or dependencies between multiple separate high-level concepts.
3. **Backlink Traceability (Predecessor Queries):** Dynamically gauges downstream impacts or historical lineages by finding all incoming links referencing a core node.
4. **Topic Mapping & Structural Summarization:** Extracts adjacent structural node neighborhoods to feed highly clustered context to an LLM rather than disjointed semantic paragraphs.

### 4. Local PDF Processing Evaluation (7,000 Files)

### Technology Matrix

Feature / Metric 

langchain-unstructured 

Native PyPDF 

IBM Docling 

****Philosophy****
All-in-one semantic elements pipeline.Lightweight raw text page extractor.AI-driven layout parser.
****Output Format****
Typed element blocks (Title, Table).Flat text string per page.Structured **Markdown** or rich JSON.
****Table Extraction****
Moderate.Fails completely.**Best-in-Class (97.9%)**.
****Execution****
Hybrid (Heavy system binary dependencies locally).100% Local (Pure Python, fast, low overhead).100% Local (Lightweight ML layout models).

### Processing Strategy

* **Avoid Local unstructured:** Building a purely local execution loop for 7,000 files using local unstructured dependencies requires massive C++ system binaries (poppler, tesseract) and runs slowly due to shell execution overhead.
* **Use Docling or PyMuPDF4LLMLoader:** Both are modern, popular utilities indexed on the LangChain Document Loader registry that output native Markdown natively suited for modern context splitters.

### Modern Docling Pipeline Implementation

python

import os
from langchain_docling import DoclingLoader
from langchain_text_splitters import MarkdownHeaderTextSplitter

def pipeline_local_pdfs(directory_path: str):
    all_chunks = []
    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=[
        ("#", "Header 1"),
        ("##", "Header 2")
    ])

    for filename in os.listdir(directory_path):
        if not filename.endswith(".pdf"):
            continue
            
        file_path = os.path.join(directory_path, filename)
        
        # Modern integration package pattern
        loader = DoclingLoader(file_path=file_path)
        documents = loader.load()
        
        for doc in documents:
            chunks = splitter.split_text(doc.page_content)
            for chunk in chunks:
                chunk.metadata["source"] = filename
                all_chunks.append(chunk)
                
    return all_chunks

Use code with caution.