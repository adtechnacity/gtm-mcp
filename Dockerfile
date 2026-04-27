FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source. We invoke the server via `python fastmcp_gtm_server.py`
# directly (entrypoint.sh), so no need to `pip install .` — keeps the
# image smaller and avoids hatchling's pyproject.toml validation.
COPY . .
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
