const { EmbedBuilder } = require('discord.js');

module.exports = {
    name: 'ship',
    description: 'Show compatibility between two users',
    async execute(message, args) {
        const user1 = message.mentions.users.first();
        const user2 = message.mentions.users.last();

        if (!user1 || !user2 || user1.id === user2.id) {
            return message.reply('Please mention two different users.');
        }

        // Generate a consistent compatibility score based on user IDs
        const seed = parseInt(user1.id.slice(-4) + user2.id.slice(-4));
        const compatibility = seed % 101; // 0 to 100%

        let comment, color, emoji;
        if (compatibility > 90) {
            comment = 'Soulmates! A match made in heaven! 💘';
            color = '#FF69B4';
            emoji = '👰🤵';
        } else if (compatibility > 75) {
            comment = 'Perfect match! Love is in the air! ❤️';
            color = '#FF0000';
            emoji = '💑';
        } else if (compatibility > 50) {
            comment = 'Good match! There\'s potential here! 💛';
            color = '#FFA500';
            emoji = '💕';
        } else if (compatibility > 25) {
            comment = 'Could work with some effort... 🤔';
            color = '#FFD700';
            emoji = '🤝';
        } else {
            comment = 'Better off as friends... 💔';
            color = '#808080';
            emoji = '🥶';
        }

        const progressBar = createProgressBar(compatibility);
        const embed = new EmbedBuilder()
            .setTitle(`${emoji} Love Calculator ${emoji}`)
            .setDescription(`Calculating love between ${user1} and ${user2}...`)
            .addFields([
                { name: 'Compatibility Score', value: `${progressBar} ${compatibility}%`, inline: false },
                { name: 'Verdict', value: comment, inline: false }
            ])
            .setColor(color)
            .setFooter({ text: `Requested by ${message.author.tag}` })
            .setTimestamp();

        message.channel.send({ embeds: [embed] });
    },
};

function createProgressBar(percentage) {
    const filled = Math.round(percentage / 10);
    const empty = 10 - filled;
    return '❤️'.repeat(filled) + '��'.repeat(empty);
}
  