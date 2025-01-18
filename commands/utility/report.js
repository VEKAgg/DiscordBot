const embedUtils = require('../../utils/embedUtils');

module.exports = {
    name: 'report',
    description: 'Report a user to the server admins.',
    args: true,
    usage: '<@user> <reason>',
    execute(message, args) {
      const userToReport = message.mentions.users.first();
      const reason = args.slice(1).join(' ');
  
      if (!userToReport) {
        return message.reply('Please mention the user you want to report.');
      }
  
      if (!reason) {
        return message.reply('Please provide a reason for the report.');
      }
  
      const reportChannel = message.guild.channels.cache.find(
        (channel) => channel.name === 'reports' || channel.name.includes('report')
      );
  
      if (!reportChannel) {
        return message.reply(
          'No reports channel found. Please inform a server admin to set one up.'
        );
      }
  
      const reportMessage = `**Report**\n**User:** ${userToReport.tag}\n**Reported by:** ${message.author.tag}\n**Reason:** ${reason}`;
      reportChannel.send(reportMessage);
  
      message.reply('Your report has been submitted. Thank you!');
    },
  };
  