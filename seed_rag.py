import os
import json
from pathlib import Path
from dotenv import load_dotenv
import psycopg
from langchain_google_genai import GoogleGenerativeAIEmbeddings

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

KNOWLEDGE_BASE = [
    {
        "slug": "database-pool-exhaustion",
        "service": "database",
        "title": "Database Connection Pool Exhaustion",
        "content": (
            "Database Connection Pool Exhaustion: Occurs when client connections reach max_connections "
            "or pool queue times out. Remediation: Terminate idle transactions using pg_terminate_backend, "
            "inspect locks using pg_stat_activity, scale read replica pool size, and verify PgBouncer transaction mode."
        ),
        "metadata": {
            "service": "database",
            "category": "runbook",
            "severity": "CRITICAL",
            "slug": "database-pool-exhaustion"
        }
    },
    {
        "slug": "elevated-api-latency",
        "service": "api_gateway",
        "title": "Elevated API Latency",
        "content": (
            "Elevated API Latency: When p99 latency exceeds 1.5s across gateway endpoints due to downstream "
            "microservice saturation, thread pool starvation, or queue congestion. Remediation: Inspect downstream "
            "service health, enable circuit breakers, activate rate-limiting, and shed non-critical background traffic."
        ),
        "metadata": {
            "service": "api_gateway",
            "category": "runbook",
            "severity": "HIGH",
            "slug": "elevated-api-latency"
        }
    },
    {
        "slug": "authentication-failures",
        "service": "auth",
        "title": "Authentication Failures and Token Timeouts",
        "content": (
            "Authentication Failures and Token Timeouts: Triggered by Redis cache evictions, token refresh "
            "lock contention, or invalid JWT signing keys resulting in 504 gateway timeouts. Remediation: Flush "
            "expired token blacklist in Redis, verify token issuer keys, and restart auth pod replicas if degradation persists."
        ),
        "metadata": {
            "service": "auth",
            "category": "runbook",
            "severity": "HIGH",
            "slug": "authentication-failures"
        }
    }
]


def validate_environment():
    """Validates required environment variables fail fast before network calls."""
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key or not gemini_key.strip():
        raise ValueError("Environment variable 'GEMINI_API_KEY' is required but not set.")

    db_url = os.getenv("DATABASE_URL")
    if not db_url or not db_url.strip():
        raise ValueError("Environment variable 'DATABASE_URL' is required but not set.")

    return gemini_key.strip(), db_url.strip()


def get_embedding_client(api_key: str | None = None) -> GoogleGenerativeAIEmbeddings:
    """Instantiates the Gemini embedding client with 768 output dimensions."""
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("Environment variable 'GEMINI_API_KEY' is required but not set.")
    return GoogleGenerativeAIEmbeddings(
        model="gemini-embedding-2-preview",
        google_api_key=key,
        task_type="RETRIEVAL_DOCUMENT",
        output_dimensionality=768
    )


def seed(docs=None, embedding_client=None, db_url=None):
    """Idempotently seeds incident runbooks into Supabase pgvector."""
    gemini_key, default_db_url = validate_environment()
    target_db_url = db_url or default_db_url
    target_docs = docs if docs is not None else KNOWLEDGE_BASE

    client = embedding_client or get_embedding_client(gemini_key)

    print(f"Generating Gemini embeddings (768 dimensions) for {len(target_docs)} runbooks...")
    texts = [doc["content"] for doc in target_docs]
    vectors = client.embed_documents(texts)

    print("Connecting to Supabase Postgres pooler with prepare_threshold=None...")
    with psycopg.connect(target_db_url, connect_timeout=15, prepare_threshold=None) as conn:
        with conn.cursor() as cur:
            for doc, vec in zip(target_docs, vectors):
                vec_str = f"[{','.join(str(x) for x in vec)}]"
                cur.execute(
                    """
                    INSERT INTO incident_docs (slug, service, title, content, metadata, embedding, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s::vector, CURRENT_TIMESTAMP)
                    ON CONFLICT (slug) DO UPDATE SET
                        service = EXCLUDED.service,
                        title = EXCLUDED.title,
                        content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding,
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    (
                        doc["slug"],
                        doc["service"],
                        doc["title"],
                        doc["content"],
                        json.dumps(doc["metadata"]),
                        vec_str
                    )
                )
        conn.commit()

    print(f"Success! Idempotently seeded {len(target_docs)} runbooks into Supabase pgvector.")
    return len(target_docs)


if __name__ == "__main__":
    seed()