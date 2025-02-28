import nextcord
from nextcord.ext import commands
import logging
from src.services.quiz_service import QuizService
from src.config.config import QUIZ_CATEGORIES, QUIZ_DIFFICULTY_LEVELS, QUIZ_TIMEOUT_SECONDS
from src.database.sqlite_db import get_session
import asyncio
import random
from datetime import datetime
import json

logger = logging.getLogger('VEKA.quiz')

class Quiz(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_quizzes = {}

    @commands.group(name="quiz", invoke_without_command=True)
    async def quiz(self, ctx):
        """Quiz commands for learning and testing knowledge"""
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title="Quiz Commands",
                description="Test your knowledge with interactive quizzes!",
                color=nextcord.Color.blue()
            )
            embed.add_field(
                name="Available Commands",
                value="""
                `!quiz start [category] [difficulty]` - Start a quiz
                `!quiz categories` - List available categories
                `!quiz stats` - View your quiz statistics
                `!quiz leaderboard` - Show quiz leaderboard
                `!quiz daily` - Take the daily challenge
                """,
                inline=False
            )
            await ctx.send(embed=embed)

    @quiz.command(name="categories")
    async def quiz_categories(self, ctx):
        """List available quiz categories"""
        embed = nextcord.Embed(
            title="Quiz Categories",
            description="Choose a category for your quiz!",
            color=nextcord.Color.blue()
        )

        for category in QUIZ_CATEGORIES:
            async for session in get_session():
                quiz_service = QuizService(session)
                stats = await quiz_service.get_category_stats()
                category_stats = stats.get(category, {})
                
                value = f"Total questions: {category_stats.get('total_questions', 0)}\n"
                value += "Difficulty distribution:\n"
                for diff, count in category_stats.get('difficulty_distribution', {}).items():
                    value += f"• {diff}: {count}\n"
                
                embed.add_field(name=category, value=value, inline=True)

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

        async for session in get_session():
            quiz_service = QuizService(session)
            quiz = await quiz_service.get_random_quiz(category, difficulty)
            
            if not quiz:
                await ctx.send("❌ No quiz questions found with these criteria.")
                return

            await self.send_quiz(ctx, quiz)

    @quiz.command(name="stats")
    async def quiz_stats(self, ctx):
        """View your quiz statistics"""
        async for session in get_session():
            quiz_service = QuizService(session)
            stats = await quiz_service.get_user_stats(str(ctx.author.id))

            embed = nextcord.Embed(
                title=f"Quiz Statistics for {ctx.author.display_name}",
                color=nextcord.Color.blue()
            )
            
            embed.add_field(
                name="Overall Stats",
                value=f"""
                Total Attempts: {stats['total_attempts']}
                Correct Answers: {stats['correct_attempts']}
                Accuracy: {stats['accuracy']:.1f}%
                Average Time: {stats['average_time']}s
                """,
                inline=False
            )
            
            embed.add_field(
                name="Points",
                value=f"""
                Total Points: {stats['total_points']}
                Quiz Score: {stats['quiz_score']}
                """,
                inline=False
            )

            await ctx.send(embed=embed)

    @quiz.command(name="leaderboard")
    async def quiz_leaderboard(self, ctx):
        """Show quiz leaderboard"""
        async for session in get_session():
            quiz_service = QuizService(session)
            leaderboard = await quiz_service.get_leaderboard()

            embed = nextcord.Embed(
                title="Quiz Leaderboard",
                description="Top quiz performers",
                color=nextcord.Color.gold()
            )

            for i, entry in enumerate(leaderboard, 1):
                user = self.bot.get_user(int(entry['discord_id']))
                name = user.display_name if user else f"User {entry['discord_id']}"
                
                embed.add_field(
                    name=f"#{i} {name}",
                    value=f"""
                    Quiz Score: {entry['quiz_score']}
                    Total Points: {entry['total_points']}
                    """,
                    inline=False
                )

            await ctx.send(embed=embed)

    @quiz.command(name="daily")
    async def quiz_daily(self, ctx):
        """Take the daily challenge quiz"""
        async for session in get_session():
            quiz_service = QuizService(session)
            quiz, is_new = await quiz_service.get_daily_challenge()

            if not quiz:
                await ctx.send("❌ No daily challenge available right now.")
                return

            embed = nextcord.Embed(
                title="🌟 Daily Challenge 🌟",
                description="Test your knowledge with today's challenge!",
                color=nextcord.Color.gold()
            )
            await ctx.send(embed=embed)

            await self.send_quiz(ctx, quiz, is_daily=True)

    async def send_quiz(self, ctx, quiz, is_daily=False):
        """Send a quiz question and handle responses"""
        if str(ctx.author.id) in self.active_quizzes:
            await ctx.send("❌ You already have an active quiz! Complete it first.")
            return

        self.active_quizzes[str(ctx.author.id)] = quiz.id

        # Prepare answers
        wrong_answers = json.loads(quiz.wrong_answers)
        all_answers = [quiz.correct_answer] + wrong_answers
        random.shuffle(all_answers)
        correct_index = all_answers.index(quiz.correct_answer)

        # Create embed
        embed = nextcord.Embed(
            title=f"Quiz Question - {quiz.category}",
            description=quiz.question,
            color=nextcord.Color.blue()
        )

        # Add answers with letters
        answer_text = ""
        for i, answer in enumerate(all_answers):
            letter = chr(65 + i)  # A, B, C, D...
            answer_text += f"{letter}. {answer}\n"
        embed.add_field(name="Answers", value=answer_text, inline=False)

        if is_daily:
            embed.set_footer(text="⭐ This is today's daily challenge! ⭐")

        # Send question
        start_time = datetime.utcnow()
        question_msg = await ctx.send(embed=embed)

        # Add reaction options
        for i in range(len(all_answers)):
            await question_msg.add_reaction(chr(127462 + i))  # 🇦, 🇧, 🇨, 🇩...

        def check(reaction, user):
            return (user == ctx.author and
                   str(reaction.emoji) in [chr(127462 + i) for i in range(len(all_answers))])

        try:
            reaction, user = await self.bot.wait_for(
                'reaction_add',
                timeout=QUIZ_TIMEOUT_SECONDS,
                check=check
            )

            # Calculate time taken
            time_taken = (datetime.utcnow() - start_time).total_seconds()

            # Check if answer is correct
            user_answer_index = ord(str(reaction.emoji)[-1]) - 127462
            is_correct = user_answer_index == correct_index

            # Record attempt
            async for session in get_session():
                quiz_service = QuizService(session)
                await quiz_service.record_attempt(
                    str(ctx.author.id),
                    quiz.id,
                    is_correct,
                    time_taken
                )

            # Send result
            result_embed = nextcord.Embed(
                title="Quiz Result",
                description="✅ Correct!" if is_correct else "❌ Wrong!",
                color=nextcord.Color.green() if is_correct else nextcord.Color.red()
            )

            result_embed.add_field(
                name="Correct Answer",
                value=f"{chr(65 + correct_index)}. {quiz.correct_answer}",
                inline=False
            )

            if quiz.explanation:
                result_embed.add_field(
                    name="Explanation",
                    value=quiz.explanation,
                    inline=False
                )

            result_embed.add_field(
                name="Time Taken",
                value=f"{time_taken:.1f} seconds",
                inline=True
            )

            await ctx.send(embed=result_embed)

        except asyncio.TimeoutError:
            await ctx.send(f"⏰ Time's up! The correct answer was: {quiz.correct_answer}")

        finally:
            del self.active_quizzes[str(ctx.author.id)]

async def setup(bot):
    """Setup the Quiz cog"""
    await bot.add_cog(Quiz(bot))
    return True 