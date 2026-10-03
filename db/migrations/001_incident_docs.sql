-- 001_incident_docs.sql
-- Migration: Setup pgvector extension, incident_docs table, and HNSW cosine vector index

-- 1. Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create incident_docs table for runbooks and incident knowledge
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

-- 3. Create HNSW index for high-recall cosine distance vector similarity search (<=>)
CREATE INDEX IF NOT EXISTS incident_docs_embedding_hnsw_idx
ON incident_docs
USING hnsw (embedding vector_cosine_ops);

-- 4. Create secondary index on service name for filtered retrieval
CREATE INDEX IF NOT EXISTS incident_docs_service_idx
ON incident_docs(service);
