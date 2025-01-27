const { EmbedBuilder } = require('discord.js');
const { User } = require('../database');
const { logger } = require('../utils/logger');
const StaffAlerts = require('../utils/staffAlerts');
const { ActivityType } = require('discord.js');
const { RoleManager } = require('../utils/roleManager');
const { PermissionFlagsBits } = require('discord.js');

module.exports = {
    name: 'presenceUpdate',
    async execute(oldPresence, newPresence) {
        if (!newPresence?.user || newPresence.user.bot) return;

        try {
            // Add permission check before role operations
            if (!newPresence.guild.members.me.permissions.has(PermissionFlagsBits.ManageRoles)) {
                logger.warn(`Missing Manage Roles permission in guild ${newPresence.guild.id}`);
                return;
            }
            
            // Check if bot's highest role is above the role it's trying to manage
            const botRole = newPresence.guild.members.me.roles.highest;
            const targetRole = newPresence.guild.roles.cache.get('1332452751577452574');
            
            if (targetRole && botRole.position <= targetRole.position) {
                logger.warn(`Bot's role position (${botRole.position}) is not high enough to manage role ${targetRole.name} (${targetRole.position})`);
                return;
            }

            let user = await User.findOne({ 
                userId: newPresence.userId,
                guildId: newPresence.guild.id 
            });

            if (!user) {
                user = new User({
                    userId: newPresence.userId,
                    guildId: newPresence.guild.id,
                    activity: { richPresence: [] }
                });
            }

            // End any existing activities
            if (oldPresence?.activities?.length > 0) {
                const now = new Date();
                await User.updateMany(
                    {
                        userId: newPresence.userId,
                        guildId: newPresence.guild.id,
                        'activity.richPresence.endTimestamp': null
                    },
                    {
                        $set: {
                            'activity.richPresence.$[elem].endTimestamp': now,
                            'activity.richPresence.$[elem].duration': {
                                $subtract: [now, '$activity.richPresence.$[elem].timestamp']
                            }
                        }
                    },
                    {
                        arrayFilters: [{ 'elem.endTimestamp': null }]
                    }
                );
            }

            // Track new activities
            for (const activity of newPresence.activities) {
                if (activity.type === ActivityType.Playing) {
                    const activityData = {
                        type: 'PLAYING',
                        name: activity.name,
                        timestamp: new Date(),
                        details: activity.details || '',
                        state: activity.state || '',
                        applicationId: activity.applicationId || '',
                        endTimestamp: null,
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
                                activity_type: 'PLAYING',
                                user: `<@${newPresence.userId}>`,
                                details: activity.details || 'None',
                                state: activity.state || 'None'
                            }
                        });
                    }

                    user.activity.richPresence.push(activityData);
                }
            }

            await user.save();
            await checkAndAssignRoles(newPresence.member, newPresence.activities);

            const member = newPresence.member;

            // Check if the user is streaming
            const isLive = newPresence.activities.some(activity => 
                activity.type === ActivityType.Streaming
            );

            const liveRole = member.guild.roles.cache.find(role => role.name === 'Live');
            if (isLive) {
                if (liveRole) {
                    await member.roles.add(liveRole);
                }
            } else {
                if (liveRole) {
                    await member.roles.remove(liveRole);
                }
            }

            // Assign streamer chat access role
            const streamerRole = member.guild.roles.cache.find(role => role.name === 'Streamer');
            if (isLive && streamerRole) {
                await member.roles.add(streamerRole);
            }

        } catch (error) {
            logger.error('Presence Update Error:', error);
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
