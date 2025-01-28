const { Client } = require('discord.js');
const { logger } = require('./logger');

async function massDMUsers(client, message) {
    const guilds = client.guilds.cache;

    for (const guild of guilds.values()) {
        const members = await guild.members.fetch();

        for (const member of members.values()) {
            if (!member.user.bot) {
                await sendDM(member.user, message);
                await delay(1000); // Delay to respect rate limits (1 second)
            }
        }
    }
}

async function sendDM(user, message) {
    try {
        await user.send(message);
        logger.info(`Mass DM sent to ${user.tag}`);
    } catch (error) {
        logger.error(`Failed to send mass DM to ${user.tag}:`, error);
    }
}

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

module.exports = { massDMUsers }; 