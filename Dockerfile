FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

VOLUME ["/app/downloads", "/app/data"]
ENV DB_PATH=/app/data/bot_data.db DOWNLOAD_DIR=/app/downloads YT_TOKEN_DIR=/app/data/yt_tokens
CMD ["python", "bot.py"]
