const { EmbedBuilder } = require('discord.js');
const { User } = require('../database');
const { logger } = require('../utils/logger');
const StaffAlerts = require('../utils/staffAlerts');

module.exports = {
    name: 'presenceUpdate',
    async execute(oldPresence, newPresence) {
        if (!newPresence?.user || newPresence.user.bot) return;

        try {
            const user = await User.findOne({ 
                userId: newPresence.userId,
                guildId: newPresence.guild.id 
            });

            if (!user) return;

            // Track all types of activities
            for (const activity of newPresence.activities) {
                const activityData = {
                    type: activity.type,
                    name: activity.name,
                    timestamp: new Date(),
                    details: activity.details || '',
                    state: activity.state || '',
                    applicationId: activity.applicationId || '',
                    duration: 0
                };

                // Check for unknown applications/games
                const knownActivities = await User.distinct('activity.richPresence.name');
                if (!knownActivities.includes(activity.name)) {
                    await StaffAlerts.send(newPresence.guild, {
                        type: 'new_activity',
                        priority: 'medium',
                        content: `New activity type detected that might need role configuration`,
                        data: {
                            activity_name: activity.name,
                            activity_type: activity.type,
                            user: `<@${newPresence.userId}>`,
                            details: activity.details || 'None',
                            state: activity.state || 'None'
                        }
                    });
                }

                // Update user's activity record
                user.activity.richPresence.push(activityData);
            }

            // Check for role assignments
            await checkAndAssignRoles(newPresence.member, user.activity.richPresence);
            await user.save();

        } catch (error) {
            logger.error('Error in presence update:', error);
        }
    }
};

async function checkAndAssignRoles(member, activities) {
    const roleRequirements = {
        gaming: { type: 'PLAYING', threshold: 5 },
        music: { type: 'LISTENING', threshold: 10 },
        streaming: { type: 'STREAMING', threshold: 3 },
        developer: { 
            type: 'CUSTOM',
            names: ['Visual Studio Code', 'IntelliJ IDEA', 'GitHub Desktop'],
            threshold: 5
        }
    };

    for (const [category, requirement] of Object.entries(roleRequirements)) {
        const activityCount = activities.filter(a => 
            requirement.type === 'CUSTOM' 
                ? requirement.names.includes(a.name)
                : a.type === requirement.type
        ).length;

        const roleId = getRoleIdForCategory(category);
        if (activityCount >= requirement.threshold && !member.roles.cache.has(roleId)) {
            try {
                await member.roles.add(roleId);
            } catch (error) {
                const staffChannel = member.guild.channels.cache.find(ch => ch.name === 'staff-alerts');
                if (staffChannel) {
                    await staffChannel.send(
                        `<@&STAFF_ROLE_ID> Failed to assign ${category} role to <@${member.id}>`
                    );
                }
            }
        }
    }
}

function getRoleIdForCategory(category) {
    const roleIds = {
        gaming: 'GAMING_ROLE_ID',
        music: 'MUSIC_ROLE_ID',
        streaming: 'STREAMER_ROLE_ID',
        developer: 'DEVELOPER_ROLE_ID'
    };
    return roleIds[category];
}
