import os
import discord
from discord.ext import commands
import motor.motor_asyncio
import logging

class RoleManagementCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # MongoDB connection
        self.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(os.getenv('MONGO_URL', 'mongodb://localhost:27017'))
        self.db = self.mongo_client['role_management']
        
        # Logging setup
        self.logger = logging.getLogger('RoleManagementCog')
        self.logger.setLevel(logging.INFO)

    async def get_guild_config(self, guild_id):
        """Retrieve or create configuration for a specific guild."""
        config = await self.db.guild_configs.find_one({'guild_id': guild_id})
        if not config:
            config = {
                'guild_id': guild_id,
                'role_mappings': {},
                'log_channel_id': None,
                'request_permissions': [],
                'auto_roles': {}
            }
            await self.db.guild_configs.insert_one(config)
        return config

    async def log_action(self, guild, message):
        """Log actions to the specified log channel."""
        config = await self.get_guild_config(guild.id)
        log_channel_id = config.get('log_channel_id')
        
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if log_channel:
                await log_channel.send(f"🔧 Role Management Log: {message}")

    @commands.command(name='maprole')
    @commands.has_permissions(manage_roles=True)
    async def map_role(self, ctx, role: discord.Role, keyword: str):
        """Map a role to a specific keyword."""
        await self.db.guild_configs.update_one(
            {'guild_id': ctx.guild.id},
            {'$set': {f'role_mappings.{keyword}': role.id}}
        )
        await self.log_action(ctx.guild, f"Role '{role.name}' mapped to keyword '{keyword}'")
        await ctx.send(f"Role '{role.name}' successfully mapped to '{keyword}'")

    @commands.command(name='unmaprole')
    @commands.has_permissions(manage_roles=True)
    async def unmap_role(self, ctx, keyword: str):
        """Remove a keyword role mapping."""
        await self.db.guild_configs.update_one(
            {'guild_id': ctx.guild.id},
            {'$unset': {f'role_mappings.{keyword}': 1}}
        )
        await self.log_action(ctx.guild, f"Keyword '{keyword}' unmapped")
        await ctx.send(f"Keyword '{keyword}' unmapped successfully")

    @commands.command(name='giverole')
    @commands.has_permissions(manage_roles=True)
    async def give_role(self, ctx, member: discord.Member, role: discord.Role):
        """Manually assign a role to a user."""
        try:
            await member.add_roles(role)
            await self.log_action(ctx.guild, f"Role '{role.name}' assigned to {member.name}")
            await ctx.send(f"Assigned {role.name} to {member.display_name}")
        except discord.Forbidden:
            await ctx.send("I don't have permission to assign this role.")

    @commands.command(name='removerole')
    @commands.has_permissions(manage_roles=True)
    async def remove_role(self, ctx, member: discord.Member, role: discord.Role):
        """Remove a role from a user."""
        try:
            await member.remove_roles(role)
            await self.log_action(ctx.guild, f"Role '{role.name}' removed from {member.name}")
            await ctx.send(f"Removed {role.name} from {member.display_name}")
        except discord.Forbidden:
            await ctx.send("I don't have permission to remove this role.")

    @commands.command(name='autorole')
    @commands.has_permissions(manage_roles=True)
    async def auto_role_setup(self, ctx, role: discord.Role, keyword: str):
        """Set up an auto-assignable role with a keyword."""
        await self.db.guild_configs.update_one(
            {'guild_id': ctx.guild.id},
            {'$set': {f'auto_roles.{keyword}': role.id}},
            upsert=True
        )
        await self.log_action(ctx.guild, f"Auto-role set for '{role.name}' with keyword '{keyword}'")
        await ctx.send(f"Users can now get {role.name} by typing {keyword}")

    @commands.command(name='listroles')
    async def list_roles(self, ctx):
        """List all mapped and auto-roles for the server."""
        config = await self.get_guild_config(ctx.guild.id)
        role_mappings = config.get('role_mappings', {})
        auto_roles = config.get('auto_roles', {})

        role_list = "**Mapped Roles:**\n"
        for keyword, role_id in role_mappings.items():
            role = ctx.guild.get_role(role_id)
            role_list += f"- {keyword}: {role.name if role else 'Deleted Role'}\n"

        role_list += "\n**Auto-Roles:**\n"
        for keyword, role_id in auto_roles.items():
            role = ctx.guild.get_role(role_id)
            role_list += f"- {keyword}: {role.name if role else 'Deleted Role'}\n"

        await ctx.send(role_list)

    @commands.command(name='setlogchannel')
    @commands.has_permissions(administrator=True)
    async def set_log_channel(self, ctx, channel: discord.TextChannel):
        """Set the log channel for role management activities."""
        await self.db.guild_configs.update_one(
            {'guild_id': ctx.guild.id},
            {'$set': {'log_channel_id': channel.id}}
        )
        await ctx.send(f"Log channel set to {channel.mention}")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Automatically assign roles based on keywords."""
        if message.author.bot:
            return

        # Check for auto-roles
        config = await self.get_guild_config(message.guild.id)
        auto_roles = config.get('auto_roles', {})
        
        for keyword, role_id in auto_roles.items():
            if message.content.lower() == keyword.lower():
                role = message.guild.get_role(role_id)
                if role:
                    try:
                        await message.author.add_roles(role)
                        await message.channel.send(f"Assigned {role.name} to {message.author.display_name}")
                        await self.log_action(message.guild, f"Auto-role '{role.name}' assigned to {message.author.name}")
                    except discord.Forbidden:
                        pass

def setup(bot):
    bot.add_cog(RoleManagementCog(bot))import os
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
