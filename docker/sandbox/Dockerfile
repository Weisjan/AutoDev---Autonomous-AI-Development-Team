FROM python:3.11-slim

RUN python -m pip install --no-cache-dir "pytest>=8,<9"

ENV PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
WORKDIR /workspace
