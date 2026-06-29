FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y ffmpeg git gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

RUN mkdir -p logs

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
