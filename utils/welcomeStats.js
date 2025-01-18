const { EmbedBuilder } = require('discord.js');
const { User } = require('../database');

class WelcomeStats {
    static async trackWelcome(member, { dmSuccess, assignedRoles, isVerified }) {
        try {
            const stats = await this.getGuildStats(member.guild.id);
            const hourOfDay = new Date().getHours();
            const dayOfWeek = new Date().getDay();

            // Update statistics
            stats.totalJoins += 1;
            stats.hourlyJoins[hourOfDay] += 1;
            stats.dailyJoins[dayOfWeek] += 1;
            
            if (dmSuccess) stats.successfulDMs += 1;
            if (isVerified) stats.verifiedJoins += 1;

            // Track retention (we'll update left status in guildMemberRemove)
            stats.members.push({
                userId: member.id,
                joinedAt: new Date(),
                assignedRoles,
                dmSuccess,
                isVerified
            });

            await stats.save();
            
            // Generate insights if threshold reached
            if (stats.totalJoins % 10 === 0) { // Every 10 joins
                await this.generateInsights(member.guild);
            }
        } catch (error) {
            console.error('Error tracking welcome stats:', error);
        }
    }

    static async generateInsights(guild) {
        const stats = await this.getGuildStats(guild.id);
        const retentionRate = await this.calculateRetentionRate(stats);
        const bestTimes = this.analyzeBestTimes(stats);

        const embed = new EmbedBuilder()
            .setTitle('📊 Welcome System Insights')
            .addFields([
                { name: 'Total Joins', value: stats.totalJoins.toString(), inline: true },
                { name: 'DM Success Rate', value: `${((stats.successfulDMs / stats.totalJoins) * 100).toFixed(1)}%`, inline: true },
                { name: 'Verification Rate', value: `${((stats.verifiedJoins / stats.totalJoins) * 100).toFixed(1)}%`, inline: true },
                { name: 'Member Retention', value: `${retentionRate.toFixed(1)}%`, inline: true },
                { name: 'Best Time to Join', value: `${bestTimes.hour}:00`, inline: true },
                { name: 'Best Day', value: this.getDayName(bestTimes.day), inline: true }
            ])
            .setColor('#00ff00')
            .setTimestamp();

        const insightChannel = guild.channels.cache.find(ch => ch.name === 'welcome-insights');
        if (insightChannel) {
            await insightChannel.send({ embeds: [embed] });
        }
    }

    static async getGuildStats(guildId) {
        return await User.findOneAndUpdate(
            { guildId, type: 'welcome_stats' },
            {
                $setOnInsert: {
                    hourlyJoins: Array(24).fill(0),
                    dailyJoins: Array(7).fill(0),
                    totalJoins: 0,
                    successfulDMs: 0,
                    verifiedJoins: 0,
                    members: []
                }
            },
            { upsert: true, new: true }
        );
    }

    private static getDayName(day) {
        return ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][day];
    }
}

module.exports = WelcomeStats; 