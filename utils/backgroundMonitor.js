const fs = require('fs');
const path = require('path');
const { logger } = require('./logger');
const mongoose = require('mongoose');

/**
 * Runs periodic health checks on the bot.
 * @param {Object} client - The Discord client instance.
 */
async function runBackgroundChecks(client) {
    const checkInterval = 300000; // 5 minutes
    const errorLogPath = path.join(__dirname, '../logs/errorLog.txt');

    // Create the logs directory if it doesn't exist
    if (!fs.existsSync(path.dirname(errorLogPath))) {
        fs.mkdirSync(path.dirname(errorLogPath));
    }

    setInterval(async () => {
        // Only run checks if no commands were executed in the last minute
        const lastCommandTime = client.lastCommandTime || 0;
        if (Date.now() - lastCommandTime < 60000) {
            return;
        }

        logger.info('[Background Monitor] Running health checks...');
        const errors = [];

        try {
            // Check client connection status
            if (!client.ws.ping) {
                errors.push('WebSocket connection issue detected');
            }

            // Check database connection
            try {
                await mongoose.connection.db.admin().ping();
            } catch (err) {
                errors.push(`Database connection error: ${err.message}`);
            }

            // Check memory usage
            const memoryUsage = process.memoryUsage();
            if (memoryUsage.heapUsed > 500 * 1024 * 1024) { // 500MB
                errors.push('High memory usage detected');
            }

        } catch (error) {
            logger.error('Background check failed:', error);
            errors.push(`Background check error: ${error.message}`);
        }
        
        // Log errors if any
        if (errors.length) {
            const timestamp = new Date().toISOString();
            const logData = `[${timestamp}] Errors: \n${errors.join('\n')}\n\n`;
            fs.appendFileSync(errorLogPath, logData);
            logger.error('[Background Monitor] Errors detected:', errors);
        } else {
            logger.info('[Background Monitor] All checks passed.');
        }
    }, checkInterval);
}

/**
 * Example API check (Replace with your API health check).
 */
async function checkExampleApi() {
    // Replace with actual API health check logic
    return Promise.resolve(true); // Simulate working API
}

module.exports = { runBackgroundChecks };
