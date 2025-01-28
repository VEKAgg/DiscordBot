const BaseAnalytics = require('./baseAnalytics');
const { User } = require('../../database');
const StaffAlerts = require('../staffAlerts');

class InviteAnalyzer extends BaseAnalytics {
    static async analyzeInvites(guild, inviter, invitedUser) {
        try {
            const timeWindow = 24 * 60 * 60 * 1000; // 24 hours
            const stats = await this.getInviterStats(inviter.id, guild.id, timeWindow);
            
            const patterns = this.detectSuspiciousPatterns(stats);
            if (patterns.length > 0) {
                await this.reportSuspiciousActivity(guild, inviter, patterns);
            }
        } catch (error) {
            this.logError(error, 'analyzeInvites');
        }
    }

    static async getInviterStats(inviterId, guildId, timeWindow) {
        return this.aggregateData(
            User,
            { 
                userId: inviterId,
                guildId: guildId,
                'invites.history.timestamp': { $gte: new Date(Date.now() - timeWindow) }
            },
            {
                _id: null,
                totalInvites: { $sum: 1 },
                uniqueIPs: { $addToSet: '$invites.history.ip' },
                invitedUsers: { $push: '$invites.history.userId' }
            }
        ).then(results => results[0] || { totalInvites: 0, uniqueIPs: [], invitedUsers: [] });
    }

    static detectSuspiciousPatterns(stats) {
        const patterns = [];
        
        if (stats.totalInvites > 10) {
            patterns.push('High invite volume');
        }
        if (stats.uniqueIPs.length === 1 && stats.totalInvites > 5) {
            patterns.push('Multiple invites from same IP');
        }
        if (stats.invitedUsers.length < stats.totalInvites * 0.8) {
            patterns.push('Duplicate invites to same users');
        }

        return patterns;
    }

    static async reportSuspiciousActivity(guild, inviter, patterns) {
        await StaffAlerts.send(guild, {
            type: 'invite_abuse',
            priority: 'high',
            content: 'Suspicious invite activity detected',
            embed: this.createEmbed({
                title: '⚠️ Suspicious Invite Activity Detected',
                fields: [
                    { name: 'Inviter', value: `<@${inviter.id}> (${inviter.tag})`, inline: true },
                    { name: 'Suspicious Patterns', value: patterns.join('\n'), inline: false }
                ],
                color: '#ff0000'
            })
        });
    }
}

module.exports = InviteAnalyzer; 