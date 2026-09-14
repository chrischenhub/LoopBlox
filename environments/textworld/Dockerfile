FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && pip install --no-cache-dir textworld==1.7.0 \
    && apt-get purge -y --auto-remove build-essential && rm -rf /var/lib/apt/lists/*
COPY game.py /opt/loopblox/game.py
ENV PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python", "-u", "/opt/loopblox/game.py"]
