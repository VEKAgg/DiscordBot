const { Client, GatewayIntentBits, Collection, REST, Routes } = require('discord.js');
const fs = require('fs');
const path = require('path');
require('dotenv').config();
const schedule = require('node-schedule');
const { runBackgroundChecks } = require('./utils/backgroundMonitor');
const config = require('./config');
const { logger } = require('./utils/logger');
const { connectDB } = require('./database/connection');
const { dmInactiveUsers } = require('./utils/userDM');
const { massDMUsers } = require('./utils/massDM');

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

// Load commands
const loadCommands = (dir) => {
    const files = fs.readdirSync(dir);
    let loadedCount = 0;
    let errorCount = 0;
    let errorCommands = [];

    for (const file of files) {
        const filePath = path.join(dir, file);
        const stat = fs.statSync(filePath);
        
        if (stat.isDirectory()) {
            const [loaded, errors, errorFiles] = loadCommands(filePath);
            loadedCount += loaded;
            errorCount += errors;
            errorCommands.push(...errorFiles);
        } else if (file.endsWith('.js')) {
            try {
                delete require.cache[require.resolve(filePath)];
                const command = require(filePath);
                if (command.name) {
                    if (client.commands.has(command.name)) {
                        logger.warn(`Duplicate command found: ${command.name}`);
                        continue;
                    }
                    client.commands.set(command.name, command);
                    if (command.slashCommand) {
                        client.slashCommands.set(command.name, command);
                        logger.info(`Loaded slash command: ${command.name}`);
                    }
                    loadedCount++;
                }
            } catch (error) {
                errorCount++;
                errorCommands.push(file);
                logger.error(`Failed to load ${file}:`, error);
            }
        }
    }
    
    return [loadedCount, errorCount, errorCommands];
};

// Load all commands
const [loaded, errors, errorFiles] = loadCommands(path.join(__dirname, 'commands'));
logger.info(`Loaded ${loaded} commands with ${errors} errors`);
if (errors > 0) {
    logger.error('Failed commands:', errorFiles);
}

// Load events
const eventFiles = fs.readdirSync('./events').filter(file => file.endsWith('.js'));
let loadedEvents = 0;
let errorEvents = [];

for (const file of eventFiles) {
    try {
        const event = require(`./events/${file}`);
        if (event.once) {
            client.once(event.name, (...args) => event.execute(...args, client));
        } else {
            client.on(event.name, (...args) => event.execute(...args, client));
        }
        loadedEvents++;
    } catch (error) {
        errorEvents.push(file);
        logger.error(`Failed to load event ${file}: ${error.message}`);
    }
}

logger.info(`Loaded ${loadedEvents} events successfully.`);
if (errorEvents.length > 0) {
    logger.error(`Failed to load events: ${errorEvents.join(', ')}`);
}

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

client.once('ready', () => {
    console.log(`Logged in as ${client.user.tag}`);

    // Schedule the DM task to run once a day
    schedule.scheduleJob('0 0 * * *', () => {
        dmInactiveUsers(client);
    });
});

// Command to trigger mass DM
client.on('messageCreate', async (message) => {
    if (message.content.startsWith('!massdm')) {
        const presetMessage = "This is a preset message for all users.";
        await massDMUsers(client, presetMessage);
        message.reply('Mass DM process started.');
    }
});

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
