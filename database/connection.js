const mongoose = require('mongoose');
const { logger } = require('../utils/logger');

const connectDB = async (mongoURI) => {
    try {
        await mongoose.connect(mongoURI, {
            autoIndex: true
        });
        
        logger.info('MongoDB Connected Successfully');
        
        mongoose.connection.on('error', (err) => {
            logger.error('MongoDB Error:', err);
        });

        mongoose.connection.on('disconnected', () => {
            logger.warn('MongoDB Disconnected. Attempting to reconnect...');
        });

        mongoose.connection.on('reconnected', () => {
            logger.info('MongoDB Reconnected Successfully');
        });

    } catch (error) {
        logger.error('MongoDB Connection Error:', error);
        process.exit(1);
    }
};

module.exports = { connectDB }; 