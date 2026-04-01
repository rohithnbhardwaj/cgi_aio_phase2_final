#!/usr/bin/env python3
"""
Final schema_ingest.py - FIXED CONNECTION LOGIC
- Uses dict-based connection to avoid "invalid dsn" errors
- Bypasses /.cache permission errors using direct path loading
- Uses Modern ChromaDB PersistentClient
- Includes chunked() helper function
"""

import os
import sys
import time
import logging
import argparse
from typing import List

from dotenv import load_dotenv
import psycopg2
from psycopg2 import sql, OperationalError
import chromadb
import traceback
from sentence_transformers import SentenceTransformer

# --- configuration / defaults ---
DEFAULT_MODEL = "all-MiniLM-L6-v2"
DEFAULT_BATCH_SIZE = 64
CHROMA_DIR = "./vector_store"

# Verified container path to bypass Hub/Permission issues
VERIFIED_MODEL_PATH = "/home/streamlit/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots/c9745ed1d9f207416be6d2e6f8de32d1f16199bf"

log = logging.getLogger("schema_ingest")
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

def load_env():
    """Loads environment variables from expected paths."""
    for p in ("/app/.env", ".env", "../.env"):
        if os.path.exists(p):
            load_dotenv(p)
            log.info("Loaded env from: %s", p)
            return
    log.info("No .env file found — using system environment variables.")

def build_db_params():
    """Builds a dictionary of parameters for psycopg2."""
    return {
        "dbname": os.getenv("POSTGRES_DB") or "streamlitdb",
        "user": os.getenv("POSTGRES_USER") or "streamlit",
        "password": os.getenv("POSTGRES_PASSWORD"),
        "host": os.getenv("POSTGRES_HOST") or "db",
        "port": os.getenv("POSTGRES_PORT") or "5432",
    }

def get_schema_rows() -> List[tuple]:
    """Fetches schema info using dict-based connection."""
    params = build_db_params()
    
    # Log connection attempt (hiding password)
    logged_params = params.copy()
    if logged_params.get("password"):
        logged_params["password"] = "****"
    log.info("Connecting to Postgres with: %s", logged_params)

    try:
        # Use ** unpacking to pass dict as keyword arguments
        conn = psycopg2.connect(**params)
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema='public'
            ORDER BY table_name, ordinal_position;
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        log.error("Failed to query Postgres schema: %s", e)
        raise

def chunked(iterable, size):
    """Helper function to break list into batches."""
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]

def retry_fn(fn, attempts=4, delay=2, backoff=2, on_exception=None):
    last_exc = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if on_exception:
                on_exception(e, i + 1)
            sleep = delay * (backoff ** i)
            log.warning("Attempt %s failed, retrying in %s seconds...", i + 1, sleep)
            time.sleep(sleep)
    log.error("All %s attempts failed.", attempts)
    raise last_exc

def load_model_with_retry(model_name: str):
    def _load():
        log.info("Loading embedding model: %s", model_name)
        if os.path.exists(VERIFIED_MODEL_PATH):
            log.info("Found local snapshot. Loading directly to bypass permission issues.")
            return SentenceTransformer(VERIFIED_MODEL_PATH)
        return SentenceTransformer(model_name)

    def on_exc(e, attempt):
        log.warning("Model load attempt %s error: %s", attempt, e)

    return retry_fn(_load, attempts=4, on_exception=on_exc)

def main(args):
    # Ensure HOME is set so libraries don't default to root /
    if 'HOME' not in os.environ:
        os.environ['HOME'] = '/home/streamlit'
    
    load_env() 
    model_name = args.model or DEFAULT_MODEL
    batch_size = args.batch_size or DEFAULT_BATCH_SIZE

    # 1. Fetch Schema
    try:
        schema_rows = get_schema_rows()
        log.info(f"Fetched {len(schema_rows)} column definitions from Postgres.")
    except Exception:
        sys.exit(1)

    if not schema_rows:
        log.info("No tables found. Nothing to ingest.")
        return

    documents = [f"Table {t}, column {c}, type {d}" for t, c, d in schema_rows]
    ids = [f"schema_{i}" for i in range(len(schema_rows))]

    # 2. Load Embedding Model
    try:
        model = load_model_with_retry(model_name)
    except Exception as e:
        log.error("Fatal: Could not load SentenceTransformer: %s", e)
        sys.exit(1)

    # 3. Connect to ChromaDB
    log.info("Connecting to ChromaDB at: %s", CHROMA_DIR)
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_or_create_collection(
        name="db_schema", 
        metadata={"source": "postgres"}
    )

    # 4. Generate Embeddings in Batches
    log.info("Generating embeddings for %d items...", len(documents))
    all_embeddings = []
    try:
        for chunk_docs in chunked(documents, batch_size):
            emb = model.encode(chunk_docs, show_progress_bar=False)
            all_embeddings.extend([e.tolist() for e in emb])
    except Exception as e:
        log.error("Error during embedding generation: %s", e)
        sys.exit(1)

    # 5. Upsert to Vector Store
    log.info("Upserting into Chroma...")
    try:
        collection.upsert(
            documents=documents,
            embeddings=all_embeddings,
            ids=ids
        )
    except Exception as e:
        log.error("Error writing to ChromaDB: %s", e)
        sys.exit(1)

    log.info("✅ Schema ingestion completed successfully!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str)
    parser.add_argument("--batch-size", type=int)
    main(parser.parse_args())