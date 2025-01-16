module.exports = {
    name: 'hack',
    description: 'Pretend to hack a user for fun.',
    args: true,
    usage: '<@user>',
    execute(message, args) {
      const userToHack = message.mentions.users.first();
  
      if (!userToHack) {
        return message.reply('Please mention a user to hack.');
      }
  
      message.channel.send(`Hacking ${userToHack.username}...`).then(async (msg) => {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        await msg.edit('Fetching IP address...');
        await new Promise((resolve) => setTimeout(resolve, 2000));
        await msg.edit('Stealing credentials...');
        await new Promise((resolve) => setTimeout(resolve, 2000));
        await msg.edit(`Hack complete! Just kidding. Don't hack people 😄`);
      });
    },
  };
  