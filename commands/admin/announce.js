const { EmbedBuilder, SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'announce',
    description: 'Make an announcement',
    category: 'admin',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    permissions: [PermissionFlagsBits.ManageMessages],
    slashCommand: new SlashCommandBuilder()
        .setName('announce')
        .setDescription('Make an announcement')
        .setDefaultMemberPermissions(PermissionFlagsBits.ManageMessages)
        .addStringOption(option =>
            option.setName('title')
                .setDescription('Title of the announcement')
                .setRequired(true))
        .addStringOption(option =>
            option.setName('message')
                .setDescription('Content of the announcement')
                .setRequired(true))
        .addChannelOption(option =>
            option.setName('channel')
                .setDescription('Channel to send the announcement to')
                .setRequired(false)),

    async execute(interaction) {
        const title = interaction.options.getString('title');
        const message = interaction.options.getString('message');
        const channel = interaction.options.getChannel('channel') || interaction.channel;

        const embed = new EmbedBuilder()
            .setTitle(title)
            .setDescription(message)
            .setColor('#2B2D31')
            .setTimestamp()
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        await channel.send({ embeds: [embed] });
        await interaction.reply({
            content: `Announcement sent to ${channel}`,
            ephemeral: true
        });
    }
}; 