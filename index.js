const { Client, GatewayIntentBits, Collection } = require('discord.js');
const fs = require('fs');
const path = require('path');
require('dotenv').config();
const schedule = require('node-schedule');
const { runBackgroundChecks } = require('./utils/backgroundMonitor');
const config = require('./config');
const { logger } = require('./utils/logger');
const { connect: connectDB } = require('./database');

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

// Increase max event listeners
require('events').EventEmitter.defaultMaxListeners = config.maxListeners;

// Load commands
const loadCommands = (dir) => {
    const commands = [];
    const duplicates = [];
    
    const collectCommands = (directory) => {
        if (!fs.existsSync(directory)) {
            logger.error(`Directory not found: ${directory}`);
            return;
        }
        
        const items = fs.readdirSync(directory);
        for (const item of items) {
            const fullPath = path.join(directory, item);
            if (fs.lstatSync(fullPath).isDirectory()) {
                collectCommands(fullPath);
            } else if (item.endsWith('.js')) {
                try {
                    delete require.cache[require.resolve(fullPath)];
                    const command = require(fullPath);
                    if (command.name) {
                        if (client.commands.has(command.name)) {
                            duplicates.push(`${command.name} (${fullPath})`);
                        } else {
                            client.commands.set(command.name, command);
                            commands.push(command.name);
                            logger.info(`Loaded command: ${command.name}`);
                        }
                    }
                } catch (error) {
                    logger.error(`Failed to load command ${fullPath}:`, error);
                }
            }
        }
    };

    process.stdout.write('\x1b[?25l');
    process.stdout.write('Loading commands...\n');
    
    collectCommands(dir);
    
    if (duplicates.length > 0) {
        logger.warn(`Found duplicate commands: ${duplicates.join(', ')}`);
    }
    
    process.stdout.write('\x1b[?25h');
    logger.info(`Successfully loaded ${commands.length} commands: ${commands.join(', ')}`);
    
    return commands;
};

// Call loadCommands after client initialization
loadCommands(path.join(__dirname, 'commands'));

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

// Initialize database connection before starting the bot
async function init() {
    try {
        await connectDB();
        await client.login(process.env.TOKEN);
    } catch (error) {
        logger.error('Failed to initialize:', error);
        process.exit(1);
    }
}

init();

client.points = new Map();
