FROM python:3.12-slim
WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Headless workflows: install git + the Claude Code CLI so the backend
# can run `claude -p "/review"` style agent jobs (see app/headless.py).
# The mounted target repo belongs to the host user, so mark all
# directories git-safe inside the container.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://claude.ai/install.sh | bash \
    && git config --global --add safe.directory '*'
ENV PATH="/root/.local/bin:${PATH}"
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
