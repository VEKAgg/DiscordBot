const { Client, GatewayIntentBits, Collection } = require('discord.js');
const fs = require('fs');
require('dotenv').config();
const schedule = require('node-schedule');
const { runBackgroundChecks } = require('./utils/backgroundMonitor');
const config = require('./config');
const { logger } = require('./utils/logger');

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
    GatewayIntentBits.GuildMembers,
    GatewayIntentBits.GuildVoiceStates
  ],
});

client.commands = new Collection();

// Increase max event listeners
require('events').EventEmitter.defaultMaxListeners = config.maxListeners;

// Load commands
const loadCommands = (dir) => {
  const commandFiles = fs.readdirSync(dir).filter((file) => file.endsWith('.js'));
  for (const file of commandFiles) {
    logger.info(`Loading command: ${file}`);
    const command = require(`${dir}/${file}`);
    client.commands.set(command.name, command);
  }

  const subfolders = fs.readdirSync(dir).filter((folder) => fs.lstatSync(`${dir}/${folder}`).isDirectory());
  for (const subfolder of subfolders) {
    loadCommands(`${dir}/${subfolder}`);
  }
};

loadCommands('./commands');

// Load events
const eventFiles = fs.readdirSync('./events').filter((file) => file.endsWith('.js'));
for (const file of eventFiles) {
  logger.info(`Loading event: ${file}`);
  const event = require(`./events/${file}`);
  if (event.once) {
    client.once(event.name, (...args) => event.execute(...args, client));
  } else {
    client.on(event.name, (...args) => event.execute(...args, client));
  }
}

// Add error event handlers
client.on('error', (error) => {
  logger.error('Client error:', error);
});

process.on('unhandledRejection', (error) => {
  logger.error('Unhandled rejection:', error);
});

// Login the bot
client.login(process.env.TOKEN).then(() => {
  logger.info('Bot successfully logged in');
}).catch((error) => {
  logger.error('Failed to log in:', error.message);
  console.error('Check your token and internet connection');
});

client.points = new Map();

client.once('ready', async () => {
  logger.info(`Logged in as ${client.user.tag}!`);

  // Start background monitoring
  runBackgroundChecks(client);

  // Set initial presence
  client.user.setPresence({
    activities: [{ 
      name: config.richPresence.activities[0].name,
      type: config.richPresence.activities[0].type
    }],
    status: config.richPresence.status
  });

  // Set Bio
  try {
    const app = await client.application.fetch();
    await app.edit({
      description: config.botDescription,
    });
    logger.info('Bot bio updated successfully.');
  } catch (error) {
    logger.error('Failed to update bot bio:', error);
  }

  // Schedule periodic tasks
  schedule.scheduleJob(config.scheduledTaskCron, () => {
    logger.info('Scheduled task executed.');
  });

  logger.info('Bot is ready!');
});
