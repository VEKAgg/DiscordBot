const mongoose = require('mongoose');

const commandLogSchema = new mongoose.Schema({
    commandName: {
        type: String,
        required: true,
        index: true
    },
    userId: {
        type: String,
        required: true,
        index: true
    },
    guildId: {
        type: String,
        required: true,
        index: true
    },
    args: [String],
    executionTime: Number,
    status: {
        type: String,
        enum: ['success', 'error'],
        default: 'success'
    },
    errorMessage: String,
    timestamp: {
        type: Date,
        default: Date.now,
        index: true
    }
});

module.exports = mongoose.model('CommandLog', commandLogSchema); 