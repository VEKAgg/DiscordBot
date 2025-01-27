const { EmbedBuilder } = require('discord.js');
const { User } = require('../database');
const { logger } = require('../utils/logger');
const StaffAlerts = require('../utils/staffAlerts');
const { ActivityType } = require('discord.js');
const { RoleManager } = require('../utils/roleManager');

module.exports = {
    name: 'presenceUpdate',
    async execute(oldPresence, newPresence) {
        try {
            const member = newPresence.member;
            // Find or create user document
            let user = await User.findOne({ 
                userId: member.id,
                guildId: member.guild.id 
            });

            if (!user) {
                user = new User({
                    userId: member.id,
                    guildId: member.guild.id,
                    username: member.user.username
                });
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

            const streamerRole = member.guild.roles.cache.find(role => role.name === 'Streamer');
            if (isLive && streamerRole) {
                await member.roles.add(streamerRole);
            }
        } catch (error) {
            logger.error('Presence update error:', error);
        }
    }
};

module.exports = {
    name: 'guildMemberAdd',
    async execute(member) {
        try {
            // Create user entry in database
            const userData = await User.findOneAndUpdate(
                { userId: member.id, guildId: member.guild.id },
                {
                    username: member.user.username,
                    discriminator: member.user.discriminator,
                    joinedAt: new Date()
                },
                { upsert: true, new: true }
            );

            // Send welcome message
            const welcomeChannel = member.guild.channels.cache.find(ch => ch.name === 'welcome');
            if (welcomeChannel) {
                const embed = new EmbedBuilder()
                    .setTitle('Welcome!')
                    .setDescription(`Welcome to the server, ${member}!`)
                    .setColor('#00ff00')
                    .setTimestamp();

                await welcomeChannel.send({ embeds: [embed] });
            }

        } catch (error) {
            logger.error('Error in guildMemberAdd event:', error);
        }
    }
};
