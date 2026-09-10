from sentence_transformers import SentenceTransformer
import logging

logger = logging.getLogger(__name__)

# Lazy loading of the embedding model to avoid slow startup if not used
_embedding_model = None

def get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        logger.info("Loading embedding model (all-MiniLM-L6-v2)...")
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedding_model

def create_embedding(text: str) -> list[float]:
    """
    Generate a vector embedding for the given text using the global model.
    """
    model = get_embedding_model()
    # normalize_embeddings=True is recommended for cosine similarity
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()
