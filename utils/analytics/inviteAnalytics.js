const BaseAnalytics = require('./baseAnalytics');
const { User } = require('../../database');
const { EmbedBuilder } = require('discord.js');

class InviteAnalytics extends BaseAnalytics {
    static async generateReport(guild, timeRange = '30d') {
        try {
            const data = await this.collectAnalytics(guild, timeRange);
            return this.createAnalyticsEmbed(data, timeRange);
        } catch (error) {
            this.logError(error, 'generateReport');
        }
    }

    static async collectAnalytics(guild, timeRange) {
        // Reference from utils/inviteAnalytics.js
        startLine: 11
        endLine: 45
    }

    static async createAnalyticsEmbed(data, timeRange) {
        const embed = new EmbedBuilder()
            .setTitle(`📊 Invite Analytics (${timeRange})`)
            .setColor('#00ff00')
            .addFields([
                { name: 'Total Invites', value: data.totalInvites.toString(), inline: true },
                { name: 'Conversion Rate', value: `${(data.conversionRate * 100).toFixed(1)}%`, inline: true },
                { name: 'Daily Average', value: (data.totalInvites / data.dailyInvites.length).toFixed(1), inline: true }
            ]);

        if (data.topInviters.length > 0) {
            const topInvitersField = data.topInviters
                .map((inviter, index) => `${index + 1}. <@${inviter._id}> (${inviter.count})`)
                .join('\n');
            embed.addFields({ name: 'Top Inviters', value: topInvitersField });
        }

        return embed;
    }

    static async calculateConversionRate(guildId, startDate) {
        const stats = await User.aggregate([
            { $match: { guildId } },
            { $match: { joinedAt: { $gte: startDate } } },
            {
                $group: {
                    _id: null,
                    total: { $sum: 1 },
                    converted: {
                        $sum: {
                            $cond: [{ $gt: ['$membershipDuration', 7 * 24 * 60 * 60 * 1000] }, 1, 0]
                        }
                    }
                }
            }
        ]);

        if (!stats.length) return 0;
        return stats[0].converted / stats[0].total;
    }

    static async getTopInviters(guildId, startDate) {
        // Add the getTopInviters implementation
        const topInviters = await User.aggregate([
            { $match: { guildId } },
            { $unwind: '$invites.history' },
            { $match: { 'invites.history.timestamp': { $gte: startDate } } },
            {
                $group: {
                    _id: '$invites.history.inviterId',
                    count: { $sum: 1 }
                }
            },
            { $sort: { count: -1 } },
            { $limit: 5 }
        ]);

        return topInviters;
    }
}

module.exports = InviteAnalytics; 