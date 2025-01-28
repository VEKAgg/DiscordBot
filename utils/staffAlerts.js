const { EmbedBuilder } = require('discord.js');
const { logger } = require('./logger');

class StaffAlerts {
    static async send(guild, alertData) {
        try {
            const { type, content, priority, data } = alertData;
            const staffChannel = guild.channels.cache.find(ch => ch.name === 'staff-alerts');
            const logsChannel = guild.channels.cache.find(ch => ch.name === 'server-logs');

            if (!staffChannel || !logsChannel) return;

            const embed = this.createAlertEmbed(type, content, priority, data);
            
            // High priority alerts go to staff channel with ping
            if (priority === 'high') {
                await staffChannel.send({
                    content: `<@&${guild.roles.cache.find(r => r.name === 'Staff')?.id}>`,
                    embeds: [embed]
                });
            }

            // Log everything to logs channel
            await logsChannel.send({ embeds: [embed] });
            
            // Store in database for searchability
            await this.storeAlert(guild.id, alertData);

        } catch (error) {
            logger.error('Staff alert error:', error);
        }
    }

    static createAlertEmbed(type, content, priority, data) {
        const colors = {
            high: '#FF0000',    // Red
            medium: '#FFA500',  // Orange
            low: '#FFFF00'      // Yellow
        };

        const icons = {
            presence: '🎮',
            suspicious: '⚠️',
            dm_failed: '📝',
            role_error: '👑',
            new_activity: '🆕',
            verification: '✅',
            voice: '🎤'
        };

        return new EmbedBuilder()
            .setTitle(`${icons[type] || '❗'} ${this.formatTitle(type)}`)
            .setDescription(content)
            .setColor(colors[priority] || '#808080')
            .addFields(
                Object.entries(data || {}).map(([key, value]) => ({
                    name: this.formatFieldName(key),
                    value: String(value),
                    inline: true
                }))
            )
            .setTimestamp();
    }

    static formatTitle(type) {
        return type.split('_')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');
    }

    static formatFieldName(key) {
        return key.split('_')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');
    }

    static async storeAlert(guildId, alertData) {
        // Reference to database schema in events/presenceUpdate.js:
        // startLine: 11
        // endLine: 14

        await User.findOneAndUpdate(
            { 
                guildId,
                type: 'server_logs'
            },
            {
                $push: {
                    logs: {
                        ...alertData,
                        timestamp: new Date()
                    }
                }
            },
            { upsert: true }
        );
    }
}

module.exports = StaffAlerts; 