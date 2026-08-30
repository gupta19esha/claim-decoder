SELECT table_name, ddl
FROM claims.INFORMATION_SCHEMA.TABLES
WHERE table_name IN ('clauses', 'clauses_embedded')
ORDER BY table_name
