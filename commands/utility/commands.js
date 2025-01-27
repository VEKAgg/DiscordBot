const { EmbedBuilder, SlashCommandBuilder } = require('discord.js');

module.exports = {
    name: 'commands',
    description: 'Shows available commands',
    category: 'utility',
    slashCommand: new SlashCommandBuilder()
        .setName('commands')
        .setDescription('Shows all available commands'),

    async execute(interaction) {
        const isSlash = interaction.commandName !== undefined;
        const client = isSlash ? interaction.client : interaction.client;

        const categories = {
            '🛠️ Core': [],
            '⚙️ Utility': [],
            '📊 Admin': [],
            'ℹ️ Info': [],
            '🎮 Fun': []
        };

        client.commands.forEach(cmd => {
            const category = cmd.category || 'Uncategorized';
            if (categories[category]) {
                categories[category].push(cmd.name);
            }
        });

        const embed = new EmbedBuilder()
            .setTitle('Available Commands')
            .setDescription('Use `/help [command]` for detailed information about a specific command.')
            .setColor('#2B2D31');

        Object.entries(categories).forEach(([category, commands]) => {
            if (commands.length > 0) {
                embed.addFields({
                    name: category,
                    value: commands.map(cmd => `\`${cmd}\``).join(' ')
                });
            }
        });

        const reply = { embeds: [embed] };
        if (isSlash) {
            await interaction.reply(reply);
        } else {
            await interaction.channel.send(reply);
        }
    }
};
