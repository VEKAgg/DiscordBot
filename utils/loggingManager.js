const { EmbedBuilder } = require('discord.js');
const LogEntry = require('../models/LogEntry');
const { logger } = require('./logger');

class LoggingManager {
    constructor(client) {
        this.client = client;
        this.logTypes = {
            BOT: { color: '#00ff00', emoji: '🤖' },
            MEMBER: { color: '#ff9900', emoji: '👤' },
            MOD: { color: '#ff0000', emoji: '🛡️' },
            SERVER: { color: '#0099ff', emoji: '🏠' }
        };
    }

    async log(guild, type, content, metadata = {}) {
        try {
            // Save to database
            await LogEntry.create({
                guildId: guild.id,
                type,
                content,
                metadata
            });

            // Send to log channel
            const logChannel = guild.channels.cache.find(ch => 
                ch.name.toLowerCase().match(/logs?|audit|monitor/)
            );

            if (!logChannel) return;

            const embed = new EmbedBuilder()
                .setTitle(`${this.logTypes[type].emoji} ${type} Log`)
                .setDescription(content)
                .setColor(this.logTypes[type].color)
                .setTimestamp();

            if (Object.keys(metadata).length > 0) {
                embed.addFields(
                    Object.entries(metadata).map(([key, value]) => ({
                        name: key,
                        value: String(value),
                        inline: true
                    }))
                );
            }

            await logChannel.send({ embeds: [embed] });
        } catch (error) {
            logger.error('Logging error:', error);
        }
    }

    async getLogs(guild, type, limit = 100) {
        return await LogEntry.find({ guildId: guild.id, type })
            .sort({ timestamp: -1 })
            .limit(limit);
    }
}

module.exports = LoggingManager; 