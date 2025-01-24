const BaseAnalytics = require('./baseAnalytics');
const { EmbedBuilder } = require('discord.js');
const { User } = require('../../database');
const StaffAlerts = require('../staffAlerts');

class InviteAnalyzer extends BaseAnalytics {
    static async checkForAbuse(member, inviter) {
        try {
            const patterns = await this.detectSuspiciousPatterns(member, inviter);
            if (patterns.length > 0) {
                await this.reportSuspiciousActivity(member.guild, inviter, patterns);
                return true;
            }
            return false;
        } catch (error) {
            this.logError(error, 'checkForAbuse');
            return false;
        }
    }

    static async detectSuspiciousPatterns(member, inviter) {
        const suspiciousPatterns = [];
        const stats = await this.getInviterStats(inviter.id, member.guild.id);
        
        // Check for rapid invites
        if (stats.totalInvites > 10) {
            suspiciousPatterns.push('High invite volume in short period');
        }

        // Check for multiple accounts from same IP
        if (stats.uniqueIPs.length < stats.totalInvites * 0.5) {
            suspiciousPatterns.push('Multiple accounts from same IP addresses');
        }

        // Check for join-leave patterns
        const joinLeavePatterns = await User.aggregate([
            { $match: { guildId: member.guild.id } },
            { $match: { inviterId: inviter.id } },
            { $match: { leftAt: { $ne: null } } },
            {
                $group: {
                    _id: null,
                    quickLeaves: {
                        $sum: {
                            $cond: [
                                { $lt: [{ $subtract: ['$leftAt', '$joinedAt'] }, 24 * 60 * 60 * 1000] },
                                1,
                                0
                            ]
                        }
                    }
                }
            }
        ]);

        if (joinLeavePatterns.length && joinLeavePatterns[0].quickLeaves > 5) {
            suspiciousPatterns.push('High number of quick leave patterns');
        }

        return suspiciousPatterns;
    }

    static async reportSuspiciousActivity(guild, inviter, patterns) {
        const embed = new EmbedBuilder()
            .setTitle('⚠️ Suspicious Invite Activity Detected')
            .setColor('#ff0000')
            .addFields([
                { name: 'Inviter', value: `<@${inviter.id}> (${inviter.tag})`, inline: true },
                { name: 'Suspicious Patterns', value: patterns.join('\n'), inline: false }
            ])
            .setTimestamp();

        await StaffAlerts.send(guild, {
            type: 'invite_abuse',
            priority: 'high',
            content: 'Suspicious invite activity detected',
            embed: embed
        });
    }

    static async getInviterStats(inviterId, guildId, timeWindow = 24 * 60 * 60 * 1000) {
        try {
            const inviterData = await User.aggregate([
                { 
                    $match: { 
                        userId: inviterId,
                        guildId: guildId
                    }
                },
                { $unwind: '$invites.history' },
                {
                    $match: {
                        'invites.history.timestamp': {
                            $gte: new Date(Date.now() - timeWindow)
                        }
                    }
                },
                {
                    $group: {
                        _id: null,
                        totalInvites: { $sum: 1 },
                        uniqueIPs: { $addToSet: '$invites.history.ip' },
                        invitedUsers: { $push: '$invites.history.userId' }
                    }
                }
            ]);

            return inviterData[0] || { totalInvites: 0, uniqueIPs: [], invitedUsers: [] };
        } catch (error) {
            this.logError(error, 'getInviterStats');
            return { totalInvites: 0, uniqueIPs: [], invitedUsers: [] };
        }
    }
}

module.exports = InviteAnalyzer; 