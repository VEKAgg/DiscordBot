const mongoose = require('mongoose');

const logEntrySchema = new mongoose.Schema({
    guildId: { type: String, required: true },
    type: { type: String, required: true },
    content: { type: String, required: true },
    timestamp: { type: Date, default: Date.now },
    metadata: { type: Map, of: String }
}, { 
    timestamps: true 
});

logEntrySchema.index({ guildId: 1, type: 1, timestamp: -1 });

module.exports = mongoose.model('LogEntry', logEntrySchema); 