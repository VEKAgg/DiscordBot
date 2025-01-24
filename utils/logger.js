const winston = require('winston');
const path = require('path');

// Define log format
const logFormat = winston.format.combine(
    winston.format.timestamp(),
    winston.format.errors({ stack: true }),
    winston.format.printf(({ timestamp, level, message, stack }) => {
        if (message.startsWith('Loading command:')) return null;
        return `[${timestamp}] ${level}: ${message}${stack ? '\n' + stack : ''}`;
    })
);

// Create logger instance
const logger = winston.createLogger({
    format: logFormat,
    transports: [
        // Console logging
        new winston.transports.Console({
            format: winston.format.colorize({ all: true }),
        }),
        // Error logging
        new winston.transports.File({
            filename: path.join(__dirname, '../logs/error.log'),
            level: 'error',
        }),
        // Combined logging
        new winston.transports.File({
            filename: path.join(__dirname, '../logs/combined.log'),
        }),
    ],
});

// Create logs directory if it doesn't exist
const fs = require('fs');
const logsDir = path.join(__dirname, '../logs');
if (!fs.existsSync(logsDir)) {
    fs.mkdirSync(logsDir);
}

module.exports = { logger }; 