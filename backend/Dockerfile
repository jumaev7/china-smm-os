FROM python:3.12-slim

# F3 image identity: pass the full Git SHA at build time.
# Example: docker build --build-arg SOURCE_SHA=$(git rev-parse HEAD) ...
# Do not trust this label alone — deploy helper also verifies image ID + file hashes.
ARG SOURCE_SHA=unknown
LABEL org.opencontainers.image.revision="${SOURCE_SHA}"
ENV SOURCE_SHA="${SOURCE_SHA}"

WORKDIR /app

# System deps: libmagic1 for file type detection, ffmpeg for video audio extraction
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p media_storage/thumbnails

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
