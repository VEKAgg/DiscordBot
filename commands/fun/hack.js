const { EmbedBuilder } = require('discord.js');

module.exports = {
    name: 'hack',
    description: 'Pretend to hack a user for fun',
    async execute(message, args) {
        const target = message.mentions.users.first();
        if (!target) {
            return message.reply('Please mention a user to "hack"!');
        }

        if (target.bot) {
            return message.reply('Nice try, but you can\'t hack a bot! 🤖');
        }

        const hackStages = [
            { text: '🔍 Initializing hack.exe...', time: 1000 },
            { text: '🔓 Getting user token...', time: 1500 },
            { text: '📱 Accessing device...', time: 2000 },
            { text: '📧 Retrieving emails...', time: 1500 },
            { text: '🔑 Decoding passwords...', time: 2000 },
            { text: '💾 Downloading personal files...', time: 1800 },
            { text: '🌐 Accessing social media...', time: 1700 },
            { text: '📸 Finding embarrassing photos...', time: 2000 },
            { text: '💰 Accessing bank details...', time: 1900 }
        ];

        const embed = new EmbedBuilder()
            .setTitle('👨‍💻 Hacking in Progress')
            .setDescription(`Target: ${target.tag}`)
            .setColor('#FF0000')
            .setFooter({ text: 'This is a joke command for entertainment purposes only' });

        const hackMessage = await message.channel.send({ embeds: [embed] });

        for (const stage of hackStages) {
            embed.addFields({ name: 'Status', value: stage.text });
            await new Promise(resolve => setTimeout(resolve, stage.time));
            await hackMessage.edit({ embeds: [embed] });
        }

        // Generate funny fake data
        const fakeEmail = `${target.username.toLowerCase()}${Math.floor(Math.random() * 100)}@definitely-real-email.com`;
        const fakePassword = 'definitely_not_password123';
        const fakeIp = `${Math.floor(Math.random() * 255)}.${Math.floor(Math.random() * 255)}.${Math.floor(Math.random() * 255)}.${Math.floor(Math.random() * 255)}`;
        const fakeBankBalance = `$${(Math.random() * 1000).toFixed(2)}`;

        const finalEmbed = new EmbedBuilder()
            .setTitle('✅ Hack Complete!')
            .setDescription(`Successfully "hacked" ${target.tag}`)
            .addFields([
                { name: '📧 Email', value: `||${fakeEmail}||`, inline: true },
                { name: '🔑 Password', value: `||${fakePassword}||`, inline: true },
                { name: '🌐 IP Address', value: `||${fakeIp}||`, inline: true },
                { name: '💰 Bank Balance', value: `||${fakeBankBalance}||`, inline: true },
                { name: '📱 Most Used Emoji', value: '||🤡||', inline: true },
                { name: '🔍 Browser History', value: '||"how to be cool online"||', inline: true }
            ])
            .setColor('#00FF00')
            .setFooter({ text: 'This was a joke hack! No actual hacking occurred.' })
            .setTimestamp();

        await hackMessage.edit({ embeds: [finalEmbed] });
    },
};
  