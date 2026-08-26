WITH q AS (
  SELECT ml_generate_embedding_result AS qv
  FROM ML.GENERATE_EMBEDDING(
    MODEL claims.embedder,
    (SELECT 'they rejected my claim saying my diabetes was there before I bought the policy' AS content),
    STRUCT(TRUE AS flatten_json_output, 'RETRIEVAL_QUERY' AS task_type))
)
SELECT clause_id, clause_title, clause_type, source_page, waiting_period_days,
       ROUND(ML.DISTANCE(embedding, (SELECT qv FROM q), 'COSINE'), 4) AS dist
FROM claims.clauses_embedded
WHERE policy_id = 'star_arogya_sanjeevani'
ORDER BY dist
LIMIT 5