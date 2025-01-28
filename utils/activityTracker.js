const { User } = require('../database');
const { logger } = require('./logger');

class ActivityTracker {
    static async handleActivity(member, activity) {
        try {
            await User.findOneAndUpdate(
                { userId: member.id, guildId: member.guild.id },
                {
                    $push: {
                        'activity.richPresence': {
                            name: activity.name,
                            type: activity.type,
                            timestamp: new Date(),
                            duration: 0
                        }
                    }
                }
            );
        } catch (error) {
            logger.error('Activity tracking error:', error);
        }
    }
}

module.exports = ActivityTracker;
