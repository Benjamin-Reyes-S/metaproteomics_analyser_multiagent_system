# Runs the LangGraph multi-agent pipeline (`python main.py`).
#
# Build context is the repo root (see docker-compose.yml) so this can pull
# in requirements.txt, agents/, graph/, schemas/, sandbox/run_code.py and
# main.py -- the pieces that actually make up the pipeline. graph/graph.py
# imports sandbox.run_code directly, so that one module has to ship here
# too even though the rest of sandbox/ (its own Dockerfile and
# requirements.txt) belongs only to the analysis-sandbox image. Dependencies
# come from the root requirements.txt (langgraph/langchain/pydantic/...),
# never from sandbox/requirements.txt.
#
# Includes the Docker CLI (no daemon) so run_code.py can launch the
# sibling analysis-sandbox container through the host's Docker socket,
# which docker-compose.yml bind-mounts into this container
# (Docker-outside-of-Docker) -- this container has no daemon of its own.
FROM python:3.11-slim

COPY --from=docker:cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agents/ agents/
COPY graph/ graph/
COPY schemas/ schemas/
COPY sandbox/run_code.py sandbox/run_code.py
COPY main.py .

ENTRYPOINT ["python", "main.py"]
