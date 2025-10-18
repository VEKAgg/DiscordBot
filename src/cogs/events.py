import nextcord
from nextcord.ext import commands, tasks
import logging
from datetime import datetime, timedelta
import aiohttp
import asyncio
from typing import List, Dict, Optional
import icalendar
import pytz
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from timezonefinder import TimezoneFinder

logger = logging.getLogger('VEKA.events')

class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.mongo
        self.events = self.db.events
        self.event_registrations = self.db.event_registrations
        self.user_locations = self.db.user_locations
        self.geolocator = Nominatim(user_agent="veka_discord_bot")
        self.tf = TimezoneFinder()
        self.check_upcoming_events.start()

    def cog_unload(self):
        self.check_upcoming_events.cancel()

    async def get_user_timezone(self, user_id: str) -> str:
        """Get user's timezone based on their location"""
        location = await self.user_locations.find_one({"user_id": user_id})
        if location and "coordinates" in location:
            lat, lon = location["coordinates"]
            return self.tf.timezone_at(lat=lat, lng=lon) or "UTC"
        return "UTC"

    @tasks.loop(minutes=5)
    async def check_upcoming_events(self):
        """Check and send notifications for upcoming events"""
        try:
            now = datetime.utcnow()
            upcoming = await self.events.find({
                "start_time": {
                    "$gt": now,
                    "$lt": now + timedelta(minutes=30)
                },
                "notified": {"$ne": True}
            }).to_list(length=None)

            for event in upcoming:
                # Get registered users
                registrations = await self.event_registrations.find({
                    "event_id": str(event["_id"]),
                    "status": "confirmed"
                }).to_list(length=None)

                # Send notifications
                for reg in registrations:
                    user = self.bot.get_user(int(reg["user_id"]))
                    if user:
                        user_tz = pytz.timezone(await self.get_user_timezone(reg["user_id"]))
                        local_time = pytz.utc.localize(event["start_time"]).astimezone(user_tz)
                        
                        embed = nextcord.Embed(
                            title="🎯 Upcoming Event Reminder",
                            description=f"Event '{event['title']}' starts in {(event['start_time'] - now).minutes} minutes!",
                            color=nextcord.Color.blue()
                        )
                        embed.add_field(
                            name="Time",
                            value=local_time.strftime("%I:%M %p %Z"),
                            inline=False
                        )
                        if "location" in event:
                            embed.add_field(
                                name="Location",
                                value=event["location"],
                                inline=False
                            )
                        try:
                            await user.send(embed=embed)
                        except nextcord.Forbidden:
                            pass

                # Mark as notified
                await self.events.update_one(
                    {"_id": event["_id"]},
                    {"$set": {"notified": True}}
                )

        except Exception as e:
            logger.error(f"Error checking upcoming events: {str(e)}")

    @commands.group(invoke_without_command=True)
    async def event(self, ctx):
        """Event management commands"""
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title="📅 Event Commands",
                description="Manage and participate in events",
                color=nextcord.Color.blue()
            )
            embed.add_field(
                name="Available Commands",
                value="""
                `!event create` - Create a new event
                `!event list` - List upcoming events
                `!event info <id>` - Get event details
                `!event register <id>` - Register for an event
                `!event unregister <id>` - Unregister from an event
                `!event location <address>` - Set your location for local events
                `!event nearby [radius]` - Find events near you
                """,
                inline=False
            )
            await ctx.send(embed=embed)

    @event.command(name="create")
    @commands.has_permissions(manage_events=True)
    async def event_create(self, ctx):
        """Create a new event interactively"""
        try:
            # Start event creation process
            await ctx.send("Let's create a new event! First, what's the title? (Type 'cancel' to cancel)")
            
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            # Get title
            try:
                msg = await self.bot.wait_for('message', timeout=60.0, check=check)
                if msg.content.lower() == 'cancel':
                    await ctx.send("Event creation cancelled.")
                    return
                title = msg.content
            except asyncio.TimeoutError:
                await ctx.send("Event creation timed out.")
                return

            # Get description
            await ctx.send("Great! Now provide a description of the event:")
            try:
                msg = await self.bot.wait_for('message', timeout=120.0, check=check)
                if msg.content.lower() == 'cancel':
                    await ctx.send("Event creation cancelled.")
                    return
                description = msg.content
            except asyncio.TimeoutError:
                await ctx.send("Event creation timed out.")
                return

            # Get date and time
            await ctx.send("When will the event start? (Format: YYYY-MM-DD HH:MM)")
            while True:
                try:
                    msg = await self.bot.wait_for('message', timeout=60.0, check=check)
                    if msg.content.lower() == 'cancel':
                        await ctx.send("Event creation cancelled.")
                        return
                    start_time = datetime.strptime(msg.content, "%Y-%m-%d %H:%M")
                    if start_time < datetime.now():
                        await ctx.send("Start time must be in the future. Please try again:")
                        continue
                    break
                except (ValueError, asyncio.TimeoutError):
                    await ctx.send("Invalid format. Please use YYYY-MM-DD HH:MM:")

            # Get location (optional)
            await ctx.send("Enter the event location (or 'skip' for online events):")
            try:
                msg = await self.bot.wait_for('message', timeout=60.0, check=check)
                location = None
                coordinates = None
                if msg.content.lower() not in ['skip', 'cancel']:
                    location = msg.content
                    # Try to geocode the location
                    try:
                        loc = self.geolocator.geocode(location)
                        if loc:
                            coordinates = [loc.latitude, loc.longitude]
                    except Exception as e:
                        logger.error(f"Error geocoding location: {str(e)}")
                elif msg.content.lower() == 'cancel':
                    await ctx.send("Event creation cancelled.")
                    return
            except asyncio.TimeoutError:
                await ctx.send("Event creation timed out.")
                return

            # Get capacity (optional)
            await ctx.send("Enter the maximum number of participants (or 'skip' for unlimited):")
            try:
                msg = await self.bot.wait_for('message', timeout=60.0, check=check)
                capacity = None
                if msg.content.lower() not in ['skip', 'cancel']:
                    try:
                        capacity = int(msg.content)
                        if capacity <= 0:
                            await ctx.send("Capacity must be positive. Setting to unlimited.")
                            capacity = None
                    except ValueError:
                        await ctx.send("Invalid number. Setting capacity to unlimited.")
                elif msg.content.lower() == 'cancel':
                    await ctx.send("Event creation cancelled.")
                    return
            except asyncio.TimeoutError:
                await ctx.send("Event creation timed out.")
                return

            # Create the event
            event = {
                "title": title,
                "description": description,
                "start_time": start_time,
                "creator_id": str(ctx.author.id),
                "guild_id": str(ctx.guild.id),
                "created_at": datetime.utcnow(),
                "status": "scheduled"
            }
            if location:
                event["location"] = location
            if coordinates:
                event["coordinates"] = coordinates
            if capacity:
                event["capacity"] = capacity

            result = await self.events.insert_one(event)

            # Send confirmation
            embed = nextcord.Embed(
                title="✅ Event Created",
                description=f"Event '{title}' has been created!",
                color=nextcord.Color.green()
            )
            embed.add_field(
                name="ID",
                value=str(result.inserted_id),
                inline=False
            )
            embed.add_field(
                name="Time",
                value=start_time.strftime("%Y-%m-%d %H:%M"),
                inline=False
            )
            if location:
                embed.add_field(
                    name="Location",
                    value=location,
                    inline=False
                )
            if capacity:
                embed.add_field(
                    name="Capacity",
                    value=str(capacity),
                    inline=False
                )
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error creating event: {str(e)}")
            await ctx.send("An error occurred while creating the event.")

    @event.command(name="list")
    async def event_list(self, ctx):
        """List upcoming events"""
        try:
            # Get upcoming events
            events = await self.events.find({
                "guild_id": str(ctx.guild.id),
                "start_time": {"$gt": datetime.utcnow()},
                "status": "scheduled"
            }).sort("start_time", 1).to_list(length=None)

            if not events:
                await ctx.send("No upcoming events scheduled!")
                return

            # Create embed
            embed = nextcord.Embed(
                title="📅 Upcoming Events",
                color=nextcord.Color.blue()
            )

            for event in events:
                # Get registration count
                reg_count = await self.event_registrations.count_documents({
                    "event_id": str(event["_id"]),
                    "status": "confirmed"
                })

                value = f"""
                Time: {event['start_time'].strftime('%Y-%m-%d %H:%M')}
                {f"Location: {event['location']}" if 'location' in event else 'Location: Online'}
                Registered: {reg_count}{f'/{event["capacity"]}' if 'capacity' in event else ''}
                ID: {event['_id']}
                """
                embed.add_field(
                    name=event["title"],
                    value=value,
                    inline=False
                )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error listing events: {str(e)}")
            await ctx.send("An error occurred while listing events.")

    @event.command(name="info")
    async def event_info(self, ctx, event_id: str):
        """Get detailed information about an event"""
        try:
            # Get event
            event = await self.events.find_one({"_id": event_id})
            if not event:
                await ctx.send("Event not found!")
                return

            # Get registrations
            registrations = await self.event_registrations.find({
                "event_id": event_id,
                "status": "confirmed"
            }).to_list(length=None)

            # Create embed
            embed = nextcord.Embed(
                title=event["title"],
                description=event["description"],
                color=nextcord.Color.blue()
            )

            embed.add_field(
                name="Time",
                value=event["start_time"].strftime("%Y-%m-%d %H:%M"),
                inline=False
            )

            if "location" in event:
                embed.add_field(
                    name="Location",
                    value=event["location"],
                    inline=False
                )

            creator = self.bot.get_user(int(event["creator_id"]))
            embed.add_field(
                name="Created by",
                value=creator.mention if creator else "Unknown",
                inline=False
            )

            reg_list = []
            for reg in registrations:
                user = self.bot.get_user(int(reg["user_id"]))
                if user:
                    reg_list.append(user.mention)

            if reg_list:
                embed.add_field(
                    name=f"Registered ({len(reg_list)}{f'/{event['capacity']}' if 'capacity' in event else ''})",
                    value="\n".join(reg_list[:10]) + (f"\n...and {len(reg_list)-10} more" if len(reg_list) > 10 else ""),
                    inline=False
                )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error getting event info: {str(e)}")
            await ctx.send("An error occurred while getting event information.")

    @event.command(name="register")
    async def event_register(self, ctx, event_id: str):
        """Register for an event"""
        try:
            # Get event
            event = await self.events.find_one({"_id": event_id})
            if not event:
                await ctx.send("Event not found!")
                return

            # Check if event is in the future
            if event["start_time"] < datetime.utcnow():
                await ctx.send("This event has already started or ended!")
                return

            # Check if already registered
            existing = await self.event_registrations.find_one({
                "event_id": event_id,
                "user_id": str(ctx.author.id)
            })
            if existing and existing["status"] == "confirmed":
                await ctx.send("You're already registered for this event!")
                return

            # Check capacity
            if "capacity" in event:
                reg_count = await self.event_registrations.count_documents({
                    "event_id": event_id,
                    "status": "confirmed"
                })
                if reg_count >= event["capacity"]:
                    await ctx.send("Sorry, this event is at full capacity!")
                    return

            # Register user
            registration = {
                "event_id": event_id,
                "user_id": str(ctx.author.id),
                "status": "confirmed",
                "registered_at": datetime.utcnow()
            }
            await self.event_registrations.insert_one(registration)

            # Send confirmation
            user_tz = pytz.timezone(await self.get_user_timezone(str(ctx.author.id)))
            local_time = pytz.utc.localize(event["start_time"]).astimezone(user_tz)

            embed = nextcord.Embed(
                title="✅ Registration Confirmed",
                description=f"You're registered for '{event['title']}'!",
                color=nextcord.Color.green()
            )
            embed.add_field(
                name="Time",
                value=local_time.strftime("%Y-%m-%d %I:%M %p %Z"),
                inline=False
            )
            if "location" in event:
                embed.add_field(
                    name="Location",
                    value=event["location"],
                    inline=False
                )
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error registering for event: {str(e)}")
            await ctx.send("An error occurred while registering for the event.")

    @event.command(name="unregister")
    async def event_unregister(self, ctx, event_id: str):
        """Unregister from an event"""
        try:
            # Get event
            event = await self.events.find_one({"_id": event_id})
            if not event:
                await ctx.send("Event not found!")
                return

            # Check if registered
            result = await self.event_registrations.delete_one({
                "event_id": event_id,
                "user_id": str(ctx.author.id),
                "status": "confirmed"
            })

            if result.deleted_count > 0:
                await ctx.send(f"You've been unregistered from '{event['title']}'")
            else:
                await ctx.send("You weren't registered for this event!")

        except Exception as e:
            logger.error(f"Error unregistering from event: {str(e)}")
            await ctx.send("An error occurred while unregistering from the event.")

    @event.command(name="location")
    async def event_location(self, ctx, *, address: str):
        """Set your location for local events"""
        try:
            # Geocode the address
            location = self.geolocator.geocode(address)
            if not location:
                await ctx.send("Could not find that location. Please try a different address.")
                return

            # Save user location
            await self.user_locations.update_one(
                {"user_id": str(ctx.author.id)},
                {
                    "$set": {
                        "address": address,
                        "coordinates": [location.latitude, location.longitude],
                        "updated_at": datetime.utcnow()
                    }
                },
                upsert=True
            )

            # Get timezone for the location
            timezone = self.tf.timezone_at(lat=location.latitude, lng=location.longitude)

            embed = nextcord.Embed(
                title="📍 Location Updated",
                description=f"Your location has been set to: {location.address}",
                color=nextcord.Color.green()
            )
            if timezone:
                embed.add_field(
                    name="Timezone",
                    value=timezone,
                    inline=False
                )
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error setting user location: {str(e)}")
            await ctx.send("An error occurred while setting your location.")

    @event.command(name="nearby")
    async def event_nearby(self, ctx, radius: int = 50):
        """Find events near your location"""
        try:
            # Get user's location
            user_location = await self.user_locations.find_one({"user_id": str(ctx.author.id)})
            if not user_location or "coordinates" not in user_location:
                await ctx.send("Please set your location first using `!event location <address>`")
                return

            # Get upcoming events with locations
            events = await self.events.find({
                "start_time": {"$gt": datetime.utcnow()},
                "status": "scheduled",
                "coordinates": {"$exists": True}
            }).to_list(length=None)

            if not events:
                await ctx.send("No upcoming events with locations found!")
                return

            # Filter events by distance
            nearby_events = []
            user_coords = tuple(user_location["coordinates"])
            
            for event in events:
                event_coords = tuple(event["coordinates"])
                distance = geodesic(user_coords, event_coords).miles
                if distance <= radius:
                    event["distance"] = distance
                    nearby_events.append(event)

            if not nearby_events:
                await ctx.send(f"No events found within {radius} miles of your location.")
                return

            # Sort by distance