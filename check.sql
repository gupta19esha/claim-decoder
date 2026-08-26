SELECT clause_id, clause_title, clause_type, exclusion_code, source_page, waiting_period_days
FROM claims.clauses
WHERE policy_id = 'star_arogya_sanjeevani'
  AND (source_page BETWEEN 9 AND 12 OR LOWER(clause_title) LIKE '%pre-existing%')
ORDER BY source_page