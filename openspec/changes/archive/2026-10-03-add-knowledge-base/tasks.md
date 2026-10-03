# Tasks

## 1. Environment & Migration Setup

- [x] 1.1 Update `requirements.txt` to include `pytest`, `pytest-mock`, `psycopg[binary,pool]>=3.1.0`, `langchain-google-genai>=2.0.0`, and `python-dotenv>=1.0.0`, verifying that all required dependencies are present and compatible.
- [x] 1.2 Create migration file `db/migrations/001_incident_docs.sql` enabling the `vector` extension, creating table `incident_docs` (with `id`, `slug UNIQUE`, `service`, `title`, `content`, `metadata JSONB`, `embedding vector(768)`, `updated_at`), and an HNSW cosine distance index (`incident_docs_embedding_hnsw_idx`), verifying SQL syntax.

## 2. Seed Script & Idempotent Ingestion

- [x] 2.1 Define three standardized runbook records in `seed_rag.py` (database connection pool exhaustion, elevated API latency, and authentication failures) with unique slugs, service identifiers, and structured metadata.
- [x] 2.2 Implement idempotent ingestion logic in `seed_rag.py` utilizing Gemini embeddings (`gemini-embedding-2-preview` with `output_dimensionality=768`) and PostgreSQL `INSERT ... ON CONFLICT (slug) DO UPDATE` through `psycopg` with `prepare_threshold=None`.
- [x] 2.3 Add environment variable validation in `seed_rag.py` ensuring `GEMINI_API_KEY` and `DATABASE_URL` fail fast with descriptive error messages when missing, verifying that no secrets are hardcoded or written to repository files.

## 3. Unit & Offline Mock Testing

- [x] 3.1 Create test suite `tests/test_knowledge_base.py` with pytest fixtures mocking `GoogleGenerativeAIEmbeddings` (producing deterministic 768-dim vectors) and `psycopg.connect` / connection cursor.
- [x] 3.2 Implement tests in `tests/test_knowledge_base.py` validating that `seed()` formats SQL upsert queries correctly and executes idempotently without generating duplicate documents.
- [x] 3.3 Implement tests in `tests/test_knowledge_base.py` validating vector similarity search query formatting (`<=>` cosine distance operator) and handling of both matching and empty result sets.
- [x] 3.4 Execute `pytest tests/test_knowledge_base.py` and verify all tests pass completely offline without external network calls to Gemini or Supabase, confirming repository cleanliness and `.gitignore` coverage.
