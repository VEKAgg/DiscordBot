const { EmbedBuilder } = require('discord.js');

module.exports = {
    name: 'howgay',
    description: 'Find out how "gay" someone is (for humor)',
    execute(message, args) {
        const target = message.mentions.users.first() || message.author;
        
        // Generate consistent percentage based on user ID
        const seed = parseInt(target.id.slice(-4));
        const percentage = seed % 101;

        let comment, color;
        if (percentage > 80) {
            comment = '🌈 YAAAS QUEEN! Slaying the gay game! 💅';
            color = '#FF1493';
        } else if (percentage > 60) {
            comment = '🏳️‍🌈 Living that fabulous life! ✨';
            color = '#FF69B4';
        } else if (percentage > 40) {
            comment = '🌟 Keeping it rainbow casual! 🌈';
            color = '#FFA500';
        } else if (percentage > 20) {
            comment = '🤔 Just a tiny bit fruity! 🍎';
            color = '#98FB98';
        } else {
            comment = '😴 Straight as a ruler! 📏';
            color = '#87CEEB';
        }

        const progressBar = createProgressBar(percentage);
        const embed = new EmbedBuilder()
            .setTitle('🏳️‍🌈 Gay-O-Meter 3000')
            .setDescription(`Analyzing ${target.username}'s gay levels...`)
            .addFields([
                { name: 'Gay Level', value: `${progressBar} ${percentage}%`, inline: false },
                { name: 'Verdict', value: comment, inline: false }
            ])
            .setColor(color)
            .setFooter({ text: 'This is a joke command for entertainment purposes only!' })
            .setTimestamp();

        message.channel.send({ embeds: [embed] });
    },
};

function createProgressBar(percentage) {
    const filled = Math.round(percentage / 10);
    const empty = 10 - filled;
    return '🌈'.repeat(filled) + '⬜'.repeat(empty);
}
  