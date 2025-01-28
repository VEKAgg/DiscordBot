const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'purge',
    description: 'Delete multiple messages at once',
    category: 'admin',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    permissions: [PermissionFlagsBits.ManageMessages],
    slashCommand: new SlashCommandBuilder()
        .setName('purge')
        .setDescription('Delete multiple messages at once')
        .setDefaultMemberPermissions(PermissionFlagsBits.ManageMessages)
        .addIntegerOption(option =>
            option.setName('amount')
                .setDescription('Number of messages to delete (1-100)')
                .setRequired(true)
                .setMinValue(1)
                .setMaxValue(100)),

    async execute(interaction) {
        const amount = interaction.options.getInteger('amount');

        try {
            const deleted = await interaction.channel.bulkDelete(amount, true);
            await interaction.reply({
                content: `Successfully deleted ${deleted.size} messages.`,
                ephemeral: true
            });
        } catch (error) {
            await interaction.reply({
                content: 'There was an error trying to delete messages in this channel!',
                ephemeral: true
            });
        }
    }
}; 