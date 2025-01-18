const { EmbedBuilder } = require('discord.js');
const { User } = require('../database');
const { ChartJSNodeCanvas } = require('chartjs-node-canvas');

class InviteAnalytics {
    static async generateReport(guild, timeRange = '30d') {
        const data = await this.collectAnalytics(guild, timeRange);
        return this.createAnalyticsEmbed(data, timeRange);
    }

    static async collectAnalytics(guild, timeRange) {
        const timeFrames = {
            '7d': 7 * 24 * 60 * 60 * 1000,
            '30d': 30 * 24 * 60 * 60 * 1000,
            '90d': 90 * 24 * 60 * 60 * 1000
        };

        const timeFrame = timeFrames[timeRange] || timeFrames['30d'];
        const startDate = new Date(Date.now() - timeFrame);

        const inviteData = await User.aggregate([
            { $match: { guildId: guild.id } },
            { $unwind: '$invites.history' },
            { $match: { 'invites.history.timestamp': { $gte: startDate } } },
            {
                $group: {
                    _id: {
                        $dateToString: { 
                            format: '%Y-%m-%d', 
                            date: '$invites.history.timestamp' 
                        }
                    },
                    count: { $sum: 1 }
                }
            },
            { $sort: { '_id': 1 } }
        ]);

        return {
            totalInvites: inviteData.reduce((sum, day) => sum + day.count, 0),
            dailyInvites: inviteData,
            topInviters: await this.getTopInviters(guild.id, startDate),
            conversionRate: await this.calculateConversionRate(guild.id, startDate)
        };
    }

    static async createAnalyticsEmbed(data, timeRange) {
        const embed = new EmbedBuilder()
            .setTitle('📊 Invite Analytics Report')
            .addFields([
                { name: 'Total Invites', value: data.totalInvites.toString(), inline: true },
                { name: 'Time Range', value: timeRange, inline: true },
                { name: 'Conversion Rate', value: `${data.conversionRate}%`, inline: true },
                { name: 'Top Inviters', value: this.formatTopInviters(data.topInviters) }
            ])
            .setImage('attachment://invite-graph.png')
            .setColor('#00ff00')
            .setTimestamp();

        return embed;
    }

    // Additional helper methods...
}

module.exports = InviteAnalytics; 