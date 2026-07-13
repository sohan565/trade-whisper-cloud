FROM python:3.11-slim

# Install ffmpeg and clear apt cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependencies list and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app.py .
COPY templates/ templates/
COPY cookies.txt* .

EXPOSE 8000

# Set environment UTF-8 variables
ENV PYTHONUNBUFFERED=1
ENV LANG=C.UTF-8

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
