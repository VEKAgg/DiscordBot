const { EmbedBuilder, SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'ban',
    description: 'Ban a member from the server',
    category: 'admin',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    permissions: [PermissionFlagsBits.BanMembers],
    slashCommand: new SlashCommandBuilder()
        .setName('ban')
        .setDescription('Ban a member from the server')
        .setDefaultMemberPermissions(PermissionFlagsBits.BanMembers)
        .addUserOption(option =>
            option.setName('user')
                .setDescription('User to ban')
                .setRequired(true))
        .addStringOption(option =>
            option.setName('reason')
                .setDescription('Reason for banning')
                .setRequired(false))
        .addIntegerOption(option =>
            option.setName('days')
                .setDescription('Number of days of messages to delete')
                .setRequired(false)
                .setMinValue(0)
                .setMaxValue(7)),

    async execute(interaction) {
        const targetUser = interaction.options.getUser('user');
        const reason = interaction.options.getString('reason') || 'No reason provided';
        const days = interaction.options.getInteger('days') || 0;
        const member = await interaction.guild.members.fetch(targetUser.id);

        if (!member.bannable) {
            return interaction.reply({
                content: 'I cannot ban this user. They may have higher permissions than me.',
                ephemeral: true
            });
        }

        const embed = new EmbedBuilder()
            .setTitle('Member Banned')
            .setColor('#2B2D31')
            .addFields([
                { name: 'User', value: targetUser.tag, inline: true },
                { name: 'Moderator', value: interaction.user.tag, inline: true },
                { name: 'Reason', value: reason },
                { name: 'Message History Deleted', value: `${days} days`, inline: true }
            ])
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        await member.ban({ deleteMessageDays: days, reason: reason });
        await interaction.reply({ embeds: [embed] });
    }
};
