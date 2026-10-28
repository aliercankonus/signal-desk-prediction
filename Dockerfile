FROM python:3.12-slim
# Host-release regression fixtures create Git commits inside the collector image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && git --version \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x scripts/*.sh || true
CMD ["python", "-m", "signal_desk.api.health_server"]
