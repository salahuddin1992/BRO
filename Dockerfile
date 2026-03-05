FROM python:3-slim

WORKDIR /app

# Install system dependencies for python-magic, Pillow, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    libffi-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create runtime directories
RUN mkdir -p /app/runtime/uploads /app/runtime/backups /app/runtime/recordings

EXPOSE 8400 8401 8402 3478 5349 2222 2121 2223

ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8400/api/health')" || exit 1

CMD ["python", "run.py", "--verbose"]
