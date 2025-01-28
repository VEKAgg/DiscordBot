const { Client } = require('discord.js');
const { logger } = require('./logger');

async function dmInactiveUsers(client) {
    const guilds = client.guilds.cache;

    for (const guild of guilds.values()) {
        const members = await guild.members.fetch();
        const now = Date.now();
        const fifteenDaysInMillis = 15 * 24 * 60 * 60 * 1000;

        members.forEach(member => {
            if (!member.user.bot && !member.presence) {
                const lastMessage = member.lastMessage ? member.lastMessage.createdTimestamp : 0;
                if (now - lastMessage > fifteenDaysInMillis) {
                    sendDM(member.user);
                }
            }
        });
    }
}

async function sendDM(user) {
    try {
        await user.send("Hey! We noticed you haven't been active in the server for a while. Is everything okay? We'd love to hear your feedback or any issues you might have.");
        logger.info(`DM sent to ${user.tag}`);
    } catch (error) {
        logger.error(`Failed to send DM to ${user.tag}:`, error);
    }
}

module.exports = { dmInactiveUsers }; 