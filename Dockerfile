FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

RUN mkdir -p logs

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
