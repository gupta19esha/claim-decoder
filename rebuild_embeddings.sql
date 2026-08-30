-- Rebuild clauses_embedded from clauses.
--
-- retrieve() in backend/main.py queries clauses_embedded, not clauses, so a
-- load into clauses changes nothing the user sees until this runs. The two
-- tables drifting apart is a silent failure: the API keeps serving the old
-- corpus and looks perfectly healthy doing it.
--
-- task_type is RETRIEVAL_DOCUMENT here and RETRIEVAL_QUERY on the query side
-- in retrieve(). They are the two halves of one asymmetric embedding scheme
-- and must stay paired.
CREATE OR REPLACE TABLE claims.clauses_embedded AS
SELECT
  * EXCEPT (content,
            ml_generate_embedding_result,
            ml_generate_embedding_statistics,
            ml_generate_embedding_status),
  ml_generate_embedding_result AS embedding
FROM ML.GENERATE_EMBEDDING(
  MODEL claims.embedder,
  (SELECT *, clause_text AS content FROM claims.clauses),
  STRUCT(TRUE AS flatten_json_output, 'RETRIEVAL_DOCUMENT' AS task_type)
)
