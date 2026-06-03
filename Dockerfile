# --- MTO INDUSTRIAL BACKEND DOCKERFILE ---
# Build Stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies (for mysql and cryptography)
RUN apt-get update && apt-get install -y \
    build-essential \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Final Stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies (including mariadb-client for mysqldump)
RUN apt-get update && apt-get install -y \
    libmariadb-dev-compat \
    mariadb-client \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Environment Variables
ENV PYTHONUNBUFFERED=1
ENV APP_ENV=production
ENV PORT=8001

# Copy entrypoint and make executable
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ---------------------------------------------------------------------------
# WIN 5: Run as a non-root user.
# Running as root inside a container means any RCE vulnerability gives the
# attacker root on the host if the container runtime is misconfigured.
# A dedicated low-privilege user limits the blast radius.
# ---------------------------------------------------------------------------
RUN useradd --system --create-home --shell /bin/false mto \
    && chown -R mto:mto /app /entrypoint.sh

USER mto

# Expose API port
EXPOSE 8001

# Run migrations then start server
CMD ["/entrypoint.sh"]
