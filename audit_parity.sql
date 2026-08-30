SELECT
  policy_id,
  COUNT(*)                                    AS n,
  COUNTIF(waiting_period_days IS NOT NULL)    AS wpd_n,
  SUM(waiting_period_days)                    AS wpd_sum,
  COUNTIF(monetary_cap IS NOT NULL)           AS cap_n,
  SUM(monetary_cap)                           AS cap_sum,
  COUNTIF(percent_cap IS NOT NULL)            AS pct_n,
  ROUND(SUM(percent_cap), 2)                  AS pct_sum
FROM claims.clauses
GROUP BY policy_id
ORDER BY policy_id
