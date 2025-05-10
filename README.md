# VEKA Discord Bot

A professional networking and community development Discord bot designed to create a vibrant community by providing tools for career development, networking, and entertainment.

## Features

### Currently Implemented
- 🤝 **Professional Networking**
  - Profile Management
  - Connection System
  - Professional Networking Features

### Coming Soon
- 📚 **Career Development**
  - Skill Development
  - Mentoring System
  - Career Guidance

- 🎯 **Events & Activities**
  - Professional Events
  - Workshops
  - Networking Sessions

- 🎮 **Community Fun**
  - Interactive Games
  - Community Building Activities

## Setup Instructions

### Standard Setup

1. **Clone the Repository**
   ```bash
   git clone <repository-url>
   cd DiscordBot
   ```

2. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Environment Setup**
   Create a `.env` file in the root directory with the following variables:
   ```
   DISCORD_TOKEN=your_discord_bot_token
   MONGODB_URI=your_mongodb_connection_string
   REDIS_URL=redis://127.0.0.1:6379
   ```

4. **Run the Bot**
   ```bash
   python main.py
   ```

### Docker Setup

1. **Clone the Repository**
   ```bash
   git clone <repository-url>
   cd DiscordBot
   ```

2. **Environment Setup**
   Create a `.env` file in the root directory with the following variables:
   ```
   DISCORD_TOKEN=your_discord_bot_token
   MONGODB_URI=your_mongodb_atlas_connection_string
   REDIS_URL=redis://redis:6379
   ```

3. **Build and Run with Docker Compose**
   ```bash
   docker-compose up -d
   ```

4. **Check Logs**
   ```bash
   docker logs veka-discord-bot
   ```

### Podman Setup

1. **Clone the Repository**
   ```bash
   git clone <repository-url>
   cd DiscordBot
   ```

2. **Environment Setup**
   Create a `.env` file in the root directory with the following variables:
   ```
   DISCORD_TOKEN=your_discord_bot_token
   MONGODB_URI=your_mongodb_atlas_connection_string
   REDIS_URL=redis://localhost:6379
   ```

3. **Create Pod and Run Containers**
   ```bash
   # Create pod
   podman pod create --name veka-bot-pod
   
   # Build bot image
   podman build -t veka-discord-bot:latest .
   
   # Run Redis
   podman run -d --pod veka-bot-pod \
     --name veka-redis \
     -v redis-data:/data \
     redis:alpine
   
   # Run Discord Bot
   podman run -d --pod veka-bot-pod \
     --name veka-discord-bot \
     -v ./logs:/app/logs \
     -v ./.env:/app/.env:ro \
     -e PYTHONUNBUFFERED=1 \
     veka-discord-bot:latest
   ```

4. **Check Logs**
   ```bash
   podman logs veka-discord-bot
   ```

## Available Commands

### Professional Networking
- `!profile [@user]` - View your or someone else's professional profile
- `!setupprofile` - Set up your professional profile
- `!connect @user [message]` - Send a connection request to another member

### Help
- `!help` - Show all available commands
- `!help <command>` - Show detailed information about a specific command

## Contributing

Feel free to contribute to this project by:
1. Forking the repository
2. Creating a new branch for your feature
3. Submitting a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 