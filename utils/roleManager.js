const { logger } = require('./logger');

class RoleManager {
    static async processRoles(member, connections, activities) {
        const roleAssignments = [
            // Developer roles
            {
                condition: this.isDeveloper(connections, activities),
                roles: ['Developer', 'Tech Enthusiast'],
                priority: 'high'
            },
            // Content Creator roles
            {
                condition: this.isContentCreator(connections),
                roles: ['Content Creator', 'Influencer'],
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

    // More role check methods...
}

module.exports = RoleManager; 