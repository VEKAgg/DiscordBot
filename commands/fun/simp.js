module.exports = {
    name: 'simp',
    description: 'Randomly determine how much of a simp someone is.',
    args: true,
    usage: '<@user>',
    execute(message, args) {
      const userToSimp = message.mentions.users.first() || message.author;
      const simpPercentage = Math.floor(Math.random() * 101); // 0 to 100%
  
      message.channel.send(
        `${userToSimp.username} is ${simpPercentage}% simp.`
      );
    },
  };
  