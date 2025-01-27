const { ActivityType } = require('discord.js');
const { statuses, interval } = require('../config/botStatus');
const { logger } = require('./logger');
const { User } = require('../database');

class StatusManager {
    constructor(client) {
        this.client = client;
        this.currentIndex = 0;
        this.voiceChannelName = 'call'; // Default name
    }

    start() {
        this.updateStatus();
        setInterval(() => this.updateStatus(), interval);
    }

    async updateStatus() {
        try {
            const status = statuses[this.currentIndex];
            let text = await this.formatStatusText(status.text);
            
            // If the status type is Competing and text includes 'call'
            if (status.type === ActivityType.Competing && text.includes('call')) {
                text = this.voiceChannelName;
            }

            await this.client.user.setActivity(text, { type: status.type });
            this.currentIndex = (this.currentIndex + 1) % statuses.length;
        } catch (error) {
            logger.error('Status update error:', error);
        }
    }

    async formatStatusText(text) {
        const stats = {
            memberCount: this.client.users.cache.size,
            serverCount: this.client.guilds.cache.size,
            activeVoice: this.client.voice.adapters.size,
            messageCount: await this.getTodayMessageCount()
        };

        return text.replace(/{(\w+)}/g, (match, key) => stats[key] || match);
    }

    async getTodayMessageCount() {
        try {
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            
            const stats = await User.aggregate([
                {
                    $match: {
                        'messages.lastMessageDate': { $gte: today }
                    }
                },
                {
                    $group: {
                        _id: null,
                        totalDaily: { $sum: '$messages.daily' }
                    }
                }
            ]);

            return stats[0]?.totalDaily || 0;
        } catch (error) {
            logger.error('Error getting daily message count:', error);
            return 0;
        }
    }

    setVoiceChannelName(name) {
        this.voiceChannelName = name;
    }
}

module.exports = StatusManager; 