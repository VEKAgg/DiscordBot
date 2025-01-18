const fs = require('fs');
const path = require('path');

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
        console.log('[Background Monitor] Running health checks...');
        const errors = [];

        try {
            // Example Check 1: Test command execution (ping)
            const pingCommand = client.commands.get('ping');
            if (pingCommand) {
                try {
                    await pingCommand.execute({
                        channel: {
                            send: () => Promise.resolve(), // Mock send to avoid spamming
                        },
                        author: { username: 'BackgroundChecker' },
                        createdTimestamp: Date.now(),
                        client,
                    });
                } catch (err) {
                    errors.push(`Ping command failed: ${err.message}`);
                }
            }

            // Example Check 2: Verify APIs (replace with real checks)
            const isApiWorking = await checkExampleApi();
            if (!isApiWorking) {
                errors.push('Example API is unresponsive.');
            }

        } catch (err) {
            errors.push(`Unexpected error: ${err.message}`);
        }

        // Log errors if any
        if (errors.length) {
            const timestamp = new Date().toISOString();
            const logData = `[${timestamp}] Errors: \n${errors.join('\n')}\n\n`;

            // Log to file
            fs.appendFileSync(errorLogPath, logData);

            console.error('[Background Monitor] Errors detected:', errors);
        } else {
            console.log('[Background Monitor] All checks passed.');
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
