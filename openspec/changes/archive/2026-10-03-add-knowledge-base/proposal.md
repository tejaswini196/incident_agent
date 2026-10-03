# Proposal: Add Incident Knowledge Base

## Why

During microservice incidents, on-call engineers need rapid, semantically relevant access to remediation runbooks rather than scouring static wiki pages. The Autonomous Incident Triage Agent relies on an incident knowledge base to retrieve actionable remediation steps for degraded services before escalating or taking manual action. Establishing this knowledge base with Supabase Postgres and pgvector provides durable, low-latency semantic search over incident runbooks with zero ongoing infrastructure costs.

## What Changes

- Create a database migration at `db/migrations/001_incident_docs.sql` to enable the `vector` extension, establish the `incident_docs` table with a 768-dimensional vector column, and create an HNSW/IVFFlat index for cosine distance search.
- Configure dependency management in `requirements.txt` ensuring `psycopg[binary,pool]`, `langchain-google-genai`, `python-dotenv`, and test dependencies (`pytest`, `unittest.mock`) are locked and specified.
- Update `seed_rag.py` to ingest three standardized incident runbooks (database connection pool exhaustion, elevated API latency, and authentication failures) with Gemini embeddings (`gemini-embedding-2-preview`, 768 dimensions).
- Implement idempotent seeding (using deterministic document hashing/unique identifiers or upsert semantics) so re-running the seed script does not create duplicate entries.
- Add automated unit/integration tests in `tests/test_knowledge_base.py` validating embedding generation, idempotent seeding logic, vector query formatting, and error handling with mocked Gemini and Supabase database calls.
- Enforce strict environment variable configuration (`GEMINI_API_KEY`, `DATABASE_URL`) without committing any secrets.

## Capabilities

### New Capabilities

- `knowledge-base`: Manages the schema, vector storage, idempotent seeding, and semantic retrieval of incident remediation runbooks using Supabase Postgres (pgvector) and Gemini 768-dimensional embeddings.

### Modified Capabilities

*(None. This is the initial capability specification for the project.)*

## Impact

- **Affected Files**:
  - `db/migrations/001_incident_docs.sql` (new)
  - `seed_rag.py` (updated for idempotent upsert, expanded runbooks, and robust error handling)
  - `requirements.txt` (updated with test and runtime dependencies)
  - `tests/test_knowledge_base.py` (new)
- **External Dependencies & Services**: Supabase Postgres with pgvector (accessed via transaction pooler on port 6543), Google Gemini Embeddings API (`gemini-embedding-2-preview`).
- **Configuration & Security**: Consumes `DATABASE_URL` and `GEMINI_API_KEY` exclusively from environment variables via `python-dotenv`. No secrets or credentials committed.

## Rollback Note

If this migration or seeding needs to be reverted:
1. Run a rollback script or command executing `DROP TABLE IF EXISTS incident_docs CASCADE;` in the target Supabase Postgres database.
2. In-flight agent queries against `incident_docs` will return "No relevant runbooks found" or raise a database table missing error.
3. Code changes in `seed_rag.py` and `requirements.txt` can be cleanly reverted via Git without affecting other components.
