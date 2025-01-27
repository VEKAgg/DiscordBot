const { EmbedBuilder, SlashCommandBuilder } = require('discord.js');

module.exports = {
    name: 'help',
    description: 'Shows command information',
    category: 'utility',
    slashCommand: new SlashCommandBuilder()
        .setName('help')
        .setDescription('Get information about commands')
        .addStringOption(option =>
            option.setName('command')
                .setDescription('Specific command to get help for')
                .setRequired(false)),

    async execute(interaction) {
        const isSlash = interaction.commandName !== undefined;
        const commandName = isSlash ? interaction.options.getString('command') : null;
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
                .setDescription(command.description || 'No description available')
                .setColor('#0099ff')
                .addFields([
                    { name: 'Category', value: command.category || 'None', inline: true },
                    { name: 'Usage', value: command.usage || 'No usage specified', inline: true }
                ]);

            return interaction.reply({ embeds: [embed] });
        }

        // Group commands by category
        const categories = {};
        commands.forEach(cmd => {
            const category = cmd.category || 'Miscellaneous';
            if (!categories[category]) categories[category] = [];
            categories[category].push(cmd.name);
        });

        const embed = new EmbedBuilder()
            .setTitle('Command Help')
            .setDescription('Use `/help <command>` for detailed information about a specific command.')
            .setColor('#0099ff');

        Object.entries(categories).forEach(([category, cmds]) => {
            embed.addFields({
                name: category,
                value: cmds.map(cmd => `\`${cmd}\``).join(', ')
            });
        });

        return interaction.reply({ embeds: [embed] });
    }
};