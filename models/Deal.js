const mongoose = require('mongoose');

const dealSchema = new mongoose.Schema({
    platform: {
        type: String,
        required: true
    },
    title: {
        type: String,
        required: true
    },
    url: {
        type: String,
        required: true,
        unique: true
    },
    originalPrice: Number,
    salePrice: Number,
    discount: Number,
    thumbnail: String,
    expiryDate: Date,
    postedDate: {
        type: Date,
        default: Date.now
    }
});

module.exports = mongoose.model('Deal', dealSchema); 