FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create directories for simulated S3
RUN mkdir -p /tmp/s3_local

COPY src/ /app/src/

# Set env vars for local AWS
ENV AWS_ACCESS_KEY_ID=test
ENV AWS_SECRET_ACCESS_KEY=test
ENV AWS_DEFAULT_REGION=us-east-1
ENV LOCALSTACK_ENDPOINT=http://localstack:4566
