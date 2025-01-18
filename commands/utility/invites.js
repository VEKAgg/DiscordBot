const { EmbedBuilder } = require('discord.js');
const { User } = require('../../database');

module.exports = {
    name: 'invites',
    description: 'Check your or another user\'s invite stats',
    async execute(message, args) {
        const target = message.mentions.users.first() || message.author;
        
        try {
            const userData = await User.findOne({ 
                userId: target.id,
                guildId: message.guild.id 
            });

            if (!userData?.invites) {
                return message.reply(`${target.username} hasn't invited anyone yet!`);
            }

            const inviteLevel = calculateInviteLevel(userData.invites.total);
            const nextLevel = getNextLevelRequirement(inviteLevel);
            const progress = userData.invites.total - getLevelRequirement(inviteLevel);
            const remaining = nextLevel - userData.invites.total;

            const embed = new EmbedBuilder()
                .setTitle(`${target.username}'s Invite Stats`)
                .setThumbnail(target.displayAvatarURL())
                .setColor(getInviteLevelColor(inviteLevel))
                .addFields([
                    { name: 'Total Invites', value: `${userData.invites.total}`, inline: true },
                    { name: 'Invite Level', value: `${inviteLevel}`, inline: true },
                    { name: 'Current Perks', value: getInviteLevelPerks(inviteLevel) },
                    { name: 'Next Level', value: `${remaining} more invites needed for level ${inviteLevel + 1}` },
                    { name: 'Progress', value: createProgressBar(progress, nextLevel - getLevelRequirement(inviteLevel)) }
                ])
                .setTimestamp();

            message.channel.send({ embeds: [embed] });
        } catch (error) {
            console.error('Error fetching invite stats:', error);
            message.reply('Failed to fetch invite stats.');
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