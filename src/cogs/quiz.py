import nextcord
from nextcord.ext import commands
import logging
import random
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
                title="🧠 Quiz Commands",
                description="Test your knowledge with our quiz system!",
                color=nextcord.Color.orange()
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
            title="📊 Quiz Categories",
            description="Here are all available quiz categories and their statistics:",
            color=nextcord.Color.orange()
        )

        for category, data in stats.items():
            difficulties = ', '.join(data['difficulty_distribution'].keys()) or 'None yet'
            embed.add_field(
                name=category,
                value=f"**Questions:** {data['total_questions']}\n**Difficulties:** {difficulties}",
                inline=True
            )

        await ctx.send(embed=embed)

    @quiz.command(name="start")
    async def quiz_start(self, ctx, category: str = None, difficulty: str = None):
        """Start a quiz with optional category and difficulty"""
        # Check if user is already in a quiz
        if str(ctx.author.id) in self.active_quizzes:
            await ctx.send("⚠️ You're already in an active quiz! Finish it first or wait for it to expire.")
            return
            
        quiz = await self.quiz_service.get_random_quiz(category, difficulty)
        if not quiz:
            categories_list = ", ".join([f"`{c}`" for c in QUIZ_CATEGORIES])
            difficulties_list = ", ".join([f"`{d}`" for d in QUIZ_DIFFICULTY_LEVELS])
            
            await ctx.send(f"❌ No quiz found with those parameters. Available categories: {categories_list}\nDifficulty levels: {difficulties_list}")
            return
            
        await self.send_quiz(ctx, quiz)

    @quiz.command(name="stats")
    async def quiz_stats(self, ctx):
        """View your quiz statistics"""
        stats = await self.quiz_service.get_user_stats(ctx.author.id)
        
        embed = nextcord.Embed(
            title=f"📈 Quiz Statistics for {ctx.author.display_name}",
            color=nextcord.Color.orange()
        )
        
        # Overall stats
        embed.add_field(
            name="🏆 Overall",
            value=f"**Total Quizzes:** {stats['total_quizzes']}\n"
                  f"**Correct Answers:** {stats['correct_answers']}\n"
                  f"**Accuracy:** {stats['accuracy']}%\n"
                  f"**Points Earned:** {stats['points']}",
            inline=False
        )
        
        # Category breakdown
        if stats['categories']:
            categories_value = ""
            for category, cat_stats in stats['categories'].items():
                categories_value += f"**{category.capitalize()}:** {cat_stats['correct']}/{cat_stats['total']} ({cat_stats['percentage']}%)\n"
            
            embed.add_field(
                name="📊 Categories",
                value=categories_value,
                inline=False
            )
        
        # Recent activity
        if stats['recent_quizzes']:
            recent_value = ""
            for quiz in stats['recent_quizzes']:
                result = "✅ Correct" if quiz['correct'] else "❌ Incorrect"
                recent_value += f"**{quiz['category'].capitalize()} ({quiz['difficulty']}):** {result}\n"
            
            embed.add_field(
                name="🕒 Recent Quizzes",
                value=recent_value,
                inline=False
            )
        
        embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url)
        await ctx.send(embed=embed)

    @quiz.command(name="leaderboard")
    async def quiz_leaderboard(self, ctx):
        """View the quiz leaderboard"""
        leaderboard = await self.quiz_service.get_leaderboard()
        
        embed = nextcord.Embed(
            title="🏆 Quiz Leaderboard",
            description="Top quiz performers in the server",
            color=nextcord.Color.orange()
        )
        
        if not leaderboard:
            embed.add_field(name="No Data", value="No quiz data available yet!")
        else:
            value = ""
            for i, entry in enumerate(leaderboard):
                medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
                user = ctx.guild.get_member(int(entry['discord_id']))
                username = user.display_name if user else "Unknown User"
                value += f"{medal} **{username}** - {entry['correct_answers']} correct ({entry['accuracy']}% accuracy)\n"
            
            embed.add_field(name="Top Performers", value=value, inline=False)
        
        await ctx.send(embed=embed)

    @quiz.command(name="daily")
    async def quiz_daily(self, ctx):
        """Take the daily quiz challenge"""
        # Check if user already took the daily quiz
        if await self.quiz_service.check_daily_taken(ctx.author.id):
            next_reset = await self.quiz_service.get_time_until_next_daily()
            await ctx.send(f"⏳ You've already taken today's daily quiz! Next quiz available in {next_reset}.")
            return
            
        quiz = await self.quiz_service.get_daily_quiz()
        if not quiz:
            await ctx.send("❌ No daily quiz available today. Please try again later!")
            return
            
        await self.send_quiz(ctx, quiz, is_daily=True)

    async def send_quiz(self, ctx, quiz, is_daily=False):
        """Send a quiz to the channel and handle responses"""
        self.active_quizzes[str(ctx.author.id)] = quiz['id']

        all_answers = [quiz['correct_answer']] + list(quiz['wrong_answers'])
        random.shuffle(all_answers)
        
        # Create the quiz embed
        embed = nextcord.Embed(
            title=f"{'🌟 Daily Quiz Challenge' if is_daily else '🧠 Quiz Question'} - {quiz['category'].capitalize()} ({quiz['difficulty'].capitalize()})",
            description=quiz['question'],
            color=nextcord.Color.orange()
        )
        
        # Add the answers as fields
        for i, answer in enumerate(all_answers):
            embed.add_field(
                name=f"Option {chr(65+i)}", # A, B, C, D...
                value=answer,
                inline=False
            )
        
        embed.set_footer(text="React with the letter corresponding to your answer.")
        
        # Send the quiz and add reaction options
        quiz_message = await ctx.send(embed=embed)
        
        # Add reactions for each answer
        reactions = ['🇦', '🇧', '🇨', '🇩', '🇪'][:len(all_answers)]
        for reaction in reactions:
            await quiz_message.add_reaction(reaction)
        
        def check(reaction, user):
            return (
                user.id == ctx.author.id and 
                reaction.message.id == quiz_message.id and
                str(reaction.emoji) in reactions
            )
        
        try:
            # Wait for user's reaction
            reaction, user = await self.bot.wait_for('reaction_add', timeout=60.0, check=check)
            
            # Get the index of the selected answer
            selected_index = reactions.index(str(reaction.emoji))
            selected_answer = all_answers[selected_index]
            
            # Check if the answer is correct
            is_correct = selected_answer == quiz['correct_answer']
            
            # Create result embed
            result_embed = nextcord.Embed(
                title="Quiz Result",
                description=f"**Question:** {quiz['question']}\n\n**Your answer:** {selected_answer}",
                color=nextcord.Color.green() if is_correct else nextcord.Color.red()
            )
            
            if is_correct:
                result_embed.add_field(
                    name="✅ Correct!",
                    value="Well done! You got it right.",
                    inline=False
                )
            else:
                result_embed.add_field(
                    name="❌ Incorrect",
                    value=f"The correct answer was: **{quiz['correct_answer']}**",
                    inline=False
                )
            
            if quiz.get('explanation'):
                result_embed.add_field(
                    name="📝 Explanation",
                    value=quiz['explanation'],
                    inline=False
                )
            
            # Record the result
            points = await self.quiz_service.record_quiz_attempt(
                ctx.author.id,
                quiz['id'],
                is_correct,
                is_daily
            )
            
            if points > 0:
                result_embed.add_field(
                    name="🏆 Points Earned",
                    value=f"You earned **{points}** points!",
                    inline=False
                )
            
            await ctx.send(embed=result_embed)
            
        except asyncio.TimeoutError:
            await ctx.send(f"⏱️ Time's up, {ctx.author.mention}! The quiz has expired.")
        finally:
            # Remove user from active quizzes
            if str(ctx.author.id) in self.active_quizzes:
                del self.active_quizzes[str(ctx.author.id)]
            
            # Try to remove reactions
            try:
                await quiz_message.clear_reactions()
            except:
                pass

    @quiz.command(name="add")
    @commands.has_permissions(administrator=True)
    async def quiz_add(self, ctx):
        """Add a new quiz question (Admin only)"""
        try:
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            # Get category
            categories_list = ", ".join([f"`{c}`" for c in QUIZ_CATEGORIES])
            await ctx.send(f"📚 Select a category ({categories_list}):")
            cat_msg = await self.bot.wait_for('message', check=check, timeout=60)
            category = cat_msg.content
            if category not in QUIZ_CATEGORIES:
                await ctx.send(f"❌ Invalid category. Must be one of: {categories_list}")
                return

            # Get difficulty
            difficulties_list = ", ".join([f"`{d}`" for d in QUIZ_DIFFICULTY_LEVELS])
            await ctx.send(f"📊 Select difficulty ({difficulties_list}):")
            diff_msg = await self.bot.wait_for('message', check=check, timeout=60)
            difficulty = diff_msg.content
            if difficulty not in QUIZ_DIFFICULTY_LEVELS:
                await ctx.send(f"❌ Invalid difficulty. Must be one of: {difficulties_list}")
                return

            # Get question
            await ctx.send("❓ Enter the quiz question:")
            q_msg = await self.bot.wait_for('message', check=check, timeout=120)
            question = q_msg.content

            # Get correct answer
            await ctx.send("✅ Enter the correct answer:")
            ans_msg = await self.bot.wait_for('message', check=check, timeout=60)
            correct_answer = ans_msg.content

            # Get wrong answers
            await ctx.send("❌ Enter wrong answers (comma-separated):")
            wrong_msg = await self.bot.wait_for('message', check=check, timeout=120)
            wrong_answers = [a.strip() for a in wrong_msg.content.split(",") if a.strip()]
            if len(wrong_answers) < 1:
                await ctx.send("❌ Need at least 1 wrong answer.")
                return

            # Get explanation (optional)
            await ctx.send("📝 Enter explanation (optional, type 'skip' to skip):")
            exp_msg = await self.bot.wait_for('message', check=check, timeout=120)
            explanation = None if exp_msg.content.lower() == 'skip' else exp_msg.content

            # Create quiz
            quiz = await self.quiz_service.create_quiz(
                category, difficulty, question, correct_answer, wrong_answers, explanation
            )

            embed = nextcord.Embed(
                title="✅ Quiz Added",
                description="New quiz question has been added successfully!",
                color=nextcord.Color.green()
            )
            embed.add_field(name="Category", value=category, inline=True)
            embed.add_field(name="Difficulty", value=difficulty, inline=True)
            embed.add_field(name="Question", value=question[:100] + "..." if len(question) > 100 else question, inline=False)
            await ctx.send(embed=embed)

        except asyncio.TimeoutError:
            await ctx.send("⏱️ Quiz creation timed out.")
        except Exception as e:
            logger.error(f"Error adding quiz: {str(e)}")
            await ctx.send("❌ An error occurred while adding the quiz.")

    @quiz.command(name="delete")
    @commands.has_permissions(administrator=True)
    async def quiz_delete(self, ctx, quiz_id: int):
        """Delete a quiz question (Admin only)"""
        try:
            from src.database.database import db
            result = await db.execute("DELETE FROM quizzes WHERE id = $1", quiz_id)
            if result == "DELETE 1":
                await ctx.send(f"✅ Quiz `{quiz_id}` has been deleted.")
            else:
                await ctx.send(f"❌ Quiz `{quiz_id}` not found.")
        except Exception as e:
            logger.error(f"Error deleting quiz: {e}")
            await ctx.send("❌ An error occurred while deleting the quiz.")

    @quiz.command(name="admin")
    @commands.has_permissions(administrator=True)
    async def quiz_admin(self, ctx):
        """Show admin quiz commands"""
        embed = nextcord.Embed(
            title="🔧 Quiz Admin Commands",
            description="Admin-only commands for managing quizzes",
            color=nextcord.Color.blue()
        )
        embed.add_field(
            name="Available Commands",
            value="""
            `!quiz add` - Add a new quiz question
            `!quiz delete <quiz_id>` - Delete a quiz by ID
            """,
            inline=False
        )
        await ctx.send(embed=embed)

def setup(bot):
    """Setup the Quiz cog"""
    if bot is not None:
        bot.add_cog(Quiz(bot))
        logging.getLogger('VEKA').info("Loaded cog: src.cogs.quiz")
    else:
        logging.getLogger('VEKA').error("Bot is None in Quiz cog setup")
