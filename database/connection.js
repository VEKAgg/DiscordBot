const mongoose = require('mongoose');
const { logger } = require('../utils/logger');

class DatabaseManager {
    constructor() {
        this.isConnected = false;
        this.retryAttempts = 0;
        this.maxRetries = 5;
        this.retryDelay = 5000;

        // Configure mongoose
        mongoose.set('bufferCommands', false);
        mongoose.set('strictQuery', true);
        
        // Handle connection events
        mongoose.connection.on('connected', () => {
            this.isConnected = true;
            this.retryAttempts = 0;
            logger.info('MongoDB connection established');
        });

        mongoose.connection.on('error', (err) => {
            logger.error('MongoDB connection error:', err);
            this.handleConnectionError();
        });

        mongoose.connection.on('disconnected', () => {
            this.isConnected = false;
            logger.warn('MongoDB disconnected');
            this.handleConnectionError();
        });

        // Handle process termination
        process.on('SIGINT', this.cleanup.bind(this));
        process.on('SIGTERM', this.cleanup.bind(this));
    }

    async connect(uri) {
        try {
            if (this.isConnected) {
                logger.warn('Already connected to MongoDB');
                return;
            }

            await mongoose.connect(uri, {
                useNewUrlParser: true,
                useUnifiedTopology: true,
                serverSelectionTimeoutMS: 5000,
                heartbeatFrequencyMS: 10000,
                maxPoolSize: 10
            });

        } catch (error) {
            logger.error('Failed to connect to MongoDB:', error);
            this.handleConnectionError();
            throw error;
        }
    }

    async handleConnectionError() {
        if (this.retryAttempts >= this.maxRetries) {
            logger.error('Max reconnection attempts reached');
            process.exit(1);
        }

        this.retryAttempts++;
        logger.info(`Attempting to reconnect... (${this.retryAttempts}/${this.maxRetries})`);

        setTimeout(async () => {
            try {
                await mongoose.connect(process.env.MONGODB_URI);
            } catch (error) {
                logger.error('Reconnection attempt failed:', error);
            }
        }, this.retryDelay);
    }

    async cleanup() {
        if (this.isConnected) {
            try {
                await mongoose.connection.close();
                logger.info('MongoDB connection closed through app termination');
                process.exit(0);
            } catch (error) {
                logger.error('Error during MongoDB cleanup:', error);
                process.exit(1);
            }
        }
    }

    getConnection() {
        return mongoose.connection;
    }
}

module.exports = new DatabaseManager(); 