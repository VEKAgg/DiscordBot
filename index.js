const { Client, GatewayIntentBits, Collection, REST, Routes } = require('discord.js');
const CommandLoader = require('./utils/commandLoader');
require('dotenv').config();
const schedule = require('node-schedule');
const { runBackgroundChecks } = require('./utils/backgroundMonitor');
const config = require('./config');
const { logger } = require('./utils/logger');
const dbManager = require('./database/connection');
const { dmInactiveUsers } = require('./utils/userDM');
const { massDMUsers } = require('./utils/massDM');
const EventLoader = require('./utils/eventLoader');
const MonitoringService = require('./services/MonitoringService');
const { connectDB } = require('./database');

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
    GatewayIntentBits.GuildMembers,
    GatewayIntentBits.GuildPresences,
    GatewayIntentBits.GuildVoiceStates
  ],
});

client.commands = new Collection();
client.slashCommands = new Collection();

// Increase max event listeners
require('events').EventEmitter.defaultMaxListeners = config.maxListeners;

// Initialize command loader
const commandLoader = new CommandLoader(client);

// Load commands
(async () => {
    try {
        const stats = await commandLoader.loadCommands('./commands');
        logger.info(`Loaded ${stats.total} commands (${stats.slash} slash commands) in ${stats.categories} categories`);
    } catch (error) {
        logger.error('Failed to load commands:', error);
        process.exit(1);
    }
})();

// Initialize event loader
const eventLoader = new EventLoader(client);

// Load events
(async () => {
    try {
        const stats = await eventLoader.loadEvents('./events');
        logger.info(`Loaded ${stats.total} events: ${stats.names.join(', ')}`);
    } catch (error) {
        logger.error('Failed to load events:', error);
        process.exit(1);
    }
})();

// Add error event handlers
client.on('error', (error) => {
  logger.error('Client error:', error);
});

process.on('unhandledRejection', (error) => {
  logger.error('Unhandled rejection:', error);
});

// Connect to MongoDB before starting the bot
connectDB(process.env.MONGODB_URI)
    .then(() => {
        // Start the bot only after DB connection is established
        client.login(process.env.TOKEN);
    })
    .catch(error => {
        logger.error('Failed to start bot:', error);
        process.exit(1);
    });

client.points = new Map();

// Function to handle command execution
async function handleCommand(message, commandName, args) {
    const command = client.commands.get(commandName);
    if (!command) return;

    try {
        await command.execute(message, args);
    } catch (error) {
        logger.error(`Error executing ${commandName}:`, error);
        message.reply('There was an error executing that command.');
    }
}

// Message event handler
client.on('messageCreate', async message => {
    if (message.author.bot) return;

    let args;
    let commandName;

    // Check for bot mention
    if (message.content.startsWith(`<@${client.user.id}>`)) {
        args = message.content.slice(`<@${client.user.id}>`.length).trim().split(/ +/);
        commandName = args.shift().toLowerCase();
    }
    // Check for 'v' prefix
    else if (message.content.toLowerCase().startsWith('v')) {
        args = message.content.slice(1).trim().split(/ +/);
        commandName = args.shift().toLowerCase();
    }
    else return;

    await handleCommand(message, commandName, args);
});

// Slash command handler
client.on('interactionCreate', async interaction => {
    if (!interaction.isCommand()) return;

    const command = client.slashCommands.get(interaction.commandName);
    if (!command) return;

    try {
        await command.execute(interaction);
    } catch (error) {
        logger.error(`Error executing slash command ${interaction.commandName}:`, error);
        await interaction.reply({ 
            content: 'There was an error executing this command!', 
            ephemeral: true 
        });
    }
});

// After client initialization
const monitor = new MonitoringService(client, {
    checkInterval: 30000, // 30 seconds
    memoryThreshold: 750 * 1024 * 1024, // 750MB
    cpuThreshold: 85 // 85%
});

monitor.on('unhealthy', (issues) => {
    // Handle unhealthy state
    logger.error('Bot health issues detected:', issues);
});

monitor.start();
