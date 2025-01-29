const { ActivityType } = require('discord.js');
const { joinVoiceChannel } = require('@discordjs/voice');
const { logger } = require('../utils/logger');
const config = require('../config/botStatus');
const { REST, Routes } = require('discord.js');
const schedule = require('node-schedule');
const { dmInactiveUsers } = require('../utils/userDM');

module.exports = {
    name: 'ready',
    once: true,
    async execute(client) {
        try {
            logger.info(`Logged in as ${client.user.tag}`);

            // Get all slash commands
            const commands = [];
            client.slashCommands.forEach(command => {
                if (command.data) {
                    commands.push(command.data.toJSON());
                }
            });

            // Register slash commands
            const rest = new REST({ version: '10' }).setToken(process.env.TOKEN);
            
            logger.info(`Started refreshing ${commands.length} application (/) commands.`);

            await rest.put(
                Routes.applicationCommands(client.user.id),
                { body: commands }
            );

            logger.info('Successfully reloaded application (/) commands.');

            // Join voice channel if configured
            if (process.env.HOME_VOICE_CHANNEL && process.env.HOME_GUILD_ID) {
                try {
                    joinVoiceChannel({
                        channelId: process.env.HOME_VOICE_CHANNEL,
                        guildId: process.env.HOME_GUILD_ID,
                        adapterCreator: client.guilds.cache.get(process.env.HOME_GUILD_ID)?.voiceAdapterCreator,
                        selfDeaf: true
                    });
                    logger.info('Successfully joined home voice channel');
                } catch (error) {
                    logger.error('Failed to join voice channel:', error);
                }
            }

            // Initialize status rotation
            let statusIndex = 0;
            setInterval(() => {
                const status = config.statuses[statusIndex];
                let text = status.text
                    .replace('{memberCount}', client.users.cache.size)
                    .replace('{serverCount}', client.guilds.cache.size)
                    .replace('{activeVoice}', client.voice.adapters.size);

                client.user.setActivity(text, { type: status.type });
                statusIndex = (statusIndex + 1) % config.statuses.length;
            }, config.interval);

            // Schedule the DM task to run once a day
            schedule.scheduleJob('0 0 * * *', () => {
                dmInactiveUsers(client);
            });

            // Initialize deal tracker
            const DealTracker = require('../services/dealTracker');
            const dealTracker = new DealTracker(client);
            await dealTracker.init().catch(error => {
                logger.error('Failed to initialize deal tracker:', error);
            });

        } catch (error) {
            logger.error('Error in ready event:', error);
        }
    }
};
