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
   ```

4. **Run the Bot**
   ```bash
   python main.py
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