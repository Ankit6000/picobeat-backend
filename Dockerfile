FROM python:3.10-slim

WORKDIR /app

# Install ffmpeg for yt-dlp first, and nodejs for signature solving
RUN apt-get update && apt-get install -y ffmpeg nodejs && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hugging Face runs as user 1000. Give permission to /app for downloads
RUN chown -R 1000:1000 /app

# Environment variables
ENV TELEGRAM_BOT_TOKEN=""
ENV TELEGRAM_CHANNEL_ID=""

# Hugging Face REQUIRES port 7860
ENV PORT=7860
EXPOSE 7860

CMD uvicorn main:app --host 0.0.0.0 --port $PORT
