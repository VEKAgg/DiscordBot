const path = require('path');
const fs = require('fs').promises;
const { logger } = require('./logger');

class CommandLoader {
    constructor(client) {
        this.client = client;
    }

    async loadCommands(commandsPath) {
        try {
            // Resolve the absolute path
            const absolutePath = path.resolve(process.cwd(), commandsPath);
            logger.debug(`Loading commands from: ${absolutePath}`);

            const categories = await fs.readdir(absolutePath);
            const commandStats = {
                total: 0,
                slash: 0,
                legacy: 0,
                categories: new Map()
            };

            for (const category of categories) {
                const categoryPath = path.join(absolutePath, category);
                
                try {
                    const stat = await fs.stat(categoryPath);
                    if (!stat.isDirectory()) continue;

                    logger.debug(`Loading category: ${category}`);
                    const files = await fs.readdir(categoryPath);
                    commandStats.categories.set(category, 0);
                    
                    for (const file of files) {
                        if (!file.endsWith('.js')) continue;
                        
                        try {
                            const commandPath = path.join(categoryPath, file);
                            delete require.cache[require.resolve(commandPath)];
                            const command = require(commandPath);
                            
                            if (command.data) {
                                this.client.slashCommands.set(command.data.name, command);
                                commandStats.slash++;
                                commandStats.total++;
                                logger.debug(`Loaded slash command: ${category}/${file}`);
                            } else if (command.name) {
                                this.client.commands.set(command.name, command);
                                commandStats.legacy++;
                                commandStats.total++;
                                logger.debug(`Loaded legacy command: ${category}/${file}`);
                            }
                            
                            commandStats.categories.set(
                                category, 
                                (commandStats.categories.get(category) || 0) + 1
                            );
                        } catch (error) {
                            logger.error(`Failed to load command ${category}/${file}:`, error.stack);
                        }
                    }
                } catch (error) {
                    logger.error(`Error loading category ${category}:`, error.stack);
                }
            }

            logger.info('Command loading summary:');
            logger.info(`Total commands: ${commandStats.total}`);
            logger.info(`Slash commands: ${commandStats.slash}`);
            logger.info(`Legacy commands: ${commandStats.legacy}`);
            logger.info('Commands per category:');
            commandStats.categories.forEach((count, category) => {
                logger.info(`  ${category}: ${count} commands`);
            });

            return commandStats;
        } catch (error) {
            logger.error('Error in command loader:', error.stack);
            return { total: 0, categories: 0 };
        }
    }
}

module.exports = CommandLoader; 