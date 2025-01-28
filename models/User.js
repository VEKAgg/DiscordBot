const mongoose = require('mongoose');

const userSchema = new mongoose.Schema({
  userId: String,
  guildId: String,
  username: { type: String, required: true },
  discriminator: { type: String, required: true },
  joinedAt: { type: Date, default: Date.now },
  demographics: {
    age: Number,
    gender: String,
    location: String,
  },
  activity: {
    richPresence: [{
      name: String,
      type: String,
      timestamp: Date,
      duration: { type: Number, default: 0 }
    }],
    voiceTime: { type: Number, default: 0 },
    messageCount: { type: Number, default: 0 },
    totalScore: { type: Number, default: 0 }
  },
  presenceHistory: [{
    status: String,
    timestamp: Date
  }],
  gameStats: [{
    gameName: String,
    totalTime: Number,
    lastPlayed: Date
  }],
  activityMetrics: {
    messageCount: { type: Number, default: 0 },
    voiceTime: { type: Number, default: 0 },
    commandsUsed: { type: Number, default: 0 }
  }
});

module.exports = mongoose.model('User', userSchema);
