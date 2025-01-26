import discord
import logging
import os
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import asyncio
import re

# Load environment variables
load_dotenv()

# Setting up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

EMBED_COLOR = 0x2f2136  # Constant embed color
DEFAULT_ROLE_LIMIT = 5
EMOJI_SUCCESS = "<a:sukoon_whitetick:1323992464058482729>"
EMOJI_INFO = "<:sukoon_info:1323251063910043659>"

class RoleManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.mongo_client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
        self.db = self.mongo_client["reqrole"]
        self.config_collection = self.db["config"]

        # Threadsafe cache for guild configurations
        self.guild_configs = {}
        self.config_lock = asyncio.Lock()
        self.dynamic_commands = {}

    async def cog_load(self):
        """Load guild configurations safely during cog initialization."""
        try:
            await self.load_all_guild_configs()
        except Exception as e:
            logger.error(f"Failed to load guild configurations: {e}")

    async def load_all_guild_configs(self):
        """
        Safely load configurations with error handling and lazy loading.
        Only load configurations for guilds the bot is currently in.
        """
        try:
            # Get current guild IDs
            current_guild_ids = [guild.id for guild in self.bot.guilds]

            # Fetch only relevant configurations
            async for config in self.config_collection.find({"guild_id": {"$in": current_guild_ids}}):
                guild_id = config.get("guild_id")
                if guild_id:
                    self.guild_configs[guild_id] = {
                        "reqrole_id": config.get("reqrole_id"),
                        "role_mappings": config.get("role_mappings", {}),
                        "log_channel_id": config.get("log_channel_id"),
                        "role_assignment_limit": config.get("role_assignment_limit", DEFAULT_ROLE_LIMIT)
                    }
                    self.generate_dynamic_commands(guild_id)

            logger.info(f"Loaded configurations for {len(self.guild_configs)} guilds")
        except Exception as e:
            logger.error(f"Configuration loading error: {e}")

    async def get_guild_config(self, guild_id):
        """
        Thread-safe method to retrieve or create guild configuration.
        Validates and sanitizes configuration data.
        """
        async with self.config_lock:
            if guild_id not in self.guild_configs:
                self.guild_configs[guild_id] = {
                    "reqrole_id": None,
                    "role_mappings": {},
                    "log_channel_id": None,
                    "role_assignment_limit": DEFAULT_ROLE_LIMIT
                }
            return self.guild_configs[guild_id]

    async def save_guild_config(self, guild_id, config):
        """
        Safely save and validate guild configuration.
        Prevents invalid or malicious configuration updates.
        """
        # Validate custom role name
        if "role_mappings" in config:
            sanitized_mappings = {}
            for name, role_id in config["role_mappings"].items():
                # Ensure custom name is alphanumeric and lowercase
                sanitized_name = re.sub(r'[^a-z0-9]', '', name.lower())
                if sanitized_name and role_id:
                    sanitized_mappings[sanitized_name] = role_id
            config["role_mappings"] = sanitized_mappings

        async with self.config_lock:
            config["guild_id"] = guild_id
            await self.config_collection.replace_one(
                {"guild_id": guild_id}, 
                config, 
                upsert=True
            )
            self.guild_configs[guild_id] = config
            logger.info(f"Saved configuration for guild {guild_id}")
            self.generate_dynamic_commands(guild_id)

    async def validate_role_hierarchy(self, ctx, role):
        """
        Ensure bot can manage the role and role is below bot's highest role.
        """
        bot_member = ctx.guild.me
        return (
            bot_member.top_role.position > role.position and 
            bot_member.guild_permissions.manage_roles
        )

    async def has_reqrole(self, ctx):
        """Check if the user has the required role for the specific guild."""
        guild_config = await self.get_guild_config(ctx.guild.id)
        reqrole_id = guild_config.get("reqrole_id")

        if reqrole_id is None:
            await ctx.send(embed=discord.Embed(
                description=f"{EMOJI_INFO} | The required role hasn't been set up for this server.",
                color=EMBED_COLOR))
            return False

        if reqrole_id not in [role.id for role in ctx.author.roles]:
            await ctx.send(embed=discord.Embed(
                description=f"{EMOJI_INFO} | You do not have the required role to use this command.",
                color=EMBED_COLOR))
            return False

        return True

    def generate_dynamic_commands(self, guild_id):
        """
        Dynamically generates commands for each custom role mapping.
        Improves flexibility, role validation, and permissions.
        """
        # Remove previous dynamic commands for this guild to avoid duplicates
        if guild_id in self.dynamic_commands:
            for cmd_name in self.dynamic_commands[guild_id]:
                self.bot.remove_command(cmd_name)
            del self.dynamic_commands[guild_id]

        guild_config = self.guild_configs.get(guild_id, {})
        role_mappings = guild_config.get("role_mappings", {})
        role_assignment_limit = guild_config.get("role_assignment_limit", DEFAULT_ROLE_LIMIT)

        self.dynamic_commands[guild_id] = []

        for custom_name, role_id in role_mappings.items():
            # Define the dynamic role command
            async def dynamic_role_command(ctx, member: discord.Member = None, custom_name=custom_name):
                # Check if the user has the required role to execute this command
                if not await self.has_reqrole(ctx):
                    return

                # Ensure a valid member is provided
                if not member:
                    await ctx.send(embed=discord.Embed(
                        description=f"{EMOJI_INFO} | Please mention a user to assign or remove the role.",
                        color=EMBED_COLOR))
                    return

                # Ensure the role exists and get it
                role = discord.utils.get(ctx.guild.roles, id=role_id)
                if not role:
                    await ctx.send(embed=discord.Embed(
                        description=f"{EMOJI_INFO} | The role mapped to '{custom_name}' no longer exists.",
                        color=EMBED_COLOR))
                    return

                # Ensure the user hasn't exceeded the role assignment limit
                mapped_role_ids = list(role_mappings.values())
                current_mapped_roles = [r for r in member.roles if r.id in mapped_role_ids]
                if len(current_mapped_roles) >= role_assignment_limit:
                    await ctx.send(embed=discord.Embed(
                        description=f"{EMOJI_INFO} | {member.mention} has already reached the maximum role assignment limit of {role_assignment_limit}.",
                        color=EMBED_COLOR))
                    return

                # Perform role assignment or removal
                action = "added" if role not in member.roles else "removed"
                try:
                    if action == "added":
                        await member.add_roles(role)
                    else:
                        await member.remove_roles(role)

                    # Send feedback about the action
                    await ctx.send(embed=discord.Embed(
                        description=f"{EMOJI_SUCCESS} | Role '{role.name}' has been {action} to {member.mention}.",
                        color=EMBED_COLOR))

                    # Log the action if a log channel is set
                    log_channel_id = guild_config.get("log_channel_id")
                    if log_channel_id:
                        log_channel = self.bot.get_channel(log_channel_id)
                        if log_channel:
                            await log_channel.send(embed=discord.Embed(
                                description=f"{ctx.author} {action} role '{role.name}' to {member.mention}.",
                                color=EMBED_COLOR))

                except discord.Forbidden:
                    await ctx.send(embed=discord.Embed(
                        description=f"{EMOJI_INFO} | I do not have permission to manage roles.",
                        color=EMBED_COLOR))
                except discord.HTTPException:
                    await ctx.send(embed=discord.Embed(
                        description=f"{EMOJI_INFO} | Failed to assign or remove the role. Please check my permissions.",
                        color=EMBED_COLOR))

            # Generate a unique command for each custom role mapping
            command_name = f"{guild_id}_{custom_name}"

            # Register the command with the bot
            cmd = commands.command(name=custom_name)(dynamic_role_command)
            self.bot.add_command(cmd)

            # Cache the command name for later cleanup
            self.dynamic_commands[guild_id].append(custom_name)


    async def dynamic_role_handler(self, ctx, custom_name: str, member: discord.Member = None):
        """Handle dynamic role assignment/removal commands."""
        if not await self.has_reqrole(ctx):
            return

        if not member:
            await ctx.send(embed=discord.Embed(
                description=f"{EMOJI_INFO} | Please mention a user.",
                color=EMBED_COLOR))
            return

        await self.assign_or_remove_role(ctx, custom_name, member)

    async def assign_or_remove_role(self, ctx, custom_name: str, member: discord.Member):
        """Assign or remove the mapped custom role from a user."""
        guild_config = await self.get_guild_config(ctx.guild.id)
        role_mappings = guild_config.get("role_mappings", {})

        role_id = role_mappings.get(custom_name)
        if not role_id:
            await ctx.send(embed=discord.Embed(
                description=f"{EMOJI_INFO} | No role mapped to '{custom_name}'. Please map a role first.",
                color=EMBED_COLOR))
            return

        role = discord.utils.get(ctx.guild.roles, id=role_id)
        if not role:
            await ctx.send(embed=discord.Embed(
                description=f"{EMOJI_INFO} | The role mapped to '{custom_name}' no longer exists.",
                color=EMBED_COLOR))
            return

        # Determine action before assignment or removal
        action = "removed" if role in member.roles else "assigned"

        # Implement role assignment limit
        role_assignment_limit = guild_config.get("role_assignment_limit", DEFAULT_ROLE_LIMIT)
        mapped_role_ids = list(role_mappings.values())
        current_mapped_roles = [r for r in member.roles if r.id in mapped_role_ids]

        if action == "assigned" and len(current_mapped_roles) >= role_assignment_limit:
            await ctx.send(embed=discord.Embed(
                description=f"{EMOJI_INFO} | User has reached the maximum role assignment limit of {role_assignment_limit}.",
                color=EMBED_COLOR))
            return

        try:
            if action == "removed":
                await member.remove_roles(role)
            else:
                await member.add_roles(role)
        except discord.Forbidden:
            await ctx.send(embed=discord.Embed(
                description=f"{EMOJI_INFO} | I do not have permission to manage roles.",
                color=EMBED_COLOR))
            return
        except discord.HTTPException:
            await ctx.send(embed=discord.Embed(
                description=f"{EMOJI_INFO} | Failed to manage roles. Please check bot permissions.",
                color=EMBED_COLOR))
            return

        await ctx.send(embed=discord.Embed(
            description=f"{EMOJI_SUCCESS} | Successfully {action} the {custom_name} role for {member.mention}.",
            color=EMBED_COLOR))

        # Log role changes
        log_channel_id = guild_config.get("log_channel_id")
        if log_channel_id:
            log_channel = self.bot.get_channel(log_channel_id)
            if log_channel:
                await log_channel.send(embed=discord.Embed(
                    description=f"{ctx.author} {action} the {custom_name} role for {member.mention}.",
                    color=EMBED_COLOR))

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setreqrole(self, ctx, role: discord.Role):
        """Set the required role with hierarchy validation."""
        if not await self.validate_role_hierarchy(ctx, role):
            await ctx.send(embed=discord.Embed(
                description=f"{EMOJI_INFO} | Cannot set this role. Insufficient permissions.",
                color=EMBED_COLOR))
            return

        guild_config = await self.get_guild_config(ctx.guild.id)
        guild_config["reqrole_id"] = role.id
        await self.save_guild_config(ctx.guild.id, guild_config)

        await ctx.send(embed=discord.Embed(
            description=f"{EMOJI_SUCCESS} | Required role set to {role.name}.",
            color=EMBED_COLOR))

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setrole(self, ctx, custom_name: str, role: discord.Role):
        """Map a custom role name to an existing role."""
        if not await self.validate_role_hierarchy(ctx, role):
            await ctx.send(embed=discord.Embed(
                description=f"{EMOJI_INFO} | Cannot map this role. Insufficient permissions.",
                color=EMBED_COLOR))
            return

        # Sanitize custom name
        sanitized_name = re.sub(r'[^a-z0-9]', '', custom_name.lower())
        if not sanitized_name:
            await ctx.send(embed=discord.Embed(
                description=f"{EMOJI_INFO} | Invalid custom role name.",
                color=EMBED_COLOR))
            return

        guild_config = await self.get_guild_config(ctx.guild.id)
        guild_config["role_mappings"][sanitized_name] = role.id
        await self.save_guild_config(ctx.guild.id, guild_config)

        await ctx.send(embed=discord.Embed(
            description=f"{EMOJI_SUCCESS} | Mapped custom role name '{sanitized_name}' to role {role.name}.",
            color=EMBED_COLOR))

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel where role assignment/removal logs will be sent."""
        guild_config = await self.get_guild_config(ctx.guild.id)
        guild_config["log_channel_id"] = channel.id
        await self.save_guild_config(ctx.guild.id, guild_config)

        await ctx.send(embed=discord.Embed(
            description=f"{EMOJI_SUCCESS} | Log channel set to {channel.name}.",
            color=EMBED_COLOR))

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setrolelimit(self, ctx, limit: int):
        """Set the maximum number of roles a user can have."""
        if limit < 1 or limit > 10:
            await ctx.send(embed=discord.Embed(
                description=f"{EMOJI_INFO} | Role limit must be between 1 and 10.",
                color=EMBED_COLOR))
            return

        guild_config = await self.get_guild_config(ctx.guild.id)
        guild_config["role_assignment_limit"] = limit
        await self.save_guild_config(ctx.guild.id, guild_config)

        await ctx.send(embed=discord.Embed(
            description=f"{EMOJI_SUCCESS} | Role assignment limit set to {limit}.",
            color=EMBED_COLOR))

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Initialize configuration when joining a new guild."""
        logger.info(f"Joined new guild: {guild.name} (ID: {guild.id})")
        await self.get_guild_config(guild.id)

async def setup(bot):
    await bot.add_cog(RoleManagement(bot))import discord
import logging
import os
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import asyncio

# Load environment variables
load_dotenv()

# Setting up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

EMBED_COLOR = 0x2f2136  # Constant embed color

class RoleManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Create a unique database for each server
        self.mongo_client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
        self.guild_databases = {}
        
        # Lock to prevent concurrent configuration updates
        self.config_lock = asyncio.Lock()

    async def get_server_database(self, guild_id):
        """
        Get or create a unique database for a specific server.
        
        Args:
            guild_id (int): The ID of the guild
        
        Returns:
            dict: Database collections for the guild
        """
        async with self.config_lock:
            if guild_id not in self.guild_databases:
                db_name = f"reqrole_{guild_id}"
                mongo_db = self.mongo_client[db_name]
                self.guild_databases[guild_id] = {
                    "config": mongo_db["config"],
                    "role_mappings": mongo_db["role_mappings"]
                }
            return self.guild_databases[guild_id]

    async def get_guild_config(self, guild_id):
        """
        Retrieve or create a configuration for a specific guild.

        Args:
            guild_id (int): The ID of the guild to get configuration for.

        Returns:
            dict: Guild-specific configuration
        """
        server_db = await self.get_server_database(guild_id)
        config = await server_db["config"].find_one({"type": "guild_config"})
        
        if not config:
            config = {
                "type": "guild_config",
                "reqrole_id": None,
                "log_channel_id": None,
                "role_assignment_limit": 5
            }
            await server_db["config"].insert_one(config)
        
        return config

    async def save_guild_config(self, guild_id, config):
        """
        Save guild-specific configuration to MongoDB.

        Args:
            guild_id (int): The ID of the guild
            config (dict): Configuration to save
        """
        server_db = await self.get_server_database(guild_id)
        await server_db["config"].replace_one(
            {"type": "guild_config"}, 
            config, 
            upsert=True
        )
        logger.info(f"Saved configuration for guild {guild_id}")

    async def get_role_mappings(self, guild_id):
        """
        Retrieve all role mappings for a specific guild.

        Args:
            guild_id (int): The ID of the guild

        Returns:
            dict: Mapping of custom names to role IDs
        """
        server_db = await self.get_server_database(guild_id)
        mappings = await server_db["role_mappings"].find().to_list(None)
        return {mapping['custom_name']: mapping['role_id'] for mapping in mappings}

    async def add_role_mapping(self, guild_id, custom_name, role_id):
        """
        Add or update a role mapping for a specific guild.

        Args:
            guild_id (int): The ID of the guild
            custom_name (str): Custom name for the role
            role_id (int): ID of the role to map
        """
        server_db = await self.get_server_database(guild_id)
        await server_db["role_mappings"].replace_one(
            {"custom_name": custom_name},
            {"custom_name": custom_name, "role_id": role_id},
            upsert=True
        )

    async def reset_role_mappings(self, guild_id):
        """
        Reset all role mappings for a specific guild.

        Args:
            guild_id (int): The ID of the guild
        """
        server_db = await self.get_server_database(guild_id)
        await server_db["role_mappings"].delete_many({})

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setrole(self, ctx, custom_name: str, role: discord.Role):
        """Map multiple custom role names to existing roles."""
        await self.add_role_mapping(ctx.guild.id, custom_name, role.id)
        await ctx.send(embed=discord.Embed(
            description=f"<a:sukoon_whitetick:1323992464058482729> | Mapped custom role name '{custom_name}' to role {role.name}.",
            color=EMBED_COLOR))
        self.generate_dynamic_commands(ctx.guild.id)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def resetrolemappings(self, ctx):
        """Reset all role mappings for the current server."""
        await self.reset_role_mappings(ctx.guild.id)
        await ctx.send(embed=discord.Embed(
            description="<a:sukoon_whitetick:1323992464058482729> | All role mappings have been reset. Existing role assignments remain unchanged.",
            color=EMBED_COLOR))
        # Regenerate commands to reflect the reset
        self.generate_dynamic_commands(ctx.guild.id)

    def generate_dynamic_commands(self, guild_id):
        """Generate dynamic commands for each custom role in a specific guild."""
        async def get_mappings():
            return await self.get_role_mappings(guild_id)

        # Remove existing dynamic commands for this guild
        commands_to_remove = [
            cmd for cmd in self.bot.commands 
            if cmd.name.startswith(f"{guild_id}_")
        ]
        for cmd in commands_to_remove:
            self.bot.remove_command(cmd.name)

        # Create new dynamic commands based on current mappings
        asyncio.create_task(self._generate_commands(guild_id))

    async def _generate_commands(self, guild_id):
        """Async helper to generate dynamic commands."""
        role_mappings = await self.get_role_mappings(guild_id)

        for custom_name in role_mappings.keys():
            async def command(ctx, member: discord.Member = None):
                await self.dynamic_role_command(ctx, custom_name, member)

            command.__name__ = f"{guild_id}_{custom_name}"
            command = commands.command(name=custom_name)(command)
            setattr(self, command.__name__, command)
            self.bot.add_command(command)

    # Rest of the methods remain the same as in the previous implementation
    # (has_reqrole, dynamic_role_command, assign_or_remove_role, etc.)

# Setup the cog
async def setup(bot):
    await bot.add_cog(RoleManagement(bot))
