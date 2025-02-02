const { SlashCommandBuilder, EmbedBuilder } = require('discord.js');

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
        try {
            const commands = interaction.client.commands;
            const category = interaction.options?.getString('category')?.toLowerCase();
            
            let filteredCommands = [...commands.values()];
            if (category) {
                filteredCommands = filteredCommands.filter(cmd => cmd.category?.toLowerCase() === category);
            }

            // Split commands into multiple embeds if needed
            const embedFields = [];
            const categorizedCommands = {};

            // Group commands by category
            filteredCommands.forEach(cmd => {
                const cat = cmd.category || 'Uncategorized';
                if (!categorizedCommands[cat]) categorizedCommands[cat] = [];
                categorizedCommands[cat].push(cmd);
            });

            // Create fields with length checking
            for (const [category, cmds] of Object.entries(categorizedCommands)) {
                let fieldValue = '';
                let currentField = {
                    name: category.charAt(0).toUpperCase() + category.slice(1),
                    value: '',
                    inline: false
                };

                cmds.forEach(cmd => {
                    const commandText = `\`/${cmd.name}\` - ${cmd.description}\n`;
                    if (currentField.value.length + commandText.length > 1024) {
                        // If adding this command would exceed limit, create new field
                        embedFields.push({ ...currentField });
                        currentField.name = `${category} (continued)`;
                        currentField.value = '';
                    }
                    currentField.value += commandText;
                });

                if (currentField.value) {
                    embedFields.push({ ...currentField });
                }
            }

            // Create embed
            const embed = new EmbedBuilder()
                .setTitle('📚 Available Commands')
                .setDescription(category ? `Showing ${category} commands` : 'All available commands')
                .setColor(0x0099ff);

            // Add fields to embed, creating new embeds if needed
            const embeds = [];
            let currentEmbed = embed;
            let currentFieldCount = 0;

            embedFields.forEach(field => {
                if (currentFieldCount >= 25) { // Discord's limit is 25 fields per embed
                    embeds.push(currentEmbed);
                    currentEmbed = new EmbedBuilder()
                        .setTitle('📚 Available Commands (Continued)')
                        .setColor(0x0099ff);
                    currentFieldCount = 0;
                }
                currentEmbed.addFields(field);
                currentFieldCount++;
            });

            embeds.push(currentEmbed);

            // Send response
            await interaction.reply({
                embeds: embeds,
                ephemeral: true
            });
        } catch (error) {
            console.error('Error in help command:', error);
            await interaction.reply({
                content: 'There was an error executing this command.',
                ephemeral: true
            }).catch(console.error);
        }
    }
}; 