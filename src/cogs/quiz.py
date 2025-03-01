import nextcord
from nextcord.ext import commands
import logging
from datetime import datetime, timedelta
import asyncio
from src.services.quiz_service import QuizService
from src.config.config import QUIZ_CATEGORIES, QUIZ_DIFFICULTY_LEVELS

logger = logging.getLogger('VEKA.quiz')

class Quiz(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.quiz_service = QuizService(bot)
        self.active_quizzes = {}

    @commands.group(name="quiz", invoke_without_command=True)
    async def quiz(self, ctx):
        """Quiz commands"""
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title="Quiz Commands",
                description="Test your knowledge with our quiz system!",
                color=nextcord.Color.blue()
            )
            embed.add_field(
                name="Available Commands",
                value="""
                `!quiz categories` - List available quiz categories
                `!quiz start [category] [difficulty]` - Start a quiz
                `!quiz stats` - View your quiz statistics
                `!quiz leaderboard` - View the quiz leaderboard
                `!quiz daily` - Take the daily challenge
                """,
                inline=False
            )
            await ctx.send(embed=embed)

    @quiz.command(name="categories")
    async def quiz_categories(self, ctx):
        """List available quiz categories and their statistics"""
        stats = await self.quiz_service.get_category_stats()
        
        embed = nextcord.Embed(
            title="Quiz Categories",
            description="Here are all available quiz categories and their statistics:",
            color=nextcord.Color.blue()
        )
        
        for category, data in stats.items():
            value = f"Total Questions: {data['total_questions']}\n"
            value += "Difficulty Distribution:\n"
            for diff, count in data['difficulty_distribution'].items():
                value += f"• {diff}: {count}\n"
            
            embed.add_field(
                name=category,
                value=value,
                inline=False
            )
        
        await ctx.send(embed=embed)

    @quiz.command(name="start")
    async def quiz_start(self, ctx, category: str = None, difficulty: str = None):
        """Start a quiz with optional category and difficulty"""
        if category and category not in QUIZ_CATEGORIES:
            categories = ", ".join(QUIZ_CATEGORIES)
            await ctx.send(f"❌ Invalid category. Available categories: {categories}")
            return
            
        if difficulty and difficulty not in QUIZ_DIFFICULTY_LEVELS:
            difficulties = ", ".join(QUIZ_DIFFICULTY_LEVELS)
            await ctx.send(f"❌ Invalid difficulty. Available difficulties: {difficulties}")
            return

        quiz = await self.quiz_service.get_random_quiz(category, difficulty)
        if not quiz:
            await ctx.send("❌ No quiz questions found with these criteria.")
            return

        await self.send_quiz(ctx, quiz)

    @quiz.command(name="stats")
    async def quiz_stats(self, ctx):
        """View your quiz statistics"""
        stats = await self.quiz_service.get_user_stats(str(ctx.author.id))
        
        embed = nextcord.Embed(
            title=f"{ctx.author.display_name}'s Quiz Statistics",
            color=nextcord.Color.blue()
        )
        
        # Add stats fields
        embed.add_field(
            name="Total Attempts",
            value=str(stats['total_attempts']),
            inline=True
        )
        embed.add_field(
            name="Correct Answers",
            value=str(stats['correct_attempts']),
            inline=True
        )
        embed.add_field(
            name="Accuracy",
            value=f"{stats['accuracy']:.1f}%",
            inline=True
        )
        embed.add_field(
            name="Average Time",
            value=f"{stats['average_time']:.1f}s",
            inline=True
        )
        embed.add_field(
            name="Total Points",
            value=str(stats['total_points']),
            inline=True
        )
        embed.add_field(
            name="Quiz Score",
            value=str(stats['quiz_score']),
            inline=True
        )
        
        await ctx.send(embed=embed)

    @quiz.command(name="leaderboard")
    async def quiz_leaderboard(self, ctx):
        """View the quiz leaderboard"""
        leaderboard = await self.quiz_service.get_leaderboard()
        
        embed = nextcord.Embed(
            title="Quiz Leaderboard",
            description="Top quiz performers:",
            color=nextcord.Color.gold()
        )
        
        for i, entry in enumerate(leaderboard, 1):
            user = self.bot.get_user(int(entry['discord_id']))
            name = user.display_name if user else f"User {entry['discord_id']}"
            
            embed.add_field(
                name=f"{i}. {name}",
                value=f"Score: {entry['quiz_score']} | Points: {entry['total_points']}",
                inline=False
            )
        
        await ctx.send(embed=embed)

    @quiz.command(name="daily")
    async def quiz_daily(self, ctx):
        """Take the daily challenge quiz"""
        quiz, is_new = await self.quiz_service.get_daily_challenge()
        if not quiz:
            await ctx.send("❌ No daily challenge available at the moment.")
            return

        embed = nextcord.Embed(
            title="Daily Challenge",
            description="This is today's challenge question!",
            color=nextcord.Color.gold()
        )
        await ctx.send(embed=embed)
        
        await self.send_quiz(ctx, quiz, is_daily=True)

    async def send_quiz(self, ctx, quiz, is_daily=False):
        """Send a quiz question and handle the response"""
        if str(ctx.author.id) in self.active_quizzes:
            await ctx.send("❌ You already have an active quiz. Please finish it first.")
            return

        self.active_quizzes[str(ctx.author.id)] = quiz['_id']
        
        # Create quiz embed
        embed = nextcord.Embed(
            title=f"Quiz Question {'(Daily Challenge)' if is_daily else ''}",
            description=quiz['question'],
            color=nextcord.Color.blue()
        )
        
        # Add category and difficulty fields
        embed.add_field(name="Category", value=quiz['category'], inline=True)
        embed.add_field(name="Difficulty", value=quiz['difficulty'], inline=True)
        
        # Prepare answer options
        options = quiz['wrong_answers'] + [quiz['correct_answer']]
        import random
        random.shuffle(options)
        
        # Add options to embed
        option_emojis = ['🇦', '🇧', '🇨', '🇩']
        option_text = ""
        for i, option in enumerate(options):
            option_text += f"{option_emojis[i]} {option}\n"
        embed.add_field(name="Options", value=option_text, inline=False)
        
        # Send quiz and add reactions
        message = await ctx.send(embed=embed)
        start_time = datetime.utcnow()
        
        for emoji in option_emojis[:len(options)]:
            await message.add_reaction(emoji)

        def check(reaction, user):
            return (
                user == ctx.author and
                str(reaction.emoji) in option_emojis[:len(options)] and
                reaction.message.id == message.id
            )

        try:
            reaction, user = await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
            end_time = datetime.utcnow()
            time_taken = (end_time - start_time).total_seconds()
            
            # Get selected answer
            selected_index = option_emojis.index(str(reaction.emoji))
            selected_answer = options[selected_index]
            is_correct = selected_answer == quiz['correct_answer']
            
            # Record the attempt
            await self.quiz_service.record_attempt(
                str(ctx.author.id),
                str(quiz['_id']),
                is_correct,
                time_taken
            )
            
            # Create result embed
            result_embed = nextcord.Embed(
                title="Quiz Result",
                color=nextcord.Color.green() if is_correct else nextcord.Color.red()
            )
            
            if is_correct:
                result_embed.description = f"✅ Correct! You answered in {time_taken:.1f} seconds."
            else:
                result_embed.description = f"❌ Wrong! The correct answer was: {quiz['correct_answer']}"
            
            if quiz.get('explanation'):
                result_embed.add_field(name="Explanation", value=quiz['explanation'], inline=False)
            
            await ctx.send(embed=result_embed)
            
        except asyncio.TimeoutError:
            await ctx.send("❌ Time's up! You took too long to answer.")
            await self.quiz_service.record_attempt(
                str(ctx.author.id),
                str(quiz['_id']),
                False,
                30.0
            )
        
        finally:
            del self.active_quizzes[str(ctx.author.id)]

async def setup(bot):
    """Setup the Quiz cog"""
    if bot is not None:
        await bot.add_cog(Quiz(bot))
        logging.getLogger('VEKA').info("Quiz cog loaded successfully")
    else:
        logging.getLogger('VEKA').error("Bot is None in Quiz cog setup")
