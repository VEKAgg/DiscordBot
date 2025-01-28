const { EmbedBuilder, SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'clear',
    description: 'Clear user warnings',
    category: 'admin',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    permissions: [PermissionFlagsBits.ModerateMembers],
    slashCommand: new SlashCommandBuilder()
        .setName('clear')
        .setDescription('Clear user warnings')
        .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers)
        .addUserOption(option =>
            option.setName('user')
                .setDescription('User to clear warnings for')
                .setRequired(true)),

    async execute(interaction) {
        const targetUser = interaction.options.getUser('user');
        const userData = await User.findOne({ userId: targetUser.id, guildId: interaction.guildId });

        if (!userData || userData.warnings.length === 0) {
            return interaction.reply({
                content: 'This user has no warnings to clear.',
                ephemeral: true
            });
        }

        const warningCount = userData.warnings.length;
        userData.warnings = [];
        await userData.save();

        const embed = new EmbedBuilder()
            .setTitle('Warnings Cleared')
            .setColor('#2B2D31')
            .addFields([
                { name: 'User', value: targetUser.tag, inline: true },
                { name: 'Moderator', value: interaction.user.tag, inline: true },
                { name: 'Warnings Cleared', value: warningCount.toString(), inline: true }
            ])
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        await interaction.reply({ embeds: [embed] });
    }
}; 