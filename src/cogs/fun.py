import nextcord
from nextcord.ext import commands
import random
import logging
from datetime import datetime

logger = logging.getLogger('VEKA.fun')

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="roll")
    async def roll(self, ctx, dice: str = "1d6"):
        """Roll dice in NdN format, e.g., 3d6"""
        try:
            number, sides = map(int, dice.lower().split('d'))
            if number <= 0 or sides <= 0:
                await ctx.send("❌ Please use positive numbers!")
                return
            if number > 100:
                await ctx.send("❌ You can't roll more than 100 dice at once!")
                return
            if sides > 100:
                await ctx.send("❌ Dice can't have more than 100 sides!")
                return

            rolls = [random.randint(1, sides) for _ in range(number)]
            total = sum(rolls)
            
            embed = nextcord.Embed(
                title="🎲 Dice Roll Results",
                color=nextcord.Color.blue()
            )
            embed.add_field(name="Rolls", value=", ".join(map(str, rolls)), inline=False)
            embed.add_field(name="Total", value=str(total), inline=False)
            
            await ctx.send(embed=embed)
            
        except ValueError:
            await ctx.send("❌ Format has to be in NdN! Example: 3d6")

    @commands.command(name="flip")
    async def flip(self, ctx):
        """Flip a coin"""
        result = random.choice(["Heads", "Tails"])
        emoji = "🌝" if result == "Heads" else "🌚"
        
        embed = nextcord.Embed(
            title=f"{emoji} Coin Flip",
            description=f"The coin landed on **{result}**!",
            color=nextcord.Color.gold()
        )
        await ctx.send(embed=embed)

    @commands.command(name="8ball")
    async def eight_ball(self, ctx, *, question: str):
        """Ask the magic 8 ball a question"""
        responses = [
            "It is certain.", "It is decidedly so.", "Without a doubt.",
            "Yes - definitely.", "You may rely on it.", "As I see it, yes.",
            "Most likely.", "Outlook good.", "Yes.",
            "Signs point to yes.", "Reply hazy, try again.", "Ask again later.",
            "Better not tell you now.", "Cannot predict now.", "Concentrate and ask again.",
            "Don't count on it.", "My reply is no.", "My sources say no.",
            "Outlook not so good.", "Very doubtful."
        ]
        
        embed = nextcord.Embed(
            title="🎱 Magic 8 Ball",
            color=nextcord.Color.purple()
        )
        embed.add_field(name="Question", value=question, inline=False)
        embed.add_field(name="Answer", value=random.choice(responses), inline=False)
        
        await ctx.send(embed=embed)

    @commands.command(name="rps")
    async def rps(self, ctx, choice: str):
        """Play Rock, Paper, Scissors"""
        choice = choice.lower()
        if choice not in ['rock', 'paper', 'scissors']:
            await ctx.send("❌ Please choose either rock, paper, or scissors!")
            return

        bot_choice = random.choice(['rock', 'paper', 'scissors'])
        
        # Determine winner
        if choice == bot_choice:
            result = "It's a tie!"
            color = nextcord.Color.blue()
        elif (
            (choice == 'rock' and bot_choice == 'scissors') or
            (choice == 'paper' and bot_choice == 'rock') or
            (choice == 'scissors' and bot_choice == 'paper')
        ):
            result = "You win! 🎉"
            color = nextcord.Color.green()
        else:
            result = "I win! 😎"
            color = nextcord.Color.red()

        # Emoji mapping
        emojis = {
            'rock': '🪨',
            'paper': '📄',
            'scissors': '✂️'
        }

        embed = nextcord.Embed(
            title="Rock, Paper, Scissors!",
            color=color
        )
        embed.add_field(name="Your Choice", value=f"{emojis[choice]} {choice.capitalize()}", inline=True)
        embed.add_field(name="My Choice", value=f"{emojis[bot_choice]} {bot_choice.capitalize()}", inline=True)
        embed.add_field(name="Result", value=result, inline=False)
        
        await ctx.send(embed=embed)

    @commands.command(name="choose")
    async def choose(self, ctx, *, choices: str):
        """Choose between multiple options (separate with commas)"""
        try:
            options = [option.strip() for option in choices.split(',')]
            if len(options) < 2:
                await ctx.send("❌ Please provide at least 2 options separated by commas!")
                return

            chosen = random.choice(options)
            
            embed = nextcord.Embed(
                title="🤔 Choice Made!",
                description=f"I choose... **{chosen}**!",
                color=nextcord.Color.blue()
            )
            embed.add_field(name="Options were", value="\n".join(f"• {option}" for option in options))
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in choose command: {str(e)}")
            await ctx.send("❌ Error processing your choices. Make sure to separate them with commas!")

async def setup(bot):
    """Setup the Fun cog"""
    if bot is not None:
        await bot.add_cog(Fun(bot))
        logging.getLogger('VEKA').info("Fun cog loaded successfully")
    else:
        logging.getLogger('VEKA').error("Bot is None in Fun cog setup")
