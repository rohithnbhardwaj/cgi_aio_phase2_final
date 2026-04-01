FROM python:3.11-slim

WORKDIR /app

# Install system packages needed for SSL, psycopg2 build, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    openssl \
    build-essential \
    libpq-dev \
    curl \
    libgomp1 \
 && rm -rf /var/lib/apt/lists/*

 # Optional: corporate CA (copy if present)
COPY zscaler-root.crt /usr/local/share/ca-certificates/zscaler-root.crt
RUN update-ca-certificates || true

ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt

# Install python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app sources
COPY . /app

#UI files
COPY ui/ ./ui/

# Ensure uploads dir exists
RUN mkdir -p /app/uploads /app/vector_store && chmod 777 /app/uploads /app/vector_store

EXPOSE 8501

ENTRYPOINT ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
