import discord
from discord.ext import commands, tasks
import json
import asyncio
import logging
import os
from typing import Dict, Optional

# Improved logging configuration
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('sticky_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class StickyBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sticky_data: Dict[str, Dict[str, Optional[str]]] = self.load_sticky_data()
        self.lock = asyncio.Lock()  # Thread-safe operations
        self.sticky_task.start()

    def load_sticky_data(self) -> Dict[str, Dict[str, Optional[str]]]:
        """
        Load sticky message data from storage with robust error handling.
        
        Returns:
            Dict containing sticky message configurations
        """
        try:
            os.makedirs('data', exist_ok=True)  # Ensure data directory exists
            file_path = 'data/sticky_data.json'
            
            # Create file if not exists
            if not os.path.exists(file_path):
                with open(file_path, 'w') as file:
                    json.dump({}, file)
            
            # Read and parse data
            with open(file_path, 'r') as file:
                data = json.load(file)
                # Validate data structure
                return {str(k): v for k, v in data.items() 
                        if isinstance(v, dict) and 'message' in v}
        
        except (FileNotFoundError, PermissionError, json.JSONDecodeError) as e:
            logger.error(f"Error loading sticky data: {e}")
            return {}

    def save_sticky_data(self) -> None:
        """
        Save sticky message data with enhanced error handling.
        Ensures atomic write and provides detailed logging.
        """
        try:
            file_path = 'data/sticky_data.json'
            temp_path = 'data/sticky_data_temp.json'
            
            # Write to temporary file first
            with open(temp_path, 'w') as temp_file:
                json.dump(self.sticky_data, temp_file, indent=4)
            
            # Atomic replace
            os.replace(temp_path, file_path)
            logger.info("Sticky data saved successfully")
        
        except Exception as e:
            logger.error(f"Failed to save sticky data: {e}")

    async def _validate_bot_permissions(self, ctx: commands.Context) -> bool:
        """
        Comprehensive permission validation with detailed feedback.
        
        Args:
            ctx: Command context
        
        Returns:
            bool indicating if bot has required permissions
        """
        required_permissions = [
            'send_messages', 
            'manage_messages', 
            'read_messages'
        ]
        
        missing_perms = [
            perm for perm in required_permissions 
            if not getattr(ctx.channel.permissions_for(ctx.guild.me), perm)
        ]
        
        if missing_perms:
            await ctx.send(f"Missing bot permissions: {', '.join(missing_perms)}")
            return False
        
        return True

    @commands.command(name='stick')
    @commands.has_permissions(manage_messages=True)
    async def stick_command(self, ctx: commands.Context, *, message: str):
        """
        Set or update a sticky message in the current channel.
        
        Args:
            ctx: Command context
            message: Sticky message content
        """
        if not await self._validate_bot_permissions(ctx):
            return

        async with self.lock:
            channel_id = str(ctx.channel.id)
            
            # Confirmation for overwriting existing sticky
            if channel_id in self.sticky_data:
                confirm_msg = await ctx.send(
                    f"Overwrite existing sticky: `{self.sticky_data[channel_id]['message']}`? "
                    "React with ✅ to confirm or ❌ to cancel."
                )
                await confirm_msg.add_reaction('✅')
                await confirm_msg.add_reaction('❌')

                try:
                    reaction, user = await self.bot.wait_for(
                        'reaction_add', 
                        timeout=30.0, 
                        check=lambda r, u: u == ctx.author and str(r.emoji) in ['✅', '❌']
                    )
                    
                    if str(reaction.emoji) == '❌':
                        await ctx.send("Sticky message update cancelled.")
                        return

                except asyncio.TimeoutError:
                    await ctx.send("No response. Sticky message update cancelled.")
                    return

            # Set/update sticky message
            self.sticky_data[channel_id] = {
                'message': message,
                'last_posted': None,
                'last_message_id': None
            }
            self.save_sticky_data()
            await ctx.send(f"Sticky message set: {message}")

    @commands.command(name='stickstop')
    @commands.has_permissions(manage_messages=True)
    async def stop_sticky(self, ctx: commands.Context):
        """
        Stop and remove the sticky message for the current channel.
        """
        if not await self._validate_bot_permissions(ctx):
            return

        async with self.lock:
            channel_id = str(ctx.channel.id)
            if channel_id in self.sticky_data:
                del self.sticky_data[channel_id]
                self.save_sticky_data()
                await ctx.send("Sticky message stopped and removed.")
            else:
                await ctx.send("No active sticky message in this channel.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Repost sticky message when a new message is sent in the channel.
        
        Args:
            message: The message that triggered the event
        """
        # Ignore bot's own messages and commands
        if message.author == self.bot.user or message.content.startswith(self.bot.command_prefix):
            return

        channel_id = str(message.channel.id)
        async with self.lock:
            if channel_id in self.sticky_data:
                data = self.sticky_data[channel_id]
                
                # Delete previous sticky message safely
                try:
                    if data.get('last_message_id'):
                        try:
                            previous_sticky = await message.channel.fetch_message(data['last_message_id'])
                            if previous_sticky.author == self.bot.user:
                                await previous_sticky.delete()
                        except discord.NotFound:
                            pass  # Message already deleted
                except discord.Forbidden:
                    logger.warning(f"Cannot delete previous sticky in {channel_id}")

                # Send new sticky message
                try:
                    new_sticky = await message.channel.send(data['message'])
                    self.sticky_data[channel_id].update({
                        'last_message_id': new_sticky.id,
                        'last_posted': discord.utils.utcnow().isoformat()
                    })
                    self.save_sticky_data()
                except discord.Forbidden:
                    logger.error(f"Cannot send sticky in {channel_id}")

    @tasks.loop(minutes=5)
    async def sticky_task(self):
        """
        Background task to periodically repost sticky messages.
        Handles channel deletion and permission issues.
        """
        async with self.lock:
            for channel_id, data in list(self.sticky_data.items()):
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if not channel:
                        del self.sticky_data[channel_id]
                        continue

                    # Repost sticky message
                    sticky_message = await channel.send(data['message'])
                    self.sticky_data[channel_id].update({
                        'last_message_id': sticky_message.id,
                        'last_posted': discord.utils.utcnow().isoformat()
                    })
                    self.save_sticky_data()

                except discord.Forbidden:
                    logger.error(f"Cannot post sticky in channel {channel_id}")
                except Exception as e:
                    logger.error(f"Sticky task error in {channel_id}: {e}")

    @sticky_task.before_loop
    async def before_sticky_task(self):
        """Ensure bot is ready before starting sticky task."""
        await self.bot.wait_until_ready()

    def cog_unload(self):
        """Gracefully stop the sticky task on cog unload."""
        self.sticky_task.cancel()

async def setup(bot):
    """Add StickyBot cog to the bot."""
    await bot.add_cog(StickyBot(bot))
    logger.info("StickyBot cog loaded successfully")
