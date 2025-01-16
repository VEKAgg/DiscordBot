module.exports = {
    name: 'ship',
    description: 'Show compatibility between two users.',
    args: true,
    usage: '<@user1> <@user2>',
    execute(message, args) {
      const user1 = message.mentions.users.first();
      const user2 = message.mentions.users.last();
  
      if (!user1 || !user2 || user1.id === user2.id) {
        return message.reply('Please mention two different users.');
      }
  
      const compatibility = Math.floor(Math.random() * 101); // 0 to 100%
      const comment =
        compatibility > 75
          ? 'Perfect match! ❤️'
          : compatibility > 50
          ? 'Good match! 💛'
          : compatibility > 25
          ? 'Could work with effort. 🤔'
          : 'Not a match. 💔';
  
      message.channel.send(
        `${user1.username} ❤️ ${user2.username}: ${compatibility}% compatible. ${comment}`
      );
    },
  };
  