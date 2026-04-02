FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

COPY . /workspace

RUN python -m pip install --upgrade pip \
    && python -m pip install -e ".[dev,redis]"

CMD ["driftcut", "--help"]
