const { EmbedBuilder, SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'timeout',
    description: 'Timeout a member',
    category: 'admin',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    permissions: [PermissionFlagsBits.ModerateMembers],
    slashCommand: new SlashCommandBuilder()
        .setName('timeout')
        .setDescription('Timeout a member')
        .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers)
        .addUserOption(option =>
            option.setName('user')
                .setDescription('User to timeout')
                .setRequired(true))
        .addIntegerOption(option =>
            option.setName('duration')
                .setDescription('Timeout duration in minutes')
                .setRequired(true)
                .setMinValue(1)
                .setMaxValue(40320)) // 4 weeks in minutes
        .addStringOption(option =>
            option.setName('reason')
                .setDescription('Reason for timeout')
                .setRequired(false)),

    async execute(interaction) {
        const targetUser = interaction.options.getUser('user');
        const duration = interaction.options.getInteger('duration');
        const reason = interaction.options.getString('reason') || 'No reason provided';
        const member = await interaction.guild.members.fetch(targetUser.id);

        if (!member.moderatable) {
            return interaction.reply({
                content: 'I cannot timeout this user. They may have higher permissions than me.',
                ephemeral: true
            });
        }

        const embed = new EmbedBuilder()
            .setTitle('Member Timed Out')
            .setColor('#2B2D31')
            .addFields([
                { name: 'User', value: targetUser.tag, inline: true },
                { name: 'Moderator', value: interaction.user.tag, inline: true },
                { name: 'Duration', value: `${duration} minutes`, inline: true },
                { name: 'Reason', value: reason }
            ])
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        await member.timeout(duration * 60 * 1000, reason);
        await interaction.reply({ embeds: [embed] });
    }
}; 