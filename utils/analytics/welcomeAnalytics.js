const BaseAnalytics = require('./baseAnalytics');
const { EmbedBuilder } = require('discord.js');
const { User, WelcomeStats } = require('../../database');

class WelcomeAnalytics extends BaseAnalytics {
    static async trackWelcome(member, { dmSuccess, assignedRoles, isVerified }) {
        try {
            const stats = await WelcomeStats.findOneAndUpdate(
                { guildId: member.guild.id },
                {
                    $inc: {
                        totalJoins: 1,
                        [`hourlyJoins.${new Date().getHours()}`]: 1,
                        [`dailyJoins.${new Date().getDay()}`]: 1,
                        successfulDMs: dmSuccess ? 1 : 0,
                        verifiedJoins: isVerified ? 1 : 0
                    },
                    $push: {
                        members: {
                            userId: member.id,
                            joinedAt: new Date(),
                            assignedRoles,
                            dmSuccess,
                            isVerified
                        }
                    }
                },
                { upsert: true, new: true }
            );

            if (stats.totalJoins % 10 === 0) {
                await this.generateInsights(member.guild);
            }
        } catch (error) {
            this.logError(error, 'trackWelcome');
        }
    }

    static getDayName(day) {
        const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
        return days[day];
    }

    static async generateInsights(guild) {
        try {
            const stats = await this.getGuildStats(guild.id);
            const retentionRate = await this.calculateRetentionRate(stats);
            const bestTimes = await this.analyzeBestTimes(stats);

            return this.createEmbed({
                title: '📊 Welcome System Insights',
                fields: [
                    { name: 'Total Joins', value: stats.totalJoins.toString(), inline: true },
                    { name: 'DM Success Rate', value: `${((stats.successfulDMs / (stats.totalJoins || 1)) * 100).toFixed(1)}%`, inline: true },
                    { name: 'Verification Rate', value: `${((stats.verifiedJoins / (stats.totalJoins || 1)) * 100).toFixed(1)}%`, inline: true },
                    { name: 'Member Retention', value: `${retentionRate.toFixed(1)}%`, inline: true },
                    { name: 'Best Time to Join', value: bestTimes ? `${bestTimes.hour}:00` : 'N/A', inline: true },
                    { name: 'Best Day', value: bestTimes ? this.getDayName(bestTimes.day) : 'N/A', inline: true }
                ]
            });
        } catch (error) {
            this.logError(error, 'generateInsights');
            return this.createEmbed({
                title: '📊 Welcome System Insights',
                description: 'Failed to generate insights',
                color: '#ff0000'
            });
        }
    }

    static async getGuildStats(guildId) {
        // Reference existing code from welcomeStats.js
        // startLine: 63
        // endLine: 78
    }

    static async calculateRetentionRate(stats) {
        const thirtyDaysAgo = this.getTimeframeDate('30d');
        const joinedUsers = stats.members.filter(m => m.joinedAt < thirtyDaysAgo);
        if (!joinedUsers.length) return 0;

        const stillPresent = await this.aggregateData(
            User,
            {
                guildId: stats.guildId,
                userId: { $in: joinedUsers.map(u => u.userId) },
                leftAt: null
            },
            { _id: null, count: { $sum: 1 } }
        );

        return (stillPresent[0]?.count || 0) / joinedUsers.length * 100;
    }

    static analyzeBestTimes(stats) {
        if (!stats?.hourlyJoins || !stats?.dailyJoins) return null;

        const hourlyJoins = Object.entries(stats.hourlyJoins);
        const dailyJoins = Object.entries(stats.dailyJoins);

        if (!hourlyJoins.length || !dailyJoins.length) return null;

        const bestHour = hourlyJoins.reduce((a, b) => b[1] > a[1] ? b : a);
        const bestDay = dailyJoins.reduce((a, b) => b[1] > a[1] ? b : a);

        return {
            hour: parseInt(bestHour[0]),
            day: parseInt(bestDay[0])
        };
    }
}

module.exports = WelcomeAnalytics; 