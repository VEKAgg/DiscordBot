const { logger } = require('../logger');
const { User, CommandLog, GuildAnalytics } = require('../../database');
const { EmbedBuilder } = require('discord.js');

class BaseAnalytics {
    static CLEANUP_INTERVAL = 24 * 60 * 60 * 1000; // 24 hours
    static MAX_AGE = 30 * 24 * 60 * 60 * 1000; // 30 days

    static async initialize() {
        try {
            await this.setupIndexes();
            this.startCleanupTask();
            logger.info(`${this.name} initialized`);
        } catch (error) {
            logger.error(`${this.name} initialization failed:`, error);
            throw error;
        }
    }

    static async setupIndexes() {
        const indexes = this.getRequiredIndexes();
        for (const [model, modelIndexes] of Object.entries(indexes)) {
            try {
                await model.createIndexes(modelIndexes);
            } catch (error) {
                logger.error(`Failed to create indexes for ${model.modelName}:`, error);
                throw error;
            }
        }
    }

    static getRequiredIndexes() {
        return {
            [GuildAnalytics.modelName]: [
                { guildId: 1, date: 1 },
                { updatedAt: 1 }
            ],
            [CommandLog.modelName]: [
                { guildId: 1, commandName: 1, timestamp: 1 },
                { timestamp: 1 }
            ],
            [User.modelName]: [
                { guildId: 1, userId: 1 },
                { joinedAt: 1 }
            ]
        };
    }

    static startCleanupTask() {
        setInterval(() => this.cleanup(), this.CLEANUP_INTERVAL);
    }

    static async cleanup() {
        const cutoff = new Date(Date.now() - this.MAX_AGE);
        try {
            await Promise.all([
                CommandLog.deleteMany({ timestamp: { $lt: cutoff } }),
                GuildAnalytics.deleteMany({ timestamp: { $lt: cutoff } })
            ]);
        } catch (error) {
            logger.error(`${this.name} cleanup failed:`, error);
        }
    }

    static async aggregateData(model, match, group, options = {}) {
        try {
            const pipeline = [
                { $match: match },
                { $group: group }
            ];

            if (options.sort) pipeline.push({ $sort: options.sort });
            if (options.limit) pipeline.push({ $limit: options.limit });

            return await model.aggregate(pipeline);
        } catch (error) {
            logger.error(`${this.name} aggregation failed:`, error);
            return [];
        }
    }

    static getTimeframeDate(timeframe) {
        const now = Date.now();
        const days = parseInt(timeframe.replace('d', '')) || 7;
        return new Date(now - (days * 24 * 60 * 60 * 1000));
    }

    static logError(error, methodName) {
        logger.error(`[${this.name}] Error in ${methodName}:`, error);
    }

    static async getGuildStats(guildId, timeframe) {
        try {
            const startDate = this.getTimeframeDate(timeframe);
            return await GuildAnalytics.findOne({
                guildId,
                date: { $gte: startDate }
            }) || await GuildAnalytics.create({ guildId });
        } catch (error) {
            this.logError(error, 'getGuildStats');
            return null;
        }
    }

    static async updateGuildStats(guildId, update) {
        try {
            return await GuildAnalytics.findOneAndUpdate(
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

    static createEmbed({ title, description = '', fields = [], color = '#00ff00', footer = null }) {
        const embed = new EmbedBuilder()
            .setTitle(title)
            .setColor(color)
            .setTimestamp();

        if (description) embed.setDescription(description);
        if (fields.length) embed.addFields(fields);
        if (footer) embed.setFooter(footer);

        return embed;
    }

    static async ping() {
        try {
            await GuildAnalytics.findOne();
            return true;
        } catch {
            return false;
        }
    }
}

module.exports = BaseAnalytics; 