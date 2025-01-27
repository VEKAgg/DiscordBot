const { logger } = require('../logger');
const { User, GuildAnalytics } = require('../../database');
const { EmbedBuilder } = require('discord.js');

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

    static getTimeframeDate(timeframe = '7d') {
        const days = parseInt(timeframe.replace('d', ''));
        const date = new Date();
        date.setDate(date.getDate() - days);
        return date;
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

    static async aggregateData(model, matchQuery, groupQuery, sortQuery = null, limit = null) {
        try {
            const pipeline = [
                { $match: matchQuery },
                { $group: groupQuery }
            ];

            if (sortQuery) pipeline.push({ $sort: sortQuery });
            if (limit) pipeline.push({ $limit: limit });

            return await model.aggregate(pipeline);
        } catch (error) {
            this.logError(error, 'aggregateData');
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

    static async cleanupOldData(cutoff) {
        try {
            await GuildAnalytics.deleteMany({
                date: { $lt: cutoff }
            });
        } catch (error) {
            this.logError(error, 'cleanupOldData');
        }
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