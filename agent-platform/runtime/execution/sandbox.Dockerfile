# Execution sandbox base image (design spec decision 3, operator decision A4).
#
# Digest-pinned, never `:latest` — a mutable tag means the boundary being tested
# today is not necessarily the boundary running tomorrow. Update the digest with:
#   docker pull python:3.12-slim
#   docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim
# and update BASE_IMAGE in subprocess_sandbox.py in the same commit.
FROM python@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65

RUN pip install --no-cache-dir "pytest==8.3.4"

WORKDIR /workspace
