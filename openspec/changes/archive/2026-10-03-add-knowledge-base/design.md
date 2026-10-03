# Design: Incident Knowledge Base with Supabase pgvector

## Context

See [proposal.md](file:///c:/Users/TEJASWINISUNKARABOIN/OneDrive/Desktop/incident_agent/openspec/changes/add-knowledge-base/proposal.md) for motivation.

The Autonomous Incident Triage Agent requires access to incident remediation runbooks. To operate entirely within a zero-cost stack (no credit card required), the knowledge base utilizes:
- **Supabase Postgres (Free Tier)**: Hosted PostgreSQL with `pgvector` enabled, accessed via the PgBouncer transaction pooler on port 6543.
- **Google Gemini Embeddings**: `gemini-embedding-2-preview` hosted on Google AI Studio's free tier, configured with `output_dimensionality=768`.
- **Render Web Service (Free Tier)**: 512MB RAM container with ephemeral storage; all knowledge base state must reside in Supabase.

## Goals / Non-Goals

**Goals:**
- Provide a clean SQL migration script (`db/migrations/001_incident_docs.sql`) setting up `pgvector`, the `incident_docs` table, and an HNSW vector index.
- Standardize on 768-dimensional embeddings to minimize index size and memory consumption while preserving semantic retrieval fidelity.
- Implement an idempotent seeding script (`seed_rag.py`) that loads three core incident runbooks and updates them on re-run without duplicating records.
- Provide unit and integration test coverage (`tests/test_knowledge_base.py`) mocking Gemini and Postgres pooler dependencies so tests execute completely offline.

**Non-Goals:**
- Real-time continuous scraping or document synchronization with external wikis (Confluence, Notion, GitHub Markdown).
- Dynamic runtime fine-tuning or re-ranking models (e.g., Cohere Rerank) that exceed free-tier boundaries.
- Complex multi-tenant partition schemas (a single shared `incident_docs` table suffices for the triage agent).

## Decisions

### 1. Table Schema and Idempotency Strategy
- **Decision**: Define `incident_docs` with:
  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;

  CREATE TABLE IF NOT EXISTS incident_docs (
      id BIGSERIAL PRIMARY KEY,
      slug VARCHAR(128) UNIQUE NOT NULL,
      service VARCHAR(64) NOT NULL,
      title VARCHAR(255) NOT NULL,
      content TEXT NOT NULL,
      metadata JSONB DEFAULT '{}'::jsonb,
      embedding vector(768) NOT NULL,
      updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
  );
  ```
- **Rationale**: Adding a unique `slug` (e.g., `db-pool-exhaustion`, `api-high-latency`, `auth-service-timeout`) allows `INSERT ... ON CONFLICT (slug) DO UPDATE` in `seed_rag.py`. This guarantees idempotency: re-running the seed script updates existing runbooks in place without creating duplicate records or wiping out historical IDs.
- **Alternatives Considered**:
  - `TRUNCATE incident_docs` before seeding: Destructive if engineers manually insert additional runbooks.
  - Generating hash IDs from content: Modifying a typo in runbook content would create a new entry instead of updating the existing runbook.

### 2. Vector Indexing: HNSW over IVFFlat
- **Decision**: Create an HNSW index with cosine distance operator:
  ```sql
  CREATE INDEX IF NOT EXISTS incident_docs_embedding_hnsw_idx 
  ON incident_docs 
  USING hnsw (embedding vector_cosine_ops);
  ```
- **Rationale**: IVFFlat requires training lists and performs poorly if created on an empty or sparsely populated table without running `REINDEX` later. HNSW constructs graphs incrementally, providing excellent recall and low query latency immediately upon seeding, even with a small number of runbooks.
- **Alternatives Considered**:
  - `IVFFlat`: Requires at least hundreds of rows to calibrate centroids properly; prone to returning 0 results if lists are misconfigured on tiny datasets.
  - No index (exact flat scan): While fast for <100 docs, an index is required by specification and ensures scalability.

### 3. Embedding Dimensionality: 768 Dimensions
- **Decision**: Configure `gemini-embedding-2-preview` with `output_dimensionality=768` (Matryoshka representation capability).
- **Rationale**: 768 dimensions matches the standard vector configuration in `config.yaml` and fits well within Postgres page sizes and memory limits on Supabase's free tier (500MB database limit).
- **Alternatives Considered**:
  - Full 1536 / 3072 dimensions: Consumes more RAM in the HNSW graph index on Postgres without discernible accuracy gain for concise runbooks.
  - Local PyTorch/HuggingFace embeddings (e.g. `all-MiniLM-L6-v2`): Consumes 300MB+ RAM in the Python process, risking OOM crashes on Render's 512MB RAM ceiling.

### 4. Database Connection Handling for PgBouncer Pooler
- **Decision**: Connect using `psycopg` with `prepare_threshold=None` and connect timeout:
  ```python
  conn = psycopg.connect(
      os.getenv("DATABASE_URL"),
      connect_timeout=15,
      prepare_threshold=None
  )
  ```
- **Rationale**: Supabase transaction poolers (PgBouncer on port 6543) do not support named prepared statements across pooled sessions. Setting `prepare_threshold=None` disables prepared statements and avoids `prepared statement already exists` or invalid connection errors.
- **Alternatives Considered**:
  - Session mode port 5432: Frequently exhausts connections on Supabase free tier when multiple services or development clients connect.

### 5. Standard Incident Runbooks Content
- **Decision**: Seed three canonical runbooks directly matching microservice incident scenarios:
  1. **Database Connection Pool Exhaustion**: Service: `database`. Remediation steps for high connection count, killing idle connections with `pg_terminate_backend`, and adjusting connection pool limits.
  2. **Elevated API Latency**: Service: `api_gateway`. Remediation steps for downstream timeouts, circuit breaker trips, thread pool saturation, and traffic shedding.
  3. **Authentication Failures**: Service: `auth`. Remediation steps for Redis token cache invalidation, key rotation errors, and pod replica restarts.

## Free-Tier Limits & Mitigations

- **Google Gemini Rate Limits (Free Tier: 15 RPM)**:
  - *Risk*: Batch embedding generation during seeding or rapid testing exceeding API quota.
  - *Mitigation*: Batch documents in a single API call (`embed_documents([doc1, doc2, doc3])`) rather than multiple sequential single calls, and mock embeddings in automated test suites.
- **Supabase Connection Limit (Free Tier ~15-20 max connections)**:
  - *Risk*: Leaking connections or exhausting connection slots.
  - *Mitigation*: Connect through port 6543 (transaction pooler) with context managers (`with conn.cursor()`) that close connections immediately after execution.
- **Render Cold Starts**:
  - *Risk*: Initial requests experience 50s delays if Render spins down free instances.
  - *Mitigation*: Seeding script is run as a CLI or migration utility, detached from web server startup.

## Risks / Trade-offs

- **[Risk] Missing pgvector Extension on Target Database** → *Mitigation*: The migration script explicitly runs `CREATE EXTENSION IF NOT EXISTS vector;`.
- **[Risk] Gemini Embedding Dimensionality Mismatch** → *Mitigation*: The embedding client explicitly enforces `output_dimensionality=768` to ensure vector length matches `vector(768)` in the database schema.
- **[Risk] Accidental Secret Leaks** → *Mitigation*: `.env` is listed in `.gitignore`; tests mock configuration without loading real credentials; documentation uses placeholder values (`postgresql://user:pass@host:6543/postgres`).

## Migration Plan

1. Execute migration `db/migrations/001_incident_docs.sql` on the Supabase database.
2. Run `python seed_rag.py` to embed and seed the initial three incident runbooks.
3. Validate seeding by querying top similarity results via `agent.py` or verification script.
4. **Rollback**: If rollback is required, run `DROP TABLE IF EXISTS incident_docs CASCADE;`.
