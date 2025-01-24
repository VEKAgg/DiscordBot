const { logger } = require('../logger');
const { User, GuildAnalytics } = require('../../database');

class BaseAnalytics {
    static async initialize() {
        try {
            // Ensure indexes are created
            await GuildAnalytics.createIndexes();
            logger.info(`${this.name} analytics initialized`);
        } catch (error) {
            this.logError(error, 'initialize');
        }
    }

    static logError(error, methodName) {
        logger.error(`[${this.name}] Error in ${methodName}:`, error);
    }

    static async getGuildStats(guildId) {
        try {
            return await GuildAnalytics.findOne({ guildId }) || await GuildAnalytics.create({ guildId });
        } catch (error) {
            this.logError(error, 'getGuildStats');
            return null;
        }
    }

    static async updateGuildStats(guildId, update) {
        try {
            await GuildAnalytics.findOneAndUpdate(
                { guildId },
                update,
                { upsert: true, new: true }
            );
        } catch (error) {
            this.logError(error, 'updateGuildStats');
        }
    }

    static async getGuildData(guildId, startDate) {
        try {
            return await User.aggregate([
                { $match: { guildId } },
                { $match: { createdAt: { $gte: startDate } } }
            ]);
        } catch (error) {
            this.logError(error, 'getGuildData');
            return [];
        }
    }
}

module.exports = BaseAnalytics; 