const { EmbedBuilder, SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'kick',
    description: 'Kick a member from the server',
    category: 'admin',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    permissions: [PermissionFlagsBits.KickMembers],
    slashCommand: new SlashCommandBuilder()
        .setName('kick')
        .setDescription('Kick a member from the server')
        .setDefaultMemberPermissions(PermissionFlagsBits.KickMembers)
        .addUserOption(option =>
            option.setName('user')
                .setDescription('User to kick')
                .setRequired(true))
        .addStringOption(option =>
            option.setName('reason')
                .setDescription('Reason for kicking')
                .setRequired(false)),

    async execute(interaction) {
        const targetUser = interaction.options.getUser('user');
        const reason = interaction.options.getString('reason') || 'No reason provided';
        const member = await interaction.guild.members.fetch(targetUser.id);

        if (!member.kickable) {
            return interaction.reply({
                content: 'I cannot kick this user. They may have higher permissions than me.',
                ephemeral: true
            });
        }

        const embed = new EmbedBuilder()
            .setTitle('Member Kicked')
            .setColor('#2B2D31')
            .addFields([
                { name: 'User', value: targetUser.tag, inline: true },
                { name: 'Moderator', value: interaction.user.tag, inline: true },
                { name: 'Reason', value: reason }
            ])
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        await member.kick(reason);
        await interaction.reply({ embeds: [embed] });
    }
}; 