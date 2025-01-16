const afkUsers = new Map();

module.exports = {
  name: 'afk',
  description: 'Set yourself as AFK with an optional message.',
  args: false,
  execute(message, args) {
    const afkMessage = args.join(' ') || 'AFK';
    afkUsers.set(message.author.id, afkMessage);

    message.reply(`You are now AFK: ${afkMessage}`);

    message.client.on('messageCreate', (msg) => {
      if (afkUsers.has(msg.author.id)) {
        afkUsers.delete(msg.author.id);
        msg.reply('Welcome back! Your AFK status has been removed.');
      }

      if (msg.mentions.users.size > 0) {
        const mentionedAfkUsers = msg.mentions.users.filter((user) => afkUsers.has(user.id));
        mentionedAfkUsers.forEach((user) => {
          msg.reply(`${user.username} is AFK: ${afkUsers.get(user.id)}`);
        });
      }
    });
  },
};
