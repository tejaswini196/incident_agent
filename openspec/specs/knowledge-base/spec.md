# Knowledge Base Specification

## Purpose

Provides a vector-indexed knowledge repository of incident runbooks in Supabase Postgres to enable semantic similarity search and idempotent document ingestion during incident triage.

## Requirements

### Requirement: Relational Schema and pgvector Storage
The system SHALL define a database migration creating the `incident_docs` table in Supabase Postgres with a 768-dimensional vector column, metadata JSON/JSONB storage, a unique constraint or deterministic identifier for idempotency, and a vector similarity index.

#### Scenario: Migration creates table and vector index
- **GIVEN** a Postgres database with pgvector extension enabled
- **WHEN** migration `001_incident_docs.sql` is executed
- **THEN** the table `incident_docs` exists with columns for identifier, content, metadata, and 768-dimensional `embedding`, accompanied by a cosine distance index.

### Requirement: Embedding Generation with Gemini
The knowledge base ingestion tool SHALL compute 768-dimensional vector embeddings for incident documents using Google Gemini embeddings (`gemini-embedding-2-preview` with `output_dimensionality=768`).

#### Scenario: Document embedding generation
- **GIVEN** runbook content text and a configured Gemini embeddings client
- **WHEN** document embedding is requested
- **THEN** the client produces a 768-dimensional floating point vector formatted for pgvector insertion.

### Requirement: Idempotent Ingestion of Standard Runbooks
The system SHALL provide an ingestion mechanism in `seed_rag.py` that populates standard incident runbooks idempotently, preventing duplicate document creation upon repeated executions.

#### Scenario: Initial seeding of standard runbooks
- **GIVEN** an empty `incident_docs` table and configured environment variables
- **WHEN** `seed_rag.py` executes
- **THEN** three standard incident runbooks (database connection pool exhaustion, elevated API latency, and authentication failures) are embedded and inserted into `incident_docs`.

#### Scenario: Repeated seeding prevents duplicate entries
- **GIVEN** `incident_docs` already contains the standard incident runbooks
- **WHEN** `seed_rag.py` executes a second time
- **THEN** existing documents are updated or skipped without increasing total document count or producing duplicate rows.

### Requirement: Semantic Vector Similarity Retrieval
The knowledge base SHALL support semantic search using cosine distance (`<=>`) against `incident_docs` to return top matching runbooks and service metadata.

#### Scenario: Successful vector retrieval
- **GIVEN** populated `incident_docs` records and an input query vector of 768 dimensions
- **WHEN** a vector similarity query executes ordered by cosine distance
- **THEN** the most semantically relevant runbook contents and associated service metadata are returned.

#### Scenario: No matching runbooks found
- **GIVEN** an empty `incident_docs` table
- **WHEN** a vector similarity search executes
- **THEN** the system returns an empty result set or indication that no runbooks were found without throwing unhandled exceptions.

### Requirement: Environment Configuration and Secret Protection
The knowledge base system SHALL load database connection strings and API credentials strictly from environment variables and SHALL NOT commit secrets to source control.

#### Scenario: Missing required environment variables
- **GIVEN** `GEMINI_API_KEY` or `DATABASE_URL` is missing from the environment
- **WHEN** the knowledge base seeding or retrieval initializes
- **THEN** a clear configuration error is raised before any external connection is attempted.

#### Scenario: Offline test execution with mocked dependencies
- **GIVEN** mock fixtures for the Gemini embedding client and database connection pool
- **WHEN** the test suite executes in an offline test environment
- **THEN** all knowledge base tests pass without issuing network requests to Google AI Studio or Supabase.
