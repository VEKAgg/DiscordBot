const fs = require('fs');
const path = require('path');
const { logger } = require('./logger');

/**
 * Runs periodic health checks on the bot.
 * @param {Object} client - The Discord client instance.
 */
async function runBackgroundChecks(client) {
    const checkInterval = 60000; // 1 minute
    const errorLogPath = path.join(__dirname, '../logs/errorLog.txt');

    // Create the logs directory if it doesn't exist
    if (!fs.existsSync(path.dirname(errorLogPath))) {
        fs.mkdirSync(path.dirname(errorLogPath));
    }

    setInterval(async () => {
        logger.info('[Background Monitor] Running health checks...');
        const errors = [];

        try {
            // Test ping command
            const pingCommand = client.commands.get('ping');
            if (pingCommand) {
                const mockMessage = {
                    channel: { send: () => Promise.resolve() },
                    createdTimestamp: Date.now(),
                    client
                };
                
                try {
                    await pingCommand.execute(mockMessage);
                } catch (err) {
                    errors.push(`Ping command failed: ${err.message}`);
                    logger.error('Ping command test failed:', err);
                }
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
