const BaseAnalytics = require('./baseAnalytics');
const { GuildAnalytics, CommandLog } = require('../../database');

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

    static async getGuildStats(guildId, type = 'overview', timeframe = '7d') {
        try {
            const startDate = this.getTimeframeDate(timeframe);
            const [stats, commandUsage] = await Promise.all([
                this.aggregateData(
                    GuildAnalytics,
                    {
                        guildId,
                        date: { $gte: startDate }
                    },
                    {
                        _id: null,
                        totalCommands: { $sum: '$metrics.totalCommands' },
                        totalErrors: { $sum: '$metrics.errorCount' },
                        avgCommandsPerDay: { $avg: '$metrics.totalCommands' }
                    }
                ),
                this.aggregateData(
                    CommandLog,
                    {
                        guildId,
                        timestamp: { $gte: startDate }
                    },
                    {
                        _id: '$commandName',
                        count: { $sum: 1 },
                        successCount: {
                            $sum: { $cond: [{ $eq: ['$status', 'success'] }, 1, 0] }
                        }
                    },
                    { count: -1 },
                    10
                )
            ]);

            return {
                overview: {
                    totalCommands: stats[0]?.totalCommands || 0,
                    totalErrors: stats[0]?.totalErrors || 0,
                    avgCommandsPerDay: Math.round(stats[0]?.avgCommandsPerDay || 0),
                    successRate: stats[0] ? 
                        ((1 - (stats[0].totalErrors / stats[0].totalCommands)) * 100).toFixed(1) + '%' 
                        : '0%'
                },
                topCommands: commandUsage.map(cmd => ({
                    name: cmd._id,
                    uses: cmd.count,
                    successRate: ((cmd.successCount / cmd.count) * 100).toFixed(1) + '%'
                }))
            };
        } catch (error) {
            this.logError(error, 'getGuildStats');
            return null;
        }
    }

    static async aggregateDailyStats() {
        try {
            const guilds = await GuildAnalytics.distinct('guildId');
            await Promise.all(guilds.map(guildId => this.getGuildStats(guildId)));
        } catch (error) {
            this.logError(error, 'aggregateDailyStats');
        }
    }
}

module.exports = CommandAnalytics; 