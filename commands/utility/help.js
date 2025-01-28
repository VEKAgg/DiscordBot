const { EmbedBuilder, SlashCommandBuilder } = require('discord.js');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'help',
    description: 'Shows command information',
    category: 'utility',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    slashCommand: new SlashCommandBuilder()
        .setName('help')
        .setDescription('Get information about commands')
        .addStringOption(option =>
            option.setName('command')
                .setDescription('Specific command to get help for')
                .setRequired(false)),

    async execute(interaction) {
        const commandName = interaction.options.getString('command');
        const commands = interaction.client.commands;

        if (commandName) {
            const command = commands.get(commandName);
            if (!command) {
                return interaction.reply({
                    content: 'That command does not exist!',
                    ephemeral: true
                });
            }

            const embed = new EmbedBuilder()
                .setTitle(`Command: ${command.name}`)
                .setColor('#2B2D31')
                .addFields([
                    { name: 'Description', value: command.description || 'No description available' },
                    { name: 'Category', value: command.category || 'Uncategorized' },
                    { name: 'Usage', value: command.usage || `/${command.name}` }
                ])
                .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

            return interaction.reply({ embeds: [embed] });
        }

        const categories = {};
        commands.forEach(cmd => {
            const category = cmd.category || 'Uncategorized';
            if (!categories[category]) categories[category] = [];
            categories[category].push(cmd.name);
        });

        const embed = new EmbedBuilder()
            .setTitle('Command Help')
            .setDescription('Use `/help <command>` for detailed information about a specific command')
            .setColor('#2B2D31')
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        Object.entries(categories).forEach(([category, cmds]) => {
            embed.addFields({
                name: category,
                value: cmds.map(cmd => `\`${cmd}\``).join(', ')
            });
        });

        await interaction.reply({ embeds: [embed] });
    }
};