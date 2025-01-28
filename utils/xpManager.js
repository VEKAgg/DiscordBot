const { logger } = require('./logger');
const { User } = require('../database');

class XPManager {
    static calculateLevel(xp) {
        return Math.floor(Math.sqrt(xp / 100));
    }

    static calculateNextLevelXP(level) {
        return Math.pow(level + 1, 2) * 100;
    }

    static createProgressBar(progress) {
        const barLength = 20;
        const filledLength = Math.round((progress / 100) * barLength);
        const emptyLength = barLength - filledLength;
        
        const filled = '█'.repeat(filledLength);
        const empty = '░'.repeat(emptyLength);
        
        return `${filled}${empty} ${Math.round(progress)}%`;
    }

    static async addXP(userId, guildId, amount) {
        const user = await User.findOneAndUpdate(
            { userId, guildId },
            { 
                $inc: { xp: amount },
                $setOnInsert: { joinedAt: new Date() }
            },
            { upsert: true, new: true }
        );

        const newLevel = this.calculateLevel(user.xp);
        if (newLevel > user.level) {
            await User.updateOne(
                { userId, guildId },
                { $set: { level: newLevel } }
            );
            return { levelUp: true, newLevel };
        }

        return { levelUp: false };
    }

    static async updateXP(member, amount) {
        const user = await User.findOneAndUpdate(
            { userId: member.id, guildId: member.guild.id },
            { $inc: { xp: amount } },
            { new: true, upsert: true }
        );

        const oldLevel = Math.floor(Math.sqrt((user.xp - amount) / 100));
        const newLevel = Math.floor(Math.sqrt(user.xp / 100));

        if (newLevel > oldLevel) {
            // Send level up message
            const channel = member.guild.systemChannel || member.guild.channels.cache.first();
            if (channel) {
                channel.send({
                    embeds: [{
                        title: '🎉 Level Up!',
                        description: `Congratulations ${member}! You've reached level ${newLevel}!`,
                        color: 0x00ff00
                    }]
                });
            }
        }

        await this.checkForRoleUpgrade(member, user.xp);
        return user;
    }

    static async handleActivity(member, activityType) {
        try {
            let xpAmount = 0;

            switch (activityType) {
                case 'textChat':
                    xpAmount = 5; // XP for sending a message
                    break;
                case 'voiceChat':
                    xpAmount = 10; // XP for staying in voice chat
                    break;
                case 'commandUsage':
                    xpAmount = 15; // XP for using a command
                    break;
                case 'richPresence':
                    xpAmount = 20; // XP for having a specific rich presence
                    break;
                case 'boosting':
                    xpAmount = 50; // XP for boosting the server
                    break;
                case 'dateJoined':
                    const daysInServer = (Date.now() - member.joinedTimestamp) / (1000 * 60 * 60 * 24);
                    xpAmount = Math.floor(daysInServer); // 1 XP per day in the server
                    break;
                case 'accountAge':
                    const accountAge = (Date.now() - member.user.createdTimestamp) / (1000 * 60 * 60 * 24);
                    xpAmount = Math.floor(accountAge / 30); // 1 XP for every month the account is old
                    break;
                default:
                    break;
            }

            if (xpAmount > 0) {
                await this.updateXP(member, xpAmount);
            }

            logger.info(`Awarded XP to ${member.user.tag} for ${activityType}`);
        } catch (error) {
            logger.error('XP handling error:', error);
        }
    }

    static async checkForRoleUpgrade(member, xp) {
        const roles = [
            { name: 'Active', threshold: 100 },
            { name: 'Active+', threshold: 200 },
            { name: 'Active Pro', threshold: 300 }
        ];

        for (const role of roles) {
            if (xp >= role.threshold) {
                const roleToAssign = member.guild.roles.cache.find(r => r.name === role.name);
                if (roleToAssign && !member.roles.cache.has(roleToAssign.id)) {
                    await member.roles.add(roleToAssign);
                }
            }
        }
    }
}

module.exports = { XPManager }; 