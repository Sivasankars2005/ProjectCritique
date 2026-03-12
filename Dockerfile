# --- Stage 1: Build ---
FROM python:3.11-slim as builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install dependencies into a local folder
RUN pip install --no-cache-dir --user -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

# --- Stage 2: Final ---
FROM python:3.11-slim

WORKDIR /app

# Copy only the installed dependencies from the builder
COPY --from=builder /root/.local /root/.local
# Ensure the scripts in /root/.local/bin are in the PATH
ENV PATH=/root/.local/bin:$PATH

# Copy project files
COPY . .

# Expose port
EXPOSE 5000

# Install gunicorn (small enough to do here directly or could be in builder)
RUN pip install --no-cache-dir gunicorn --user

# Command to run the application
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
