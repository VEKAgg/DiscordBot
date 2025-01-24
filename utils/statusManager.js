const { ActivityType } = require('discord.js');
const { statuses, interval } = require('../config/botStatus');
const { logger } = require('./logger');

class StatusManager {
    constructor(client) {
        this.client = client;
        this.currentIndex = 0;
    }

    start() {
        this.updateStatus();
        setInterval(() => this.updateStatus(), interval);
    }

    async updateStatus() {
        try {
            const status = statuses[this.currentIndex];
            const text = await this.formatStatusText(status.text);
            
            await this.client.user.setActivity({
                name: text,
                type: status.type
            });

            this.currentIndex = (this.currentIndex + 1) % statuses.length;
        } catch (error) {
            logger.error('Status update error:', error);
        }
    }

    async formatStatusText(text) {
        const stats = {
            memberCount: this.client.guilds.cache.reduce((acc, guild) => acc + guild.memberCount, 0),
            serverCount: this.client.guilds.cache.size,
            activeVoice: this.client.channels.cache.filter(c => c.type === 2 && c.members.size > 0).size,
            messageCount: await this.getTodayMessageCount()
        };

        return text.replace(/{(\w+)}/g, (match, key) => stats[key] || match);
    }

    async getTodayMessageCount() {
        try {
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            
            const messageStats = await this.client.analytics.getStats('messages', '1d');
            return messageStats.total || 0;
        } catch {
            return 0;
        }
    }
}

module.exports = StatusManager; 