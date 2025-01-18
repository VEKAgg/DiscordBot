const { EmbedBuilder } = require('discord.js');
const { logger } = require('./logger');

async function applyInviteLevelRewards(guild, userId, level) {
    try {
        const member = await guild.members.fetch(userId);
        if (!member) return;

        const rewards = {
            1: {
                roles: ['Level 1 Inviter'],
                color: '#2ecc71'
            },
            2: {
                roles: ['Level 2 Inviter'],
                color: '#3498db'
            },
            3: {
                roles: ['Level 3 Inviter', 'VIP'],
                color: '#9b59b6'
            },
            4: {
                roles: ['Level 4 Inviter', 'VIP+'],
                color: '#f1c40f'
            },
            5: {
                roles: ['Elite Inviter', 'VIP++'],
                color: '#e74c3c'
            }
        };

        const reward = rewards[level];
        if (!reward) return;

        // Remove old invite roles
        const oldRoles = member.roles.cache.filter(role => 
            role.name.includes('Inviter') || role.name.includes('VIP')
        );
        await member.roles.remove(oldRoles);

        // Add new roles
        for (const roleName of reward.roles) {
            let role = guild.roles.cache.find(r => r.name === roleName);
            if (!role) {
                role = await guild.roles.create({
                    name: roleName,
                    color: reward.color,
                    reason: 'Invite reward system'
                });
            }
            await member.roles.add(role);
        }

        // Send DM to user
        const dmEmbed = new EmbedBuilder()
            .setTitle('🎉 New Invite Rewards!')
            .setDescription(`Congratulations! You've reached invite level ${level}!`)
            .addFields([
                { name: 'New Roles', value: reward.roles.join(', ') },
                { name: 'Custom Color', value: reward.color }
            ])
            .setColor(reward.color)
            .setTimestamp();

        await member.send({ embeds: [dmEmbed] });

    } catch (error) {
        logger.error('Error applying invite rewards:', error);
    }
}

module.exports = { applyInviteLevelRewards }; 