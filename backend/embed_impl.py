# backend/embed_impl.py
from sentence_transformers import SentenceTransformer
import os

_MODEL_NAME = os.getenv('EMBED_MODEL', 'all-MiniLM-L6-v2')

# instantiate once
_model = SentenceTransformer(_MODEL_NAME)

def embed_text(text: str):
    if text is None:
        return []
    vec = _model.encode([text], show_progress_bar=False)[0]
    # return as plain Python list (float)
    return vec.tolist()