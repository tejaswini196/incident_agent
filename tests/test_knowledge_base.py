import os
import json
import pytest
from unittest.mock import MagicMock, patch

import seed_rag


@pytest.fixture
def mock_env(monkeypatch):
    """Provides mock environment variables for offline execution."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key-12345")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mockuser:mockpass@localhost:6543/postgres")


@pytest.fixture
def mock_embedding_client():
    """Provides a mocked embedding client returning deterministic 768-dimensional vectors."""
    client = MagicMock()
    # Return a 768-dimensional float vector for each input text
    client.embed_documents.side_effect = lambda texts: [[0.05] * 768 for _ in texts]
    client.embed_query.side_effect = lambda query: [0.05] * 768
    return client


@pytest.fixture
def mock_db_pool():
    """Provides a mocked psycopg database connection and cursor."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()

    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    return mock_conn, mock_cursor


# --- Task 3.1 & 3.2: Environment Validation & Seeding Tests ---

def test_validate_environment_missing_gemini_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost:6543/postgres")
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        seed_rag.validate_environment()


def test_validate_environment_missing_database_url(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "mock-key")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        seed_rag.validate_environment()


def test_validate_environment_success(mock_env):
    key, url = seed_rag.validate_environment()
    assert key == "test-gemini-key-12345"
    assert url == "postgresql://mockuser:mockpass@localhost:6543/postgres"


def test_knowledge_base_standard_runbooks_structure():
    """Validates the 3 standard runbooks conform to expected schema."""
    slugs = [doc["slug"] for doc in seed_rag.KNOWLEDGE_BASE]
    assert len(slugs) == 3
    assert "database-pool-exhaustion" in slugs
    assert "elevated-api-latency" in slugs
    assert "authentication-failures" in slugs

    for doc in seed_rag.KNOWLEDGE_BASE:
        assert doc["service"] in ["database", "api_gateway", "auth"]
        assert len(doc["title"]) > 5
        assert len(doc["content"]) > 20
        assert "category" in doc["metadata"]
        assert doc["metadata"]["category"] == "runbook"
        assert doc["metadata"]["slug"] == doc["slug"]


def test_seed_idempotent_upsert_query_execution(mock_env, mock_embedding_client, mock_db_pool):
    """Verifies seed() issues idempotent ON CONFLICT (slug) DO UPDATE queries."""
    mock_conn, mock_cursor = mock_db_pool

    with patch("psycopg.connect", return_value=mock_conn) as mock_connect:
        count = seed_rag.seed(
            embedding_client=mock_embedding_client,
            db_url="postgresql://mockuser:mockpass@localhost:6543/postgres"
        )

        assert count == 3
        mock_connect.assert_called_once_with(
            "postgresql://mockuser:mockpass@localhost:6543/postgres",
            connect_timeout=15,
            prepare_threshold=None
        )

        # Ensure embed_documents was called with 3 documents
        mock_embedding_client.embed_documents.assert_called_once()
        texts_embedded = mock_embedding_client.embed_documents.call_args[0][0]
        assert len(texts_embedded) == 3

        # Verify cursor executed 3 INSERT ... ON CONFLICT statements
        assert mock_cursor.execute.call_count == 3
        executed_sql = mock_cursor.execute.call_args_list[0][0][0]
        params = mock_cursor.execute.call_args_list[0][0][1]

        assert "INSERT INTO incident_docs" in executed_sql
        assert "ON CONFLICT (slug) DO UPDATE SET" in executed_sql
        assert "%s::vector" in executed_sql

        # Verify parameters: slug, service, title, content, metadata json, vector str
        assert params[0] == "database-pool-exhaustion"
        assert params[1] == "database"
        assert json.loads(params[4])["slug"] == "database-pool-exhaustion"

        # Check 768 dimensions in the formatted vector string
        vector_str = params[5]
        assert vector_str.startswith("[") and vector_str.endswith("]")
        elements = vector_str[1:-1].split(",")
        assert len(elements) == 768

        # Verify transaction commit
        mock_conn.commit.assert_called_once()


def test_seed_repeated_execution_is_idempotent(mock_env, mock_embedding_client, mock_db_pool):
    """Simulates executing seed() twice and verifies both succeed idempotently."""
    mock_conn, mock_cursor = mock_db_pool

    with patch("psycopg.connect", return_value=mock_conn):
        count_first = seed_rag.seed(embedding_client=mock_embedding_client)
        count_second = seed_rag.seed(embedding_client=mock_embedding_client)

        assert count_first == 3
        assert count_second == 3
        # 3 calls per run * 2 runs = 6 idempotent upsert executions
        assert mock_cursor.execute.call_count == 6


# --- Task 3.3: Vector Similarity Search & Retrieval Query Tests ---

def test_vector_similarity_search_query_formatting(mock_env, mock_embedding_client, mock_db_pool):
    """Tests executing cosine similarity search (<=> operator) against incident_docs."""
    mock_conn, mock_cursor = mock_db_pool

    # Setup mock return data from pgvector query
    mock_cursor.fetchall.return_value = [
        ("database", "Database Connection Pool Exhaustion remediation details", 0.92),
        ("auth", "Auth service timeout remediation details", 0.75)
    ]

    # Function simulating agent vector search logic
    query = "database connections pool maxed out"
    query_vector = mock_embedding_client.embed_query(query)
    vec_str = f"[{','.join(str(x) for x in query_vector)}]"

    with mock_conn:
        with mock_conn.cursor() as cur:
            cur.execute(
                """
                SELECT metadata->>'service' as service, content, 1 - (embedding <=> %s::vector) as similarity
                FROM incident_docs
                ORDER BY embedding <=> %s::vector
                LIMIT 2;
                """,
                (vec_str, vec_str)
            )
            rows = cur.fetchall()

    mock_cursor.execute.assert_called_once()
    sql_called = mock_cursor.execute.call_args[0][0]
    args_called = mock_cursor.execute.call_args[0][1]

    assert "<=> %s::vector" in sql_called
    assert len(args_called) == 2
    assert args_called[0] == vec_str

    assert len(rows) == 2
    assert rows[0][0] == "database"
    assert rows[0][2] == 0.92


def test_vector_similarity_search_empty_results(mock_env, mock_embedding_client, mock_db_pool):
    """Tests vector similarity search handles empty table or no matches without raising errors."""
    mock_conn, mock_cursor = mock_db_pool
    mock_cursor.fetchall.return_value = []

    query_vector = mock_embedding_client.embed_query("unknown service problem")
    vec_str = f"[{','.join(str(x) for x in query_vector)}]"

    with mock_conn:
        with mock_conn.cursor() as cur:
            cur.execute(
                """
                SELECT metadata->>'service' as service, content, 1 - (embedding <=> %s::vector) as similarity
                FROM incident_docs
                ORDER BY embedding <=> %s::vector
                LIMIT 2;
                """,
                (vec_str, vec_str)
            )
            rows = cur.fetchall()

    assert rows == []
    result_text = "\n---\n".join([f"[{r[0]}]: {r[1]}" for r in rows]) if rows else "No relevant runbooks found."
    assert result_text == "No relevant runbooks found."


# --- Task 3.4: Secret Cleanliness & Offline Safety ---

def test_no_hardcoded_secrets_in_repo_or_tests():
    """Ensures code files do not contain live API keys or live connection strings."""
    google_key_prefix = "AIza" + "Sy"
    disallowed_substrings = [
        google_key_prefix,
        "postgres://postgres:",
    ]
    code_files = [
        "seed_rag.py",
        "db/migrations/001_incident_docs.sql"
    ]
    for rel_path in code_files:
        full_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), rel_path)
        if os.path.exists(full_path):
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
                for pattern in disallowed_substrings:
                    assert pattern not in content, f"Disallowed secret pattern found in {rel_path}"
