module.exports = {
    name: 'guildMemberAdd',
    execute(member) {
        member.send(`Welcome to the server, ${member.user.username}! 🎉`);
        const channel = member.guild.channels.cache.find(ch => ch.name === 'welcome');
        if (channel) {
            channel.send(`Everyone welcome ${member}! 🎉`);
        }
    },
};
