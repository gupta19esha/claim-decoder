FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Every module, not just main.py. Copying one file by name meant bill_audit.py
# was missing from the image and the endpoint 500'd on its import.
COPY *.py ./

# Cloud Run supplies PORT. Do not hardcode 8080 in the CMD.
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
