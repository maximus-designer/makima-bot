import discord
from discord.ext import commands, tasks
import asyncio
import logging
import os
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError

# Set up logging to log only errors
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class StickyBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()  # Ensure thread-safe operations

        # MongoDB connection setup
        mongo_uri = os.getenv('MONGO_URL')
        self.mongo_client = AsyncIOMotorClient(mongo_uri)
        self.db = self.mongo_client['sticky_bot_db']
        self.sticky_collection = self.db['sticky_messages']

        self.sticky_task.start()

        logging.info("StickyBot cog loaded successfully.")

    async def has_permissions(self, ctx):
        """Check if the bot has necessary permissions in the channel."""
        permissions = ctx.channel.permissions_for(ctx.guild.me)
        if not permissions.send_messages or not permissions.manage_messages or not permissions.read_messages:
            await ctx.send("The bot lacks necessary permissions (Send Messages, Manage Messages, Read Messages) in this channel.")
            return False
        return True

    @commands.command()
    async def stick(self, ctx, *, message):
        """Start or overwrite a sticky message in the channel."""
        if not ctx.author.guild_permissions.manage_messages:
            await ctx.send("You do not have permission to manage sticky messages.")
            return

        if not await self.has_permissions(ctx):
            return

        async with self.lock:  # Prevent concurrent modifications
            channel_id = ctx.channel.id

            # Check for existing sticky message
            existing_doc = await self.sticky_collection.find_one({'channel_id': channel_id})
            if existing_doc:
                confirmation_message = await ctx.send(
                    f"A sticky message already exists: `{existing_doc['message']}`.\n"
                    "React with ✅ to overwrite it with the new message or ❌ to keep the old message."
                )
                await confirmation_message.add_reaction('✅')
                await confirmation_message.add_reaction('❌')

                def reaction_check(reaction, user):
                    return user == ctx.author and str(reaction.emoji) in ['✅', '❌'] and reaction.message.id == confirmation_message.id

                try:
                    reaction, user = await self.bot.wait_for('reaction_add', timeout=30.0, check=reaction_check)
                    if str(reaction.emoji) == '❌':
                        await ctx.send("Keeping the old sticky message.")
                        return
                except asyncio.TimeoutError:
                    await ctx.send("You didn't react in time. Sticky message setup canceled.")
                    return

            # Prepare and save sticky message data
            sticky_data = {
                'channel_id': channel_id,
                'guild_id': ctx.guild.id,
                'message': message,
                'last_posted': None,
                'last_message_id': None
            }
            await self.sticky_collection.update_one(
                {'channel_id': channel_id},
                {'$set': sticky_data},
                upsert=True
            )
            await ctx.send(f"Sticky message set for this channel: {message}")

    @commands.command()
    async def stickstop(self, ctx):
        """Stop the sticky message in the channel."""
        if not ctx.author.guild_permissions.manage_messages:
            await ctx.send("You do not have permission to stop the sticky message.")
            return

        if not await self.has_permissions(ctx):
            return

        async with self.lock:
            channel_id = ctx.channel.id
            result = await self.sticky_collection.delete_one({'channel_id': channel_id})

            if result.deleted_count > 0:
                await ctx.send("Sticky message stopped.")
            else:
                await ctx.send("There is no sticky message in this channel.")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Repost sticky message when a new message is sent in the channel."""
        # Ignore messages from the bot itself
        if message.author == self.bot.user:
            return

        # Ignore DMs
        if not message.guild:
            return

        # Check if the bot has the required permissions before posting
        permissions = message.channel.permissions_for(message.guild.me)
        if not permissions.send_messages or not permissions.manage_messages:
            logging.error(f"Bot does not have required permissions in channel {message.channel.id}")
            return

        # Fetch sticky message data from MongoDB
        sticky_doc = await self.sticky_collection.find_one({'channel_id': message.channel.id})

        if sticky_doc:
            async with self.lock:
                # Check if necessary fields exist in the document
                if 'message' not in sticky_doc or 'channel_id' not in sticky_doc:
                    logging.error(f"Sticky message document missing necessary fields: {sticky_doc}")
                    return

                # Delete previous sticky message if it exists
                last_message_id = sticky_doc.get('last_message_id')
                if last_message_id:
                    try:
                        last_message = await message.channel.fetch_message(last_message_id)
                        if last_message.author == self.bot.user:
                            await last_message.delete()
                    except (discord.NotFound, discord.Forbidden):
                        pass
                    except Exception as e:
                        logging.error(f"Error deleting previous sticky message: {str(e)}")

                # Send new sticky message
                try:
                    sticky_message = await message.channel.send(sticky_doc['message'])

                    # Update sticky data in MongoDB
                    await self.sticky_collection.update_one(
                        {'channel_id': message.channel.id},
                        {'$set': {
                            'last_message_id': sticky_message.id,
                            'last_posted': discord.utils.utcnow().isoformat()
                        }}
                    )
                except Exception as e:
                    logging.error(f"Error sending sticky message: {str(e)}")

    @tasks.loop(seconds=60)
    async def sticky_task(self):
        """Task to repost sticky messages every 1 minute."""
        async for document in self.sticky_collection.find():
            try:
                # Ensure document contains the necessary fields before processing
                if 'channel_id' not in document or 'message' not in document:
                    logging.error(f"Skipping invalid sticky message document: {document}")
                    continue

                channel_id = document['channel_id']
                channel = self.bot.get_channel(channel_id)

                if not channel:
                    # Remove sticky data for non-existent channels
                    await self.sticky_collection.delete_one({'channel_id': channel_id})
                    continue

                # Delete previous sticky message
                last_message_id = document.get('last_message_id')
                if last_message_id:
                    try:
                        last_message = await channel.fetch_message(last_message_id)
                        if last_message.author == self.bot.user:
                            await last_message.delete()
                    except discord.NotFound:
                        pass

                # Send new sticky message
                sticky_message = await channel.send(document['message'])

                # Update sticky data in MongoDB
                await self.sticky_collection.update_one(
                    {'channel_id': channel_id},
                    {'$set': {
                        'last_message_id': sticky_message.id,
                        'last_posted': discord.utils.utcnow().isoformat()
                    }}
                )

            except discord.Forbidden:
                logging.error(f"Failed to post sticky message in channel {channel_id}. Missing permissions.")
            except Exception as e:
                logging.error(f"Error processing sticky message document: {e}")
                logging.error(f"Problematic document: {document}")

    @sticky_task.before_loop
    async def before_sticky_task(self):
        await self.bot.wait_until_ready()

    def cog_unload(self):
        """Stop the sticky task loop when the bot shuts down."""
        if self.sticky_task.is_running():
            self.sticky_task.cancel()
        self.mongo_client.close()

# Add the cog to the bot
async def setup(bot):
    await bot.add_cog(StickyBot(bot))
    logging.info("StickyBot cog loaded successfully.")
