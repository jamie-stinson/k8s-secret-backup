# --- Build Stage ---
FROM python:3.11-slim AS builder

WORKDIR /app

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Copy source code
COPY k8s_secrets_backup.py .

# --- Final Stage ---
FROM gcr.io/distroless/python3:nonroot

# Set up Python path so it can find installed packages
ENV PYTHONPATH=/usr/local/lib/python3.11/site-packages

# Copy installed dependencies and app
COPY --from=builder /install /usr/local
COPY --from=builder /app/k8s_secrets_backup.py /app/k8s_secrets_backup.py

WORKDIR /app
USER nonroot:nonroot

ENTRYPOINT ["python3", "/app/k8s_secrets_backup.py"]
