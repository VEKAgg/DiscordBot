const { SlashCommandBuilder } = require('@discordjs/builders');
const { PriceTracker } = require('../../utils/priceTracker');
const TrackedProduct = require('../../models/TrackedProduct');

module.exports = {
    data: new SlashCommandBuilder()
        .setName('track')
        .setDescription('Track price for a product')
        .addStringOption(option =>
            option.setName('url')
                .setDescription('Product URL to track')
                .setRequired(true))
        .addNumberOption(option =>
            option.setName('target')
                .setDescription('Target price for notifications')
                .setRequired(false)),

    async execute(interaction) {
        await interaction.deferReply();
        const url = interaction.options.getString('url');
        const targetPrice = interaction.options.getNumber('target');

        try {
            const product = await PriceTracker.trackProduct(url);
            
            await TrackedProduct.findOneAndUpdate(
                { url },
                {
                    ...product,
                    currentPrice: product.price,
                    watchers: [{
                        userId: interaction.user.id,
                        targetPrice,
                        notifyOnAnyChange: !targetPrice
                    }]
                },
                { upsert: true }
            );

            await interaction.editReply(`Now tracking ${product.title} - Current price: ${product.price}`);
        } catch (error) {
            await interaction.editReply('Failed to track product. Make sure the URL is supported and valid.');
        }
    }
}; 