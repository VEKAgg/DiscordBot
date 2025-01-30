import logging
import sys
from logging.handlers import RotatingFileHandler

def setup_logger(name='veka'):
    """Set up the logger with file output.
    
    Returns:
        logging.Logger: Configured logger instance
    """
    # Check if logger already exists
    if name in logging.Logger.manager.loggerDict:
        return logging.getLogger(name)
        
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', 
                                datefmt='%Y-%m-%d %H:%M:%S')
    
    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    # File Handler
    file_handler = RotatingFileHandler(
        'logs/bot.log', 
        maxBytes=10000000, 
        backupCount=5
    )
    file_handler.setFormatter(formatter)
    
    # Add handlers only if they don't exist
    if not logger.handlers:
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
    
    return logger 