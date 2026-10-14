FROM python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce

WORKDIR /opt/autodev
COPY docker/sandbox/requirements.lock ./requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.lock

# Build only the trusted source checkout; never install code/dependencies at runtime.
COPY pyproject.toml README.md ./
COPY src ./src
COPY docker/sandbox/check_environment.py ./check_environment.py
RUN python -m pip install --no-cache-dir --no-deps --no-build-isolation ".[dev]" \
    && python -m pip check \
    && python -I /opt/autodev/check_environment.py /opt/autodev/pyproject.toml

ENV PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
WORKDIR /workspace
