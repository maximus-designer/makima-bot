import os
import discord
from discord.ext import commands
import motor.motor_asyncio
from pymongo import MongoClient
import logging

# Environment variable for MongoDB connection string
MONGO_URL = os.getenv('MONGO_URL', 'mongodb://localhost:27017')

class RoleManagementCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Async MongoDB client for better performance
        self.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
        self.db = self.mongo_client['discord_role_management']
        
        # Logger setup
        self.logger = logging.getLogger('RoleManagementBot')
        self.logger.setLevel(logging.INFO)

    async def get_guild_config(self, guild_id):
        """Retrieve or create configuration for a specific guild."""
        config = await self.db.guild_configs.find_one({'guild_id': guild_id})
        if not config:
            config = {
                'guild_id': guild_id,
                'role_mappings': {},
                'log_channel_id': None,
                'request_permissions': []
            }
            await self.db.guild_configs.insert_one(config)
        return config

    @commands.command(name='map')
    @commands.has_permissions(manage_roles=True)
    async def map_role(self, ctx, role_name: str, keyword: str):
        """Map a role to a specific keyword."""
        # Find the role in the server
        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if not role:
            await ctx.send(f"Role '{role_name}' not found.")
            return

        # Update role mapping in database
        await self.db.guild_configs.update_one(
            {'guild_id': ctx.guild.id},
            {'$set': {f'role_mappings.{keyword}': role.id}}
        )

        # Log the mapping
        await self.log_action(ctx.guild, f"Role '{role_name}' mapped to keyword '{keyword}'")
        await ctx.send(f"Role '{role_name}' successfully mapped to '{keyword}'")

    @commands.command(name='unmap')
    @commands.has_permissions(manage_roles=True)
    async def unmap_role(self, ctx, keyword: str):
        """Remove a keyword role mapping."""
        await self.db.guild_configs.update_one(
            {'guild_id': ctx.guild.id},
            {'$unset': {f'role_mappings.{keyword}': 1}}
        )

        await self.log_action(ctx.guild, f"Keyword '{keyword}' unmapped")
        await ctx.send(f"Keyword '{keyword}' unmapped successfully")

    @commands.command(name='requestrole')
    async def request_role(self, ctx, keyword: str = None, member: discord.Member = None):
        """Request a role using a mapped keyword."""
        # If no keyword provided, try to extract from command name
        if not keyword:
            keyword = f'.{ctx.command.name.upper()}'
        
        # Get guild configuration
        config = await self.get_guild_config(ctx.guild.id)
        
        # Determine target member
        target_member = member or ctx.author
        
        # Check role mapping exists
        role_mappings = config.get('role_mappings', {})
        if keyword not in role_mappings:
            await ctx.send(f"No role mapped to '{keyword}'")
            return

        # Permissions check
        role_id = role_mappings[keyword]
        role = ctx.guild.get_role(role_id)
        
        # Assign role
        try:
            await target_member.add_roles(role)
            await self.log_action(ctx.guild, f"Role '{role.name}' assigned to {target_member.name}")
            await ctx.send(f"Role '{role.name}' assigned to {target_member.mention}")
        except discord.Forbidden:
            await ctx.send("I don't have permission to assign this role.")

    @commands.command(name='resetmappings')
    @commands.has_permissions(administrator=True)
    async def reset_mappings(self, ctx):
        """Reset all role mappings for the server."""
        await self.db.guild_configs.update_one(
            {'guild_id': ctx.guild.id},
            {'$set': {'role_mappings': {}}}
        )
        await self.log_action(ctx.guild, "All role mappings reset")
        await ctx.send("All role mappings have been reset.")

    @commands.command(name='setlogchannel')
    @commands.has_permissions(administrator=True)
    async def set_log_channel(self, ctx, channel: discord.TextChannel):
        """Set the log channel for role management activities."""
        await self.db.guild_configs.update_one(
            {'guild_id': ctx.guild.id},
            {'$set': {'log_channel_id': channel.id}}
        )
        await ctx.send(f"Log channel set to {channel.mention}")

    async def log_action(self, guild, message):
        """Log actions to the specified log channel."""
        config = await self.get_guild_config(guild.id)
        log_channel_id = config.get('log_channel_id')
        
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if log_channel:
                await log_channel.send(f"🔧 Role Management Log: {message}")

def setup(bot):
    bot.add_cog(RoleManagementCog(bot))

# Main bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='.', intents=intents)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    print('------')

# Run the bot
bot.run(os.getenv('DISCORD_TOKEN'))
