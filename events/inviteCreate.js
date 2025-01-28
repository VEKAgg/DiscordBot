const { EmbedBuilder } = require('discord.js');
const { logger } = require('../utils/logger');

module.exports = {
    name: 'inviteCreate',
    async execute(invite) {
        try {
            // Cache the invite
            invite.client.invites.set(invite.code, {
                code: invite.code,
                uses: invite.uses,
                maxUses: invite.maxUses,
                inviter: invite.inviter?.id,
                createdAt: invite.createdAt,
                expiresAt: invite.expiresAt
            });

            // Log invite creation
            const logChannel = invite.guild.channels.cache.find(ch => ch.name === 'invite-logs');
            if (logChannel) {
                const embed = new EmbedBuilder()
                    .setTitle('📨 New Invite Created')
                    .setColor('#3498db')
                    .addFields([
                        { name: 'Created By', value: invite.inviter ? `<@${invite.inviter.id}>` : 'Unknown', inline: true },
                        { name: 'Code', value: invite.code, inline: true },
                        { name: 'Max Uses', value: invite.maxUses ? invite.maxUses.toString() : 'Unlimited', inline: true },
                        { name: 'Expires', value: invite.expiresAt ? `<t:${Math.floor(invite.expiresAt / 1000)}:R>` : 'Never' }
                    ])
                    .setTimestamp();

                await logChannel.send({ embeds: [embed] });
            }
        } catch (error) {
            logger.error('Error in inviteCreate event:', error);
        }
    }
}; 