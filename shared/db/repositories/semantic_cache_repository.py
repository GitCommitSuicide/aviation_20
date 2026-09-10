import psycopg
from datetime import datetime, timedelta
from shared.db.connection import get_connection

CACHE_THRESHOLD = 0.15

def get_cached_response(
    embedding: list[float],
    query_type: str = "general",
    language: str = "en",
    threshold: float = CACHE_THRESHOLD
) -> str | None:
    """
    Search the semantic_cache table for a matching previous query using cosine distance.
    Returns the response text if a match is found below the distance threshold and isn't expired.
    """
    sql = """
        SELECT
            response,
            embedding <=> %s::vector AS distance
        FROM semantic_cache
        WHERE
            query_type = %s
            AND language = %s
            AND (expires_at IS NULL OR expires_at > NOW())
        ORDER BY embedding <=> %s::vector
        LIMIT 1;
    """
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            # We need to format the embedding list as a vector string, psycopg can handle lists natively 
            # if registered, but string format '[1.0, 2.0, ...]' is universally safe.
            emb_str = f"[{','.join(map(str, embedding))}]"
            
            cur.execute(sql, (emb_str, query_type, language, emb_str))
            result = cur.fetchone()
            
            if not result:
                return None
                
            response, distance = result
            if distance <= threshold:
                return response
                
    return None

def save_to_cache(
    query: str,
    response: str,
    embedding: list[float],
    query_type: str = "general",
    language: str = "en",
    expires_in_hours: int = 24
) -> None:
    """
    Save a new query and response to the semantic cache.
    """
    sql = """
        INSERT INTO semantic_cache (
            query,
            response,
            embedding,
            query_type,
            language,
            expires_at
        )
        VALUES (%s, %s, %s::vector, %s, %s, %s)
    """
    
    expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)
    emb_str = f"[{','.join(map(str, embedding))}]"
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (query, response, emb_str, query_type, language, expires_at)
            )
        conn.commit()
