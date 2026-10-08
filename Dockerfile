# Pulled from the AWS-hosted public ECR mirror of Docker Hub library images
# to avoid Docker Hub's anonymous rate limit on shared CodeBuild egress IPs.
# The image is byte-identical to docker.io/library/python:3.12-slim.
FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

# Install exactly what uv.lock pins, so the image matches local/CI.
# --no-install-project: we run fastmcp_gtm_server.py directly (entrypoint.sh).
RUN pip install --no-cache-dir uv==0.11.7
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

COPY . .
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
