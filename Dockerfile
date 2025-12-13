# Use a lightweight Python base image
FROM python:3.10-slim

# Set working directory inside the container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Environment variable to make output show up in logs immediately
ENV PYTHONUNBUFFERED=1

# By default, run the query script. 
#IF want to start from scrath and manually run the scripts one by one
#CMD ["tail", "-f", "/dev/null"]
# Usage: docker run -it rag-app
CMD ["python", "query_rag.py"]
