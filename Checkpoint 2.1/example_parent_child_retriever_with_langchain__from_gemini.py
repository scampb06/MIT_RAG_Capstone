from langchain.retrievers import ParentDocumentRetriever
from langchain_chroma import Chroma
from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.storage import InMemoryStore

# 1. Prepare sample documents (Simulating a long document)
docs = [
    Document(
        page_content="""
        The Apollo program, also known as Project Apollo, was the third United States human spaceflight program carried out by NASA. 
        It succeeded in landing the first humans on the Moon in 1969. 
        
        The mission that achieved this milestone was Apollo 11. Command Module Pilot Michael Collins remained in lunar orbit while Commander Neil Armstrong and Lunar Module Pilot Buzz Aldrin walked on the lunar surface. 
        They spent over two hours exploring and collecting lunar materials to bring back to Earth.
        """,
        metadata={"source": "space_history.txt"}
    )
]

# 2. Define your splitters for Parent and Child chunks
# Parent chunks: Large context (e.g., ~2000 characters)
parent_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)

# Child chunks: Small, granular pieces for embedding search (e.g., ~400 characters)
child_splitter = RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=50)

# 3. Set up the Vector Store (for Child Chunks) and Docstore (for Parent Chunks)
# Note: Ensure you have your OPENAI_API_KEY set up in your environment variables
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = Chroma(collection_name="split_parents", embedding_function=embeddings)

# The docstore maps the unique parent ID to the full parent text
store = InMemoryStore()

# 4. Initialize the ParentDocumentRetriever
retriever = ParentDocumentRetriever(
    vectorstore=vectorstore,
    docstore=store,
    child_splitter=child_splitter,
    parent_splitter=parent_splitter,
)

# 5. Add documents to the retriever
# This automatically creates parents, breaks them into children, embeds children, and links them.
retriever.add_documents(docs, ids=None)

# 6. Test the retrieval
query = "Who stayed in the lunar orbit during Apollo 11?"

# Retrieve relevant documents based on the small child vectors
retrieved_docs = retriever.invoke(query)

# View the result
print(f"Number of retrieved docs: {len(retrieved_docs)}")
print("\n--- Retrieved Content ---")
print(retrieved_docs[0].page_content)
