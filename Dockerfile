FROM python:3.11-slim

# Install ffmpeg, nodejs (for yt-dlp signature decryption), and clear apt cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependencies list and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app.py .
COPY templates/ templates/
COPY cookies.txt* .

# Set environment UTF-8 variables
ENV PYTHONUNBUFFERED=1
ENV LANG=C.UTF-8

CMD ["python", "app.py"]
