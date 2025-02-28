const XPConfig = require('../models/XPConfig');
const UserXP = require('../models/UserXP');
const { logger } = require('./logger');

const xpSystem = {
    // Base XP settings
    defaultSettings: {
        messageXP: { min: 15, max: 25 },
        voiceXP: { perMinute: 10 },
        activityXP: { min: 50, max: 100 },
        cooldown: 60000, // 1 minute
        multipliers: {
            boost: 1.5,
            weekend: 2,
            event: 2.5
        }
    },

    async calculateXP(user, guild, activity) {
        try {
            const config = await XPConfig.findOne({ guildId: guild.id }) || { settings: this.defaultSettings };
            const now = Date.now();
            
            // Get user's current XP state
            let userXP = await UserXP.findOne({ userId: user.id, guildId: guild.id });
            
            if (!userXP) {
                userXP = new UserXP({
                    userId: user.id,
                    guildId: guild.id,
                    xp: 0,
                    level: 0,
                    lastXPGain: 0
                });
            }

            // Check cooldown
            if (now - userXP.lastXPGain < config.settings.cooldown) {
                return null;
            }

            // Calculate base XP
            let xpGain = 0;
            switch (activity.type) {
                case 'message':
                    xpGain = Math.floor(
                        Math.random() * 
                        (config.settings.messageXP.max - config.settings.messageXP.min + 1) + 
                        config.settings.messageXP.min
                    );
                    break;
                case 'voice':
                    xpGain = config.settings.voiceXP.perMinute;
                    break;
                case 'activity':
                    xpGain = Math.floor(
                        Math.random() * 
                        (config.settings.activityXP.max - config.settings.activityXP.min + 1) + 
                        config.settings.activityXP.min
                    );
                    break;
            }

            // Apply multipliers
            if (user.premiumSince) xpGain *= config.settings.multipliers.boost;
            if (this.isWeekend()) xpGain *= config.settings.multipliers.weekend;
            // Add more multipliers as needed

            // Update user XP
            userXP.xp += xpGain;
            userXP.lastXPGain = now;

            // Check for level up
            const newLevel = this.calculateLevel(userXP.xp);
            const leveledUp = newLevel > userXP.level;
            userXP.level = newLevel;

            await userXP.save();

            return {
                xpGained: xpGain,
                newXP: userXP.xp,
                newLevel: userXP.level,
                leveledUp
            };
        } catch (error) {
            logger.error('Error calculating XP:', error);
            return null;
        }
    },

    calculateLevel(xp) {
        return Math.floor(0.1 * Math.sqrt(xp));
    },

    isWeekend() {
        const day = new Date().getDay();
        return day === 0 || day === 6;
    }
};

module.exports = xpSystem; 