const BaseAnalytics = require('./baseAnalytics');
const { User } = require('../../database');

class InviteAnalytics extends BaseAnalytics {
    static async generateReport(guild, timeRange = '30d') {
        try {
            const data = await this.collectAnalytics(guild, timeRange);
            return this.createEmbed({
                title: `📊 Invite Analytics (${timeRange})`,
                fields: [
                    { name: 'Total Invites', value: data.totalInvites.toString(), inline: true },
                    { name: 'Conversion Rate', value: `${(data.conversionRate * 100).toFixed(1)}%`, inline: true },
                    { name: 'Daily Average', value: (data.totalInvites / data.dailyInvites.length).toFixed(1), inline: true },
                    ...(data.topInviters.length > 0 ? [{
                        name: 'Top Inviters',
                        value: data.topInviters
                            .map((inviter, index) => `${index + 1}. <@${inviter._id}> (${inviter.count})`)
                            .join('\n')
                    }] : [])
                ]
            });
        } catch (error) {
            this.logError(error, 'generateReport');
            return null;
        }
    }

    static async collectAnalytics(guild, timeRange) {
        const startDate = this.getTimeframeDate(timeRange);
        const [conversionRate, topInviters] = await Promise.all([
            this.calculateConversionRate(guild.id, startDate),
            this.getTopInviters(guild.id, startDate)
        ]);

        return {
            totalInvites: topInviters.reduce((sum, inv) => sum + inv.count, 0),
            conversionRate,
            dailyInvites: await this.getDailyInvites(guild.id, startDate),
            topInviters
        };
    }

    static async calculateConversionRate(guildId, startDate) {
        const stats = await this.aggregateData(
            User,
            { 
                guildId,
                joinedAt: { $gte: startDate }
            },
            {
                _id: null,
                total: { $sum: 1 },
                converted: {
                    $sum: {
                        $cond: [{ $gt: ['$membershipDuration', 7 * 24 * 60 * 60 * 1000] }, 1, 0]
                    }
                }
            }
        );

        if (!stats.length) return 0;
        return stats[0].converted / stats[0].total;
    }

    static async getTopInviters(guildId, startDate) {
        return this.aggregateData(
            User,
            {
                guildId,
                'invites.history.timestamp': { $gte: startDate }
            },
            {
                _id: '$invites.history.inviterId',
                count: { $sum: 1 }
            },
            { count: -1 },
            5
        );
    }

    static async getDailyInvites(guildId, startDate) {
        return this.aggregateData(
            User,
            {
                guildId,
                'invites.history.timestamp': { $gte: startDate }
            },
            {
                _id: { $dateToString: { format: '%Y-%m-%d', date: '$invites.history.timestamp' } },
                count: { $sum: 1 }
            }
        );
    }
}

module.exports = InviteAnalytics; 