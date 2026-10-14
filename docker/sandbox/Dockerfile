FROM python:3.11-slim

RUN python -m pip install --no-cache-dir "pytest>=8,<9" "ruff>=0.6,<1" "pydantic>=2.7,<3" "python-dotenv>=1,<2"

ENV PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
WORKDIR /workspace
