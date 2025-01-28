const { EmbedBuilder, SlashCommandBuilder } = require('discord.js');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'about',
    description: 'Shows information about the bot and its contributors',
    category: 'informational',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    slashCommand: new SlashCommandBuilder()
        .setName('about')
        .setDescription('Shows information about the bot and its contributors'),

    async execute(interaction) {
        const embed = new EmbedBuilder()
            .setTitle('About VEKA Bot')
            .setColor('#2B2D31')
            .setDescription('A multipurpose Discord bot with advanced analytics, leveling, and server management features.')
            .addFields([
                { 
                    name: 'Contributors',
                    value: [
                        '• TwistedVorteK - Lead Developer',
                        '• Sleepless - Developer',
                        '• Community Contributors'
                    ].join('\n')
                },
                {
                    name: 'Links',
                    value: [
                        '[GitHub Repository](https://github.com/VEKAgg/DiscordBot)',
                        '[Report Issues](https://github.com/VEKAgg/DiscordBot/issues)',
                        '[Support Server](https://discord.gg/veka)'
                    ].join('\n')
                }
            ])
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        await interaction.reply({ embeds: [embed] });
    }
}; 