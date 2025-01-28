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
        const isSlash = interaction.commandName !== undefined;
        
        const embed = new EmbedBuilder()
            .setTitle('Bot Information')
            .setColor('#0099ff')
            .addFields([
                { name: 'Bot Version', value: version, inline: true },
                { name: 'Discord.js', value: discordVersion, inline: true },
                { name: 'Node.js', value: process.version, inline: true },
                { name: 'Platform', value: os.platform(), inline: true },
                { name: 'Memory Usage', value: `${Math.round(process.memoryUsage().heapUsed / 1024 / 1024)}MB`, inline: true },
                { name: 'Uptime', value: `${Math.round(process.uptime() / 60 / 60)}h`, inline: true }
            ])
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` })
            .setTimestamp();

        const reply = { embeds: [embed] };
        if (isSlash) {
            await interaction.reply(reply);
        } else {
            await interaction.channel.send(reply);
        }
    },

    async setupDashboard(message) {
        const channel = message.mentions.channels.first() || message.channel;
        await DashboardConfig.findOneAndUpdate(
            { guildId: message.guild.id },
            { channelId: channel.id },
            { upsert: true }
        );
        message.reply(`Dashboard will be displayed in ${channel}`);
    },

    async setupAnalytics(message) {
        const config = await AnalyticsConfig.findOneAndUpdate(
            { guildId: message.guild.id },
            { enabled: true },
            { upsert: true, new: true }
        );
        message.reply('Analytics system has been enabled for this server.');
    }
};
