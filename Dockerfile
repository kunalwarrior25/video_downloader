FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure yt-dlp is up to date
RUN pip install -U yt-dlp

# Set default port
ENV PORT=10000

# Use gunicorn as the production server, binding to the dynamic $PORT
CMD gunicorn --bind 0.0.0.0:$PORT app:app
