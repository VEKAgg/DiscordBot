const { EmbedBuilder } = require('discord.js');

module.exports = {
    name: 'mock',
    description: 'Mock text by alternating capitalization and adding emojis',
    execute(message, args) {
        if (!args.length) {
            return message.reply('Please provide text to mock. Example: `#mock hello there`');
        }

        const input = args.join(' ');
        const mockedText = mockText(input);
        const spongebobUrl = 'https://i.imgur.com/cIBCUzN.png';

        const embed = new EmbedBuilder()
            .setTitle('🤪 Mocking Generator')
            .setDescription(mockedText)
            .setThumbnail(spongebobUrl)
            .addFields([
                { 
                    name: 'Original Text', 
                    value: `||${input}||`, 
                    inline: false 
                },
                { 
                    name: 'Character Count', 
                    value: `${mockedText.length} characters`, 
                    inline: true 
                },
                { 
                    name: 'Word Count', 
                    value: `${input.split(' ').length} words`, 
                    inline: true 
                }
            ])
            .setColor('#FF9900')
            .setFooter({ text: 'Inspired by the Mocking SpongeBob meme' })
            .setTimestamp();

        message.channel.send({ embeds: [embed] });
    },
};

function mockText(text) {
    let mocked = '';
    let capitalize = true;

    for (const char of text) {
        if (/[a-zA-Z]/.test(char)) {
            mocked += capitalize ? char.toUpperCase() : char.toLowerCase();
            capitalize = !capitalize;
        } else {
            mocked += char;
        }
    }

    // Add random mocking emojis
    const mockEmojis = ['🤪', '🥴', '😜', '🙃', '😏'];
    const numEmojis = Math.min(3, Math.floor(text.length / 10));
    
    for (let i = 0; i < numEmojis; i++) {
        const randomEmoji = mockEmojis[Math.floor(Math.random() * mockEmojis.length)];
        mocked += ` ${randomEmoji}`;
    }

    return mocked;
}
