WITH q AS (
  SELECT ml_generate_embedding_result AS qv
  FROM ML.GENERATE_EMBEDDING(
    MODEL claims.embedder,
    (SELECT 'claim rejected because diabetes existed before the policy started' AS content),
    STRUCT(TRUE AS flatten_json_output, 'RETRIEVAL_QUERY' AS task_type))
)
SELECT clause_title, clause_type, exclusion_code, source_page, waiting_period_days,
       ROUND(ML.DISTANCE(embedding, (SELECT qv FROM q), 'COSINE'), 4) AS dist
FROM claims.clauses_embedded
WHERE policy_id = 'star_arogya_sanjeevani'
ORDER BY dist
LIMIT 15