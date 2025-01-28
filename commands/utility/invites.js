const { EmbedBuilder, SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { User } = require('../../database');
const InviteAnalytics = require('../../utils/analytics/inviteAnalytics');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'invites',
    description: 'Check server invites',
    category: 'utility',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
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
        const targetUser = interaction.options.getUser('user');
        const invites = await interaction.guild.invites.fetch();
        
        let userInvites;
        if (targetUser) {
            userInvites = invites.filter(invite => invite.inviter?.id === targetUser.id);
        }

        const embed = new EmbedBuilder()
            .setTitle(targetUser ? `${targetUser.tag}'s Invites` : 'Server Invites')
            .setColor('#2B2D31')
            .setDescription(
                targetUser ?
                    userInvites.map(invite => 
                        `Code: \`${invite.code}\` - Uses: ${invite.uses || 0}`
                    ).join('\n') || 'No invites found' :
                    invites.map(invite => 
                        `Code: \`${invite.code}\` - By: ${invite.inviter?.tag} - Uses: ${invite.uses || 0}`
                    ).join('\n') || 'No invites found'
            )
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        await interaction.reply({ embeds: [embed] });
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