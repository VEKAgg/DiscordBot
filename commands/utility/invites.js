const { EmbedBuilder, SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { User } = require('../../database');
const InviteAnalytics = require('../../utils/analytics/inviteAnalytics');

module.exports = {
    name: 'invites',
    description: 'Check server invites',
    category: 'utility',
    permissions: [PermissionFlagsBits.ManageGuild],
    slashCommand: new SlashCommandBuilder()
        .setName('invites')
        .setDescription('Check server invites')
        .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
        .addUserOption(option =>
            option.setName('user')
                .setDescription('Check invites for a specific user')
                .setRequired(false)),

    async execute(interaction) {
        const isSlash = interaction.commandName !== undefined;
        const targetUser = isSlash 
            ? interaction.options.getUser('user')
            : interaction.mentions.users.first();

        try {
            const invites = await (isSlash ? interaction.guild : interaction.guild).invites.fetch();
            const userInvites = new Map();

            // Count invites per user
            invites.forEach(invite => {
                const inviter = invite.inviter;
                if (inviter && (!targetUser || inviter.id === targetUser.id)) {
                    const count = userInvites.get(inviter.id) || { uses: 0, code: invite.code };
                    count.uses += invite.uses;
                    userInvites.set(inviter.id, count);
                }
            });

            // Sort users by invite count
            const sortedInviters = [...userInvites.entries()]
                .sort((a, b) => b[1].uses - a[1].uses)
                .slice(0, 10);

            const embed = new EmbedBuilder()
                .setTitle('📊 Server Invites')
                .setDescription(targetUser ? `Invites for ${targetUser.tag}` : 'Top 10 Inviters')
                .setColor('#FFA500')
                .setTimestamp();

            if (sortedInviters.length > 0) {
                embed.addFields(
                    sortedInviters.map((entry, index) => ({
                        name: `${index + 1}. ${(isSlash ? interaction.guild : interaction.guild).members.cache.get(entry[0])?.user.tag || 'Unknown User'}`,
                        value: `Invites: ${entry[1].uses} (Code: ${entry[1].code})`,
                        inline: false
                    }))
                );
            } else {
                embed.setDescription('No invite data found.');
            }

            const reply = { embeds: [embed] };
            if (isSlash) {
                await interaction.reply(reply);
            } else {
                await interaction.channel.send(reply);
            }
        } catch (error) {
            console.error('Error fetching invites:', error);
            const reply = { 
                content: 'Failed to fetch invite information.',
                ephemeral: true 
            };
            if (isSlash) {
                await interaction.reply(reply);
            } else {
                await interaction.reply(reply.content);
            }
        }
    }
};

function calculateInviteLevel(invites) {
    if (invites < 5) return 0;
    if (invites < 10) return 1;
    if (invites < 25) return 2;
    if (invites < 50) return 3;
    if (invites < 100) return 4;
    return Math.floor(5 + Math.log10(invites - 99));
}

function getLevelRequirement(level) {
    switch (level) {
        case 0: return 0;
        case 1: return 5;
        case 2: return 10;
        case 3: return 25;
        case 4: return 50;
        default: return 100 + Math.pow(10, level - 5);
    }
}

function getNextLevelRequirement(currentLevel) {
    return getLevelRequirement(currentLevel + 1);
}

function getInviteLevelColor(level) {
    const colors = ['#GRAY', '#GREEN', '#BLUE', '#PURPLE', '#GOLD', '#RED'];
    return colors[Math.min(level, colors.length - 1)];
}

function getInviteLevelPerks(level) {
    const perks = [
        'No perks yet',
        '• Custom role color',
        '• Custom nickname',
        '• Access to exclusive channels',
        '• Can create private voice channels',
        '• VIP status + all previous perks'
    ];
    return perks[Math.min(level, perks.length - 1)];
}

function createProgressBar(current, total, length = 10) {
    const progress = Math.round((current / total) * length);
    return '█'.repeat(progress) + '░'.repeat(length - progress);
} 