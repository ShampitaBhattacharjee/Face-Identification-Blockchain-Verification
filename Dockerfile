# Reproducible runtime including a compiled dlib (the slowest part of local setup).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake pkg-config \
        libopenblas-dev liblapack-dev \
        libjpeg-dev libpng-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN mkdir -p output deployments

# Usage:
#   docker build -t faceid .
#   docker run --rm --env-file .env -v $PWD/samples:/app/samples -v $PWD/output:/app/output \
#       -v $PWD/deployments:/app/deployments faceid --image samples/photo.jpg
ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
