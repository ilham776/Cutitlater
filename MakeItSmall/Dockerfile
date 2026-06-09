# Start with Python 3.11
FROM python:3.11-slim

# Install Node.js and system dependencies
RUN apt-get update && apt-get install -y \
    nodejs \
    npm \
    ffmpeg \
    libatomic1 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Create clips folder
RUN mkdir -p clips

# Start the server
CMD uvicorn app:app --host 0.0.0.0 --port $PORT
