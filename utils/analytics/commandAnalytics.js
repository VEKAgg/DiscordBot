const BaseAnalytics = require('./baseAnalytics');
const { CommandLog, GuildAnalytics } = require('../../database');

class CommandAnalytics extends BaseAnalytics {
    static async logCommand(commandName, userId, guildId, args = [], executionTime = 0, status = 'success', errorMessage = null) {
        try {
            const today = new Date();
            today.setHours(0, 0, 0, 0);

            await CommandLog.create({
                commandName,
                userId,
                guildId,
                args,
                executionTime,
                status,
                errorMessage
            });

            await GuildAnalytics.findOneAndUpdate(
                { guildId, date: today },
                {
                    $inc: {
                        'metrics.totalCommands': 1,
                        'metrics.errorCount': status === 'error' ? 1 : 0,
                        [`metrics.commandUsage.${commandName}`]: 1
                    },
                    $set: { updatedAt: new Date() }
                },
                { upsert: true }
            );
        } catch (error) {
            this.logError(error, 'logCommand');
        }
    }

    static async getGuildStats(guildId, days = 7) {
        try {
            const startDate = new Date();
            startDate.setDate(startDate.getDate() - days);

            const stats = await GuildAnalytics.aggregate([
                {
                    $match: {
                        guildId,
                        date: { $gte: startDate }
                    }
                },
                {
                    $group: {
                        _id: null,
                        totalCommands: { $sum: '$metrics.totalCommands' },
                        totalErrors: { $sum: '$metrics.errorCount' },
                        avgCommandsPerDay: { $avg: '$metrics.totalCommands' }
                    }
                }
            ]);

            const commandUsage = await CommandLog.aggregate([
                {
                    $match: {
                        guildId,
                        timestamp: { $gte: startDate }
                    }
                },
                {
                    $group: {
                        _id: '$commandName',
                        count: { $sum: 1 }
                    }
                },
                { $sort: { count: -1 } },
                { $limit: 10 }
            ]);

            return {
                overview: stats[0] || { totalCommands: 0, totalErrors: 0, avgCommandsPerDay: 0 },
                topCommands: commandUsage
            };
        } catch (error) {
            this.logError(error, 'getGuildStats');
            return null;
        }
    }

    static async aggregateDailyStats() {
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        try {
            const guilds = await GuildAnalytics.distinct('guildId');
            await Promise.all(guilds.map(guildId => this.getGuildStats(guildId)));
        } catch (error) {
            this.logError(error, 'aggregateDailyStats');
        }
    }
}

module.exports = CommandAnalytics; 