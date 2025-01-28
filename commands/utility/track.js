const { EmbedBuilder } = require('discord.js');
const { PriceTracker } = require('../../utils/priceTracker');
const TrackedProduct = require('../../models/TrackedProduct');
const { ErrorHandler } = require('../../utils/errorHandler');

module.exports = {
    name: 'track',
    description: 'Track price of a product',
    async execute(message, args) {
        if (!args[0]) {
            return message.reply('Usage: !track <product_url> [target_price] [notify_all=true/false]');
        }

        try {
            const [url, targetPrice, notifyAll] = args;
            const product = await PriceTracker.trackProduct(url);
            
            // Check if product is already being tracked
            let trackedProduct = await TrackedProduct.findOne({ url });
            
            if (trackedProduct) {
                // Add user to watchers if not already watching
                if (!trackedProduct.watchers.find(w => w.userId === message.author.id)) {
                    trackedProduct.watchers.push({
                        userId: message.author.id,
                        notifyOnAnyChange: notifyAll === 'true',
                        targetPrice: targetPrice ? parseFloat(targetPrice) : null
                    });
                    await trackedProduct.save();
                }
            } else {
                // Create new tracked product
                trackedProduct = await TrackedProduct.create({
                    ...product,
                    currentPrice: product.price,
                    priceHistory: [{ price: product.price }],
                    category: await PriceTracker.detectCategory(product.title),
                    watchers: [{
                        userId: message.author.id,
                        notifyOnAnyChange: notifyAll === 'true',
                        targetPrice: targetPrice ? parseFloat(targetPrice) : null
                    }]
                });
            }

            const embed = new EmbedBuilder()
                .setTitle('🎯 Product Tracking Started')
                .setDescription(`Now tracking **${product.title}**`)
                .addFields([
                    { name: 'Current Price', value: `${product.price}`, inline: true },
                    { name: 'Platform', value: product.platform, inline: true },
                    { name: 'Target Price', value: targetPrice || 'None', inline: true },
                    { name: 'Notifications', value: notifyAll === 'true' ? 'All Changes' : 'Target Price Only', inline: true }
                ])
                .setURL(product.url)
                .setColor('#2F3136')
                .setTimestamp();

            message.channel.send({ embeds: [embed] });
        } catch (error) {
            await ErrorHandler.sendErrorMessage(message, error);
        }
    }
}; 