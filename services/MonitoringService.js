const { EventEmitter } = require('events');
const { logger } = require('../utils/logger');
const os = require('os');
const dbManager = require('../database/connection');

class MonitoringService extends EventEmitter {
    constructor(client, options = {}) {
        super();
        this.client = client;
        this.checkInterval = options.checkInterval || 60000; // 1 minute
        this.memoryThreshold = options.memoryThreshold || 500 * 1024 * 1024; // 500MB
        this.cpuThreshold = options.cpuThreshold || 80; // 80%
        this.checks = new Map();
        this.status = {
            healthy: true,
            lastCheck: null,
            issues: []
        };
    }

    start() {
        this.registerHealthChecks();
        this.startMonitoring();
        logger.info('Monitoring service started');
    }

    registerHealthChecks() {
        this.checks.set('websocket', this.checkWebSocket.bind(this));
        this.checks.set('database', this.checkDatabase.bind(this));
        this.checks.set('memory', this.checkMemory.bind(this));
        this.checks.set('cpu', this.checkCPU.bind(this));
        this.checks.set('commands', this.checkCommandResponse.bind(this));
    }

    async startMonitoring() {
        setInterval(async () => {
            try {
                await this.runHealthChecks();
            } catch (error) {
                logger.error('Health check failed:', error);
                this.emit('healthCheckError', error);
            }
        }, this.checkInterval);
    }

    async runHealthChecks() {
        const issues = [];
        let healthy = true;

        for (const [name, check] of this.checks) {
            try {
                const result = await check();
                if (!result.healthy) {
                    healthy = false;
                    issues.push(`${name}: ${result.message}`);
                }
            } catch (error) {
                healthy = false;
                issues.push(`${name}: Check failed - ${error.message}`);
            }
        }

        this.status = {
            healthy,
            lastCheck: new Date(),
            issues
        };

        this.emit('healthCheck', this.status);
        
        if (!healthy) {
            this.emit('unhealthy', issues);
            logger.warn('Health check failed:', issues);
        }
    }

    async checkWebSocket() {
        const ping = this.client.ws.ping;
        return {
            healthy: ping < 500,
            message: ping >= 500 ? `High latency: ${ping}ms` : null
        };
    }

    async checkDatabase() {
        try {
            const conn = dbManager.getConnection();
            await conn.db.admin().ping();
            return { healthy: true };
        } catch (error) {
            return {
                healthy: false,
                message: `Database unreachable: ${error.message}`
            };
        }
    }

    async checkMemory() {
        const used = process.memoryUsage().heapUsed;
        return {
            healthy: used < this.memoryThreshold,
            message: used >= this.memoryThreshold ? 
                `Memory usage high: ${Math.round(used / 1024 / 1024)}MB` : null
        };
    }

    async checkCPU() {
        const cpuUsage = await this.getCPUUsage();
        return {
            healthy: cpuUsage < this.cpuThreshold,
            message: cpuUsage >= this.cpuThreshold ? 
                `CPU usage high: ${Math.round(cpuUsage)}%` : null
        };
    }

    async checkCommandResponse() {
        const lastCmd = this.client.lastCommandTime || 0;
        const threshold = Date.now() - (5 * 60 * 1000); // 5 minutes
        
        return {
            healthy: lastCmd > threshold,
            message: lastCmd <= threshold ? 
                'No commands processed in last 5 minutes' : null
        };
    }

    async getCPUUsage() {
        const cpus = os.cpus();
        const usage = cpus.reduce((acc, cpu) => {
            const total = Object.values(cpu.times).reduce((a, b) => a + b);
            const idle = cpu.times.idle;
            return acc + ((total - idle) / total * 100);
        }, 0) / cpus.length;
        
        return usage;
    }

    getStatus() {
        return this.status;
    }
}

module.exports = MonitoringService; 