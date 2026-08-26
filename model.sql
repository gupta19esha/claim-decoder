CREATE OR REPLACE MODEL claims.embedder REMOTE WITH CONNECTION `project-37e668b0-6b36-4e1f-a02.us.vertex_conn` OPTIONS (ENDPOINT = 'text-embedding-004')
