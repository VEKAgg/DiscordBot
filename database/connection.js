const mongoose = require('mongoose');
const { logger } = require('../utils/logger');

const connectDB = async (uri) => {
    try {
        if (!uri || typeof uri !== 'string') {
            throw new Error('MongoDB URI is required');
        }

        const conn = await mongoose.connect(uri, {
            useNewUrlParser: true,
            useUnifiedTopology: true,
            serverSelectionTimeoutMS: 5000,
            family: 4
        });

        logger.info('MongoDB Connected Successfully');
        
        mongoose.connection.on('disconnected', () => {
            logger.warn('MongoDB disconnected. Attempting to reconnect...');
        });

        mongoose.connection.on('error', (err) => {
            logger.error('MongoDB connection error:', err);
        });

        mongoose.connection.on('reconnected', () => {
            logger.info('MongoDB reconnected successfully');
        });

        return conn;
    } catch (error) {
        logger.error('MongoDB Connection Error:', error);
        throw error;
    }
};

module.exports = { connectDB }; 