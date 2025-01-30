# Contributing to VEKA Bot

We love your input! We want to make contributing to VEKA Bot as easy and transparent as possible.

## Development Process
1. Fork the repo and create your branch from `main`
2. Make your changes
3. Test your changes thoroughly
4. Ensure your code follows our style guidelines
5. Submit a Pull Request

## Code Style Guidelines
- Follow PEP 8 style guidelines
- Use type hints for all functions
- Document functions using Google-style docstrings
- Use async/await for Discord operations
- Add appropriate error handling
- Keep functions focused and modular

## Project Structure
- `src/`: Contains the main bot code
  - `bot.py`: Main bot file
  - `cogs/`: Command categories
  - `utils/`: Utility functions
  - `database/`: Database models
- `config/`: Configuration files
- `tests/`: Test files
- `docs/`: Documentation

## Setting Up Development Environment
1. Install Python 3.10 or higher
2. Clone your fork
3. Create virtual environment:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
4. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
5. Copy and configure environment variables:
   ```
   cp .env.example .env
   # Edit .env with your credentials
   ```

## Pull Request Process
1. Update documentation for any new features
2. Add tests for new functionality
3. Ensure all tests pass: `pytest tests/`
4. Update requirements.txt if needed
5. The PR will be merged once reviewed

## Bug Reports
Please use the GitHub Issues tab and include:
- A quick summary
- Steps to reproduce
- What you expected would happen
- What actually happens
- Python version and OS information

## Feature Requests
We love feature requests! Please include:
- The use case
- Why this would be beneficial
- Any implementation ideas you have

## Questions?
Feel free to join our [Support Server](https://discord.gg/vekabot) for help.