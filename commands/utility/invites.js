const { EmbedBuilder } = require('discord.js');
const { User } = require('../../database');
const InviteAnalytics = require('../../utils/analytics/inviteAnalytics');

module.exports = {
    name: 'invite',
    description: 'Get bot invite link',
    async execute(message) {
        const embed = new EmbedBuilder()
            .setTitle('🔗 Invite VEKA Bot')
            .setDescription('Click the link below to add me to your server!')
            .addFields([
                { name: 'Invite Link', value: 'https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&scope=bot&permissions=8' },
                { name: 'Support Server', value: 'https://discord.gg/YOUR_SUPPORT_SERVER' }
            ])
            .setColor('#7289DA')
            .setTimestamp();

        message.channel.send({ embeds: [embed] });
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