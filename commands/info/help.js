const { SlashCommandBuilder } = require('discord.js');

module.exports = {
    name: 'help',
    description: 'Shows all available commands',
    category: 'info',
    slashCommand: new SlashCommandBuilder()
        .setName('help')
        .setDescription('Shows all available commands')
        .addStringOption(option =>
            option.setName('category')
                .setDescription('Command category to show')
                .setRequired(false)
                .addChoices(
                    { name: 'Admin', value: 'admin' },
                    { name: 'Info', value: 'info' },
                    { name: 'Utility', value: 'utility' }
                )),

    async execute(interaction) {
        const commands = interaction.client.commands;
        const category = interaction.options.getString('category')?.toLowerCase();
        
        let filteredCommands = [...commands.values()];
        if (category) {
            filteredCommands = filteredCommands.filter(cmd => cmd.category?.toLowerCase() === category);
        }

        const embed = {
            title: '📚 Available Commands',
            description: category ? `Showing ${category} commands` : 'All available commands',
            fields: [],
            color: 0x0099ff
        };

        const categorizedCommands = filteredCommands.reduce((acc, cmd) => {
            const cat = cmd.category || 'Uncategorized';
            if (!acc[cat]) acc[cat] = [];
            acc[cat].push(cmd);
            return acc;
        }, {});

        for (const [category, cmds] of Object.entries(categorizedCommands)) {
            embed.fields.push({
                name: category.charAt(0).toUpperCase() + category.slice(1),
                value: cmds.map(cmd => `\`/${cmd.name}\` - ${cmd.description}`).join('\n') || 'No commands available',
                inline: false
            });
        }

        await interaction.reply({ embeds: [embed], ephemeral: true });
    }
}; 