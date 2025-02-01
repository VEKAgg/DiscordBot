import logging
import sys
from logging.handlers import RotatingFileHandler
import os
from datetime import datetime
import nextcord

class CustomFormatter(logging.Formatter):
    """Custom formatter with colors for console output"""
    
    COLORS = {
        'DEBUG': '\033[94m',    # Blue
        'INFO': '\033[92m',     # Green
        'WARNING': '\033[93m',  # Yellow
        'ERROR': '\033[91m',    # Red
        'CRITICAL': '\033[95m', # Magenta
        'RESET': '\033[0m'      # Reset
    }

    def format(self, record):
        # Add color to console output only
        if isinstance(record.args, dict):
            record.msg = f"{record.msg} {record.args}"
            record.args = ()
            
        if hasattr(sys.stdout, 'isatty') and sys.stdout.isatty():
            levelname = record.levelname
            if levelname in self.COLORS:
                record.levelname = f"{self.COLORS[levelname]}{levelname}{self.COLORS['RESET']}"
        return super().format(record)

def setup_logger():
    # Create logs directory if it doesn't exist
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # Set up loggers
    loggers = {
        'nextcord': logging.getLogger('nextcord'),
        'bot': logging.getLogger('bot'),
        'commands': logging.getLogger('nextcord.commands'),
        'http': logging.getLogger('nextcord.http')
    }

    # Set levels
    for logger in loggers.values():
        logger.setLevel(logging.INFO)

    # Create formatters
    console_formatter = CustomFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Create handlers
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(console_formatter)
    console.setLevel(logging.INFO)

    debug_file = RotatingFileHandler(
        filename='logs/debug.log',
        encoding='utf-8',
        maxBytes=32 * 1024 * 1024,  # 32 MiB
        backupCount=5,
        mode='a'
    )
    debug_file.setFormatter(file_formatter)
    debug_file.setLevel(logging.DEBUG)

    error_file = RotatingFileHandler(
        filename='logs/error.log',
        encoding='utf-8',
        maxBytes=32 * 1024 * 1024,
        backupCount=5,
        mode='a'
    )
    error_file.setFormatter(file_formatter)
    error_file.setLevel(logging.ERROR)

    # Add handlers to all loggers
    for logger in loggers.values():
        logger.addHandler(console)
        logger.addHandler(debug_file)
        logger.addHandler(error_file)

    return loggers['bot']  # Return the bot logger as default 