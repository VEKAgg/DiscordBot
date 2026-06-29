import logging
import random

import nextcord
from nextcord.ext import commands

logger = logging.getLogger('VEKA.fun')


class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ==================== PREFIX COMMANDS ====================

    @commands.command(name='roll')
    async def roll(self, ctx, dice: str = '1d6'):
        """Roll dice in NdN format, e.g., 3d6"""
        embed = self._roll_dice(dice)
        if embed:
            await ctx.send(embed=embed)

    @commands.command(name='flip')
    async def flip(self, ctx):
        """Flip a coin"""
        result = random.choice(['Heads', 'Tails'])
        emoji = '🌝' if result == 'Heads' else '🌚'
        embed = nextcord.Embed(
            title=f'{emoji} Coin Flip', description=f'The coin landed on **{result}**!', color=nextcord.Color.orange()
        )
        await ctx.send(embed=embed)

    @commands.command(name='8ball')
    async def eight_ball(self, ctx, *, question: str):
        """Ask the magic 8-ball a question"""
        embed = self._magic_8ball(question)
        await ctx.send(embed=embed)

    @commands.command(name='rps')
    async def rps(self, ctx, choice: str):
        """Play Rock, Paper, Scissors"""
        embed = self._rps_game(choice)
        if embed:
            await ctx.send(embed=embed)

    @commands.command(name='choose')
    async def choose(self, ctx, *, choices: str):
        """Choose between multiple options (comma-separated)"""
        embed = self._choose_option(choices)
        if embed:
            await ctx.send(embed=embed)

    # ==================== SLASH COMMANDS ====================

    @nextcord.slash_command(name='roll', description='Roll dice in NdN format (e.g. 3d6)')
    async def roll_slash(self, interaction: nextcord.Interaction, dice: str = '1d6'):
        """Roll dice in NdN format, e.g., 3d6"""
        embed = self._roll_dice(dice)
        if embed:
            await interaction.response.send_message(embed=embed)

    @nextcord.slash_command(name='flip', description='Flip a coin')
    async def flip_slash(self, interaction: nextcord.Interaction):
        """Flip a coin"""
        result = random.choice(['Heads', 'Tails'])
        emoji = '🌝' if result == 'Heads' else '🌚'
        embed = nextcord.Embed(
            title=f'{emoji} Coin Flip', description=f'The coin landed on **{result}**!', color=nextcord.Color.orange()
        )
        await interaction.response.send_message(embed=embed)

    @nextcord.slash_command(name='8ball', description='Ask the magic 8-ball a question')
    async def eight_ball_slash(self, interaction: nextcord.Interaction, question: str):
        """Ask the magic 8-ball a question"""
        embed = self._magic_8ball(question)
        await interaction.response.send_message(embed=embed)

    @nextcord.slash_command(name='rps', description='Play Rock, Paper, Scissors')
    async def rps_slash(
        self,
        interaction: nextcord.Interaction,
        choice: str = nextcord.SlashOption(
            name='choice', description='Your choice', choices={'Rock': 'rock', 'Paper': 'paper', 'Scissors': 'scissors'}
        ),
    ):
        """Play Rock, Paper, Scissors"""
        embed = self._rps_game(choice)
        if embed:
            await interaction.response.send_message(embed=embed)

    @nextcord.slash_command(name='choose', description='Choose between comma-separated options')
    async def choose_slash(self, interaction: nextcord.Interaction, options: str):
        """Choose between multiple options (comma-separated)"""
        embed = self._choose_option(options)
        if embed:
            await interaction.response.send_message(embed=embed)

    # ==================== SHARED LOGIC ====================

    def _roll_dice(self, dice: str) -> nextcord.Embed | None:
        try:
            number, sides = map(int, dice.lower().split('d'))
            if number <= 0 or sides <= 0:
                return None
            if number > 100:
                return None
            if sides > 100:
                return None

            rolls = [random.randint(1, sides) for _ in range(number)]
            total = sum(rolls)

            embed = nextcord.Embed(title='🎲 Dice Roll Results', color=nextcord.Color.orange())

            if len(rolls) <= 15:
                roll_str = ' + '.join(map(str, rolls))
                if len(rolls) > 1:
                    roll_str += f' = {total}'
                embed.add_field(name='Rolls', value=f'```{roll_str}```', inline=False)
            else:
                embed.add_field(name='Rolls', value=f'Rolled {number}d{sides} (too many to display)', inline=False)

            embed.add_field(name='Total', value=f'**{total}**', inline=False)
            return embed

        except ValueError:
            return None

    def _magic_8ball(self, question: str) -> nextcord.Embed:
        responses = [
            'It is certain.',
            'It is decidedly so.',
            'Without a doubt.',
            'Yes - definitely.',
            'You may rely on it.',
            'As I see it, yes.',
            'Most likely.',
            'Outlook good.',
            'Yes.',
            'Signs point to yes.',
            'Reply hazy, try again.',
            'Ask again later.',
            'Better not tell you now.',
            'Cannot predict now.',
            'Concentrate and ask again.',
            "Don't count on it.",
            'My reply is no.',
            'My sources say no.',
            'Outlook not so good.',
            'Very doubtful.',
        ]
        response = random.choice(responses)
        embed = nextcord.Embed(title='🔮 Magic 8-Ball', color=nextcord.Color.orange())
        embed.add_field(name='Question', value=question, inline=False)
        embed.add_field(name='Answer', value=response, inline=False)
        return embed

    def _rps_game(self, choice: str) -> nextcord.Embed | None:
        choice = choice.lower()
        choices = ['rock', 'paper', 'scissors']

        if choice not in choices:
            return None

        bot_choice = random.choice(choices)

        if choice == bot_choice:
            result = "It's a tie!"
            color = nextcord.Color.orange()
        elif (
            (choice == 'rock' and bot_choice == 'scissors')
            or (choice == 'paper' and bot_choice == 'rock')
            or (choice == 'scissors' and bot_choice == 'paper')
        ):
            result = 'You win!'
            color = nextcord.Color.green()
        else:
            result = 'I win!'
            color = nextcord.Color.red()

        emojis = {'rock': '🪨', 'paper': '📄', 'scissors': '✂️'}

        embed = nextcord.Embed(title='✂️ Rock, Paper, Scissors', description=result, color=color)
        embed.add_field(name='Your Choice', value=f'{emojis[choice]} {choice.capitalize()}', inline=True)
        embed.add_field(name='My Choice', value=f'{emojis[bot_choice]} {bot_choice.capitalize()}', inline=True)
        return embed

    def _choose_option(self, choices: str) -> nextcord.Embed | None:
        options = [option.strip() for option in choices.split(',') if option.strip()]

        if len(options) < 2:
            return None

        chosen = random.choice(options)

        embed = nextcord.Embed(
            title='🎯 Choice Maker', description=f'I choose...\n\n**{chosen}**!', color=nextcord.Color.orange()
        )
        options_text = '\n'.join([f'• {option}' for option in options])
        embed.add_field(name='Options', value=options_text, inline=False)
        return embed


def setup(bot):
    """Setup the Fun cog"""
    if bot is not None:
        bot.add_cog(Fun(bot))
        logging.getLogger('VEKA').info('Loaded cog: src.cogs.fun')
    else:
        logging.getLogger('VEKA').error('Bot is None in Fun cog setup')
