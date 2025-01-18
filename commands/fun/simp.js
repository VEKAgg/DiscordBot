const { EmbedBuilder } = require('discord.js');

module.exports = {
    name: 'simp',
    description: 'Randomly determine how much of a simp someone is',
    execute(message, args) {
        const target = message.mentions.users.first() || message.author;
        
        // Generate consistent percentage based on user ID
        const seed = parseInt(target.id.slice(-4));
        const percentage = seed % 101;

        let comment, color, emoji;
        if (percentage > 80) {
            comment = 'ULTIMATE SIMP! Donating their life savings to streamers! 💸';
            color = '#FF69B4';
            emoji = '🥵';
        } else if (percentage > 60) {
            comment = 'Major simp energy! Probably has a folder of saved Instagram posts! 📱';
            color = '#FF1493';
            emoji = '😍';
        } else if (percentage > 40) {
            comment = 'Moderate simping detected! Occasionally drops a Super Chat! 💝';
            color = '#FFA500';
            emoji = '🤗';
        } else if (percentage > 20) {
            comment = 'Light simping! Just likes every post! 👍';
            color = '#98FB98';
            emoji = '😊';
        } else {
            comment = 'No simp detected! Sigma grindset activated! 😎';
            color = '#87CEEB';
            emoji = '💪';
        }

        const progressBar = createProgressBar(percentage);
        const embed = new EmbedBuilder()
            .setTitle(`${emoji} Simp Calculator 9000`)
            .setDescription(`Analyzing ${target.username}'s simp levels...`)
            .addFields([
                { name: 'Simp Level', value: `${progressBar} ${percentage}%`, inline: false },
                { name: 'Verdict', value: comment, inline: false },
                { name: 'Symptoms', value: getSimpSymptoms(percentage), inline: false }
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
    return '💝'.repeat(filled) + '⬜'.repeat(empty);
}

function getSimpSymptoms(percentage) {
    const symptoms = [
        'Excessive use of heart emojis',
        'Donating to streamers',
        'Always replies within seconds',
        'Says "sorry" too much',
        'Likes every single post'
    ];
    
    const count = Math.ceil(percentage / 20);
    return symptoms.slice(0, count).map(s => `• ${s}`).join('\n') || 'No symptoms detected!';
}
  