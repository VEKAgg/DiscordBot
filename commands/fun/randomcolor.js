const { EmbedBuilder } = require('discord.js');
const { createCanvas } = require('canvas');

module.exports = {
    name: 'randomcolor',
    description: 'Display a random color with detailed information',
    async execute(message) {
        // Generate random RGB values
        const r = Math.floor(Math.random() * 256);
        const g = Math.floor(Math.random() * 256);
        const b = Math.floor(Math.random() * 256);

        // Convert to hex
        const hexColor = rgbToHex(r, g, b);
        
        // Calculate HSL values
        const [h, s, l] = rgbToHsl(r, g, b);
        
        // Create a color preview using canvas
        const canvas = createCanvas(100, 100);
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = `rgb(${r}, ${g}, ${b})`;
        ctx.fillRect(0, 0, 100, 100);

        const embed = new EmbedBuilder()
            .setTitle('🎨 Random Color Generator')
            .setDescription(`Here's your random color!`)
            .addFields([
                { name: 'Hex', value: hexColor.toUpperCase(), inline: true },
                { name: 'RGB', value: `rgb(${r}, ${g}, ${b})`, inline: true },
                { name: 'HSL', value: `hsl(${Math.round(h)}°, ${Math.round(s)}%, ${Math.round(l)}%)`, inline: true },
                { name: 'Color Type', value: getColorCategory(h, s, l), inline: true },
                { name: 'Brightness', value: getBrightnessLevel(l), inline: true },
                { name: 'Saturation', value: getSaturationLevel(s), inline: true }
            ])
            .setColor(hexColor)
            .setImage('attachment://color.png')
            .setFooter({ text: 'Try using this color in your designs!' })
            .setTimestamp();

        message.channel.send({ 
            embeds: [embed],
            files: [{
                attachment: canvas.toBuffer(),
                name: 'color.png'
            }]
        });
    },
};

function rgbToHex(r, g, b) {
    return '#' + [r, g, b].map(x => {
        const hex = x.toString(16);
        return hex.length === 1 ? '0' + hex : hex;
    }).join('');
}

function rgbToHsl(r, g, b) {
    r /= 255;
    g /= 255;
    b /= 255;
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    let h, s, l = (max + min) / 2;

    if (max === min) {
        h = s = 0;
    } else {
        const d = max - min;
        s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
        switch (max) {
            case r: h = (g - b) / d + (g < b ? 6 : 0); break;
            case g: h = (b - r) / d + 2; break;
            case b: h = (r - g) / d + 4; break;
        }
        h /= 6;
    }

    return [h * 360, s * 100, l * 100];
}

function getColorCategory(h, s, l) {
    if (s < 10) return 'Grayscale';
    if (h >= 0 && h < 30) return 'Red-Orange';
    if (h >= 30 && h < 60) return 'Yellow-Orange';
    if (h >= 60 && h < 120) return 'Green';
    if (h >= 120 && h < 180) return 'Cyan';
    if (h >= 180 && h < 240) return 'Blue';
    if (h >= 240 && h < 300) return 'Purple';
    return 'Pink-Red';
}

function getBrightnessLevel(l) {
    if (l < 20) return 'Very Dark';
    if (l < 40) return 'Dark';
    if (l < 60) return 'Medium';
    if (l < 80) return 'Light';
    return 'Very Light';
}

function getSaturationLevel(s) {
    if (s < 20) return 'Very Dull';
    if (s < 40) return 'Dull';
    if (s < 60) return 'Moderate';
    if (s < 80) return 'Vibrant';
    return 'Very Vibrant';
}
