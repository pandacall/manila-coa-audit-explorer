# One prebuilt SQLite file instead of a managed vector database

The app runs on GCP, but the corpus is only a few thousand chunks, and the demo must cost close to nothing when idle and outlive the free trial. Vertex AI Vector Search bills an always-on endpoint (about $68/month), and Cloud SQL with pgvector about $8/month. So we build a single SQLite file offline — FTS5 for keyword search, `sqlite-vec` for embeddings, plus the observation-link and financial-line tables — and ship it inside the Cloud Run image, rebuilding it on each deploy.

## Consequences

- The index is read-only at runtime; changing the corpus means a rebuild and redeploy.
- Mutable state (the daily question cap) lives elsewhere (Firestore), not in this file.
- Revisit if the corpus grows by orders of magnitude (more cities or more years).
