const { logger } = require('../utils/logger');

module.exports = {
    name: 'guildMemberUpdate',
    async execute(oldMember, newMember) {
        const boostedRole = newMember.guild.roles.cache.find(role => role.name === 'Server Booster');
        const hasBoosted = newMember.roles.cache.has(boostedRole.id);

        if (hasBoosted && !oldMember.roles.cache.has(boostedRole.id)) {
            const boostCount = newMember.premiumSince ? newMember.premiumSince : 0; // Adjust this logic as needed
            await newMember.send(`Thank you for boosting the server! You've boosted ${boostCount} times.`);
            logger.info(`Thanked ${newMember.user.tag} for boosting.`);
        }
    }
}; 