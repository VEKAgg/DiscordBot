const { createEmbed } = require('../../utils/embedUtils');

module.exports = {
    name: 'cakeday',
    description: 'Celebrate your Discord account anniversary!',
    execute(message, args, client) {
        const createdAt = message.author.createdAt;
        const today = new Date();
        const nextCakeday = new Date(createdAt);

        nextCakeday.setFullYear(today.getFullYear());
        if (nextCakeday < today) {
            nextCakeday.setFullYear(today.getFullYear() + 1);
        }

        const timeUntilCakeday = nextCakeday - today;
        const daysLeft = Math.ceil(timeUntilCakeday / (1000 * 60 * 60 * 24));

        if (daysLeft === 0) {
            message.channel.send({
                embeds: [createEmbed('🎉 Happy Cakeday! 🎂', `It's your Discord account's anniversary!`, 'GREEN')],
            });
        } else {
            message.channel.send({
                embeds: [
                    createEmbed(
                        '🎂 Cakeday Countdown',
                        `Your next Discord account anniversary is in **${daysLeft} days**.`,
                        'ORANGE',
                    ),
                ],
            });
        }
    },
};
