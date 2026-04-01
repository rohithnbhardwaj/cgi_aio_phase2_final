import chromadb
from chromadb.config import Settings

def search_schema(query, k=5):
    client = chromadb.Client(Settings(persist_directory="./vector_store"))
    col = client.get_collection("db_schema")
    res = col.query(query_texts=[query], n_results=k)
    return res["documents"][0]
