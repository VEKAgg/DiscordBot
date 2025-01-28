const os = require('os');
const fs = require('fs/promises');
const path = require('path');
const { logger } = require('./logger');

class SystemMonitor {
    static async checkSystem() {
        const metrics = {
            cpu: os.loadavg()[0],
            memory: {
                total: os.totalmem(),
                free: os.freemem()
            },
            disk: await this.checkDiskSpace(),
            uptime: os.uptime()
        };

        // Alert if resources are running low
        if (metrics.cpu > 80) {
            logger.warn('High CPU usage detected');
        }

        const memoryUsage = (metrics.memory.total - metrics.memory.free) / metrics.memory.total * 100;
        if (memoryUsage > 80) {
            logger.warn('High memory usage detected');
        }

        if (metrics.disk.usagePercent > 80) {
            logger.warn('Disk space running low');
        }

        return metrics;
    }

    static async checkDiskSpace() {
        // Implementation depends on OS
        // For Linux:
        const df = await fs.exec('df -h /');
        // Parse df output and return disk metrics
    }
}

module.exports = SystemMonitor; 