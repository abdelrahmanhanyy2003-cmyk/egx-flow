FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt
# Official EFG Hermes Younit SDK (PyPI package "coming soon"; installed from source).
ARG YOUNIT_REF=master
RUN pip install "git+https://github.com/efg-hermes-younit/younit-python@${YOUNIT_REF}"

COPY . .
RUN useradd -m egx && chown -R egx /app
USER egx
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
