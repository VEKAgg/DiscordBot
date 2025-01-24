const User = require('../models/User');
const { logger } = require('./logger');

async function updatePresence(oldPresence, newPresence) {
    if (!newPresence.guild || !newPresence.user) return;

    try {
        const user = await User.findOneAndUpdate(
            { 
                userId: newPresence.userId,
                guildId: newPresence.guild.id
            },
            {
                $set: { lastPresenceUpdate: new Date() },
                $push: {
                    'activity.richPresence': {
                        name: newPresence.activities[0]?.name || 'Unknown',
                        details: newPresence.activities[0]?.details || '',
                        startTimestamp: new Date(),
                        endTimestamp: null
                    }
                }
            },
            { 
                upsert: true,
                new: true
            }
        );

        // Update previous activity end time if exists
        if (oldPresence?.activities?.length > 0) {
            await User.updateOne(
                { 
                    userId: newPresence.userId,
                    guildId: newPresence.guild.id,
                    'activity.richPresence.endTimestamp': null
                },
                {
                    $set: {
                        'activity.richPresence.$.endTimestamp': new Date()
                    }
                }
            );
        }
    } catch (error) {
        logger.error('Presence update error:', error);
    }
}

module.exports = { updatePresence }; 