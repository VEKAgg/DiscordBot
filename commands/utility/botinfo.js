const { EmbedBuilder, SlashCommandBuilder, version: discordVersion } = require('discord.js');
const os = require('os');
const { version } = require('../../package.json');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'botinfo',
    description: 'Shows information about the bot',
    category: 'utility',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    slashCommand: new SlashCommandBuilder()
        .setName('botinfo')
        .setDescription('Shows information about the bot'),

    async execute(interaction) {
        const embed = new EmbedBuilder()
            .setTitle('Bot Information')
            .setColor('#2B2D31')
            .addFields([
                { name: 'Bot Version', value: version, inline: true },
                { name: 'Discord.js', value: discordVersion, inline: true },
                { name: 'Node.js', value: process.version, inline: true },
                { name: 'Platform', value: os.platform(), inline: true },
                { name: 'Memory Usage', value: `${Math.round(process.memoryUsage().heapUsed / 1024 / 1024)}MB`, inline: true },
                { name: 'Uptime', value: `${Math.round(process.uptime() / 60 / 60)}h`, inline: true }
            ])
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        await interaction.reply({ embeds: [embed] });
    },
};
