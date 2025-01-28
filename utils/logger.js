const winston = require('winston');
const { format } = winston;
const path = require('path');

// Define log format
const logFormat = format.combine(
    format.timestamp({
        format: 'YYYY-MM-DD HH:mm:ss'
    }),
    format.errors({ stack: true }),
    format.splat(),
    format.json()
);

// Create logger instance
const logger = winston.createLogger({
    level: 'info',
    format: logFormat,
    defaultMeta: { service: 'veka-bot' },
    transports: [
        // Console logging
        new winston.transports.Console({
            format: format.combine(
                format.colorize(),
                format.simple()
            )
        }),
        // Error logging
        new winston.transports.File({ filename: 'logs/error.log', level: 'error' }),
        // Combined logging
        new winston.transports.File({ filename: 'logs/combined.log' }),
    ],
});

// Create logs directory if it doesn't exist
const fs = require('fs');
const logsDir = path.join(__dirname, '../logs');
if (!fs.existsSync(logsDir)) {
    fs.mkdirSync(logsDir);
}

module.exports = { logger }; 