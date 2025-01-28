const { EmbedBuilder, SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'unban',
    description: 'Unban a user from the server',
    category: 'admin',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    permissions: [PermissionFlagsBits.BanMembers],
    slashCommand: new SlashCommandBuilder()
        .setName('unban')
        .setDescription('Unban a user from the server')
        .setDefaultMemberPermissions(PermissionFlagsBits.BanMembers)
        .addStringOption(option =>
            option.setName('userid')
                .setDescription('ID of the user to unban')
                .setRequired(true)),

    async execute(interaction) {
        const userId = interaction.options.getString('userid');

        try {
            const bans = await interaction.guild.bans.fetch();
            const bannedUser = bans.get(userId);

            if (!bannedUser) {
                return interaction.reply({
                    content: 'This user is not banned.',
                    ephemeral: true
                });
            }

            const embed = new EmbedBuilder()
                .setTitle('User Unbanned')
                .setColor('#2B2D31')
                .addFields([
                    { name: 'User', value: bannedUser.user.tag, inline: true },
                    { name: 'Moderator', value: interaction.user.tag, inline: true }
                ])
                .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

            await interaction.guild.members.unban(userId);
            await interaction.reply({ embeds: [embed] });
        } catch (error) {
            return interaction.reply({
                content: 'There was an error trying to unban this user.',
                ephemeral: true
            });
        }
    }
}; 