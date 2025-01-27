const { logger } = require('./logger');

class RoleManager {
    static async processRoles(member, connections, activities) {
        const roleAssignments = [
            // Developer roles
            {
                condition: this.isDeveloper(connections, activities),
                roles: ['Dev'],
                priority: 'high'
            },
            {
                condition: this.isUsingIDE(activities),
                roles: ['IDE User'],
                priority: 'medium'
            },
            // Content Creator roles
            {
                condition: this.isContentCreator(connections),
                roles: ['Creator'],
                priority: 'medium'
            },
            // More role categories...
        ];

        for (const assignment of roleAssignments) {
            if (await assignment.condition) {
                await this.assignRoles(member, assignment.roles, assignment.priority);
            }
        }
    }

    static async isDeveloper(connections, activities) {
        const devTools = ['VS Code', 'IntelliJ', 'GitHub Desktop'];
        const hasDevActivity = activities.some(a => 
            devTools.some(tool => a.name.includes(tool))
        );
        return connections.github.verified || hasDevActivity;
    }

    static async isUsingIDE(activities) {
        const ideTools = ['Visual Studio Code', 'PyCharm', 'IntelliJ'];
        return activities.some(activity => 
            ideTools.some(tool => activity.name.includes(tool))
        );
    }

    // More role check methods...

    static async assignNotificationRoles(member) {
        const notificationRole = member.guild.roles.cache.find(role => role.name === 'Notification Squad');
        if (notificationRole) {
            await member.roles.add(notificationRole);
        }
    }

    static async assignLanguageRoles(member, language) {
        const languageRole = member.guild.roles.cache.find(role => role.name === language);
        if (languageRole) {
            await member.roles.add(languageRole);
        }
    }

    static async assignRegionalRoles(member, region) {
        const regionRole = member.guild.roles.cache.find(role => role.name === region);
        if (regionRole) {
            await member.roles.add(regionRole);
        }
    }
}

module.exports = RoleManager; 