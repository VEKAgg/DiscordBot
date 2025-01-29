const path = require('path');
const fs = require('fs').promises;
const { logger } = require('./logger');

class EventLoader {
    constructor(client) {
        this.client = client;
    }

    async loadEvents(eventsPath) {
        const eventFiles = await fs.readdir(eventsPath);
        const stats = {
            total: 0,
            names: []
        };

        for (const file of eventFiles) {
            try {
                const filePath = path.resolve(eventsPath, file);
                const event = require(filePath);
                
                if (event.once) {
                    this.client.once(event.name, (...args) => event.execute(...args));
                } else {
                    this.client.on(event.name, (...args) => event.execute(...args));
                }
                
                stats.total++;
                stats.names.push(event.name);
            } catch (error) {
                logger.error(`Failed to load event ${file}:`, error);
            }
        }
        
        return stats;
    }
}

module.exports = EventLoader; 