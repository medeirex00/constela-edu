# SGPE — API (FastAPI)
FROM python:3.13-slim

# psycopg (PostgreSQL) roda em modo binário — sem toolchain de compilação
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "psycopg[binary]==3.2.3"

COPY app ./app
COPY scripts ./scripts

# Diretórios de dados montados como volumes no compose
RUN mkdir -p /dados/uploads /dados/exports /dados/database

ENV PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
