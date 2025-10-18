FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/data/cache/rss
RUN mkdir -p /app/logs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DISCORD_TOKEN=""
ENV MONGO_URI="mongodb://mongo:27017/vekabot"
ENV REDIS_URI="redis://redis:6379/0"
ENV JWT_SECRET=""

# Run the bot
CMD ["python", "main.py"]