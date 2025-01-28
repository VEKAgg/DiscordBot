const mongoose = require('mongoose');

const gamingConfigSchema = new mongoose.Schema({
    guildId: { type: String, required: true, unique: true },
    enabled: { type: Boolean, default: false },
    trackedGames: [String],
    roleRewards: [{
        gameName: String,
        roleId: String,
        timeRequired: Number
    }],
    lastUpdate: { type: Date, default: Date.now }
});

module.exports = mongoose.model('GamingConfig', gamingConfigSchema);
