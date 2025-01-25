import discord
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
        self.mongo_client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
        self.db = self.mongo_client["reqrole"]
        self.config_collection = self.db["config"]

        # Multi-server support: Use a dictionary to store configurations per guild
        self.guild_configs = {}

        # Lock to prevent concurrent configuration updates
        self.config_lock = asyncio.Lock()

    async def cog_load(self):
        """Ensure load_data is awaited properly when the cog is loaded."""
        await self.load_all_guild_configs()

    async def load_all_guild_configs(self):
        """Load configurations for all guilds the bot is in."""
        try:
            async for config in self.config_collection.find():
                guild_id = config.get("guild_id")
                if guild_id:
                    self.guild_configs[guild_id] = {
                        "reqrole_id": config.get("reqrole_id"),
                        "role_mappings": config.get("role_mappings", {}),
                        "log_channel_id": config.get("log_channel_id"),
                        "role_assignment_limit": config.get("role_assignment_limit", 5)
                    }
            logger.info(f"Loaded configurations for {len(self.guild_configs)} guilds.")
        except Exception as e:
            logger.error(f"Error loading guild configurations: {e}")

    async def get_guild_config(self, guild_id):
        """
        Retrieve or create a configuration for a specific guild.

        Args:
            guild_id (int): The ID of the guild to get configuration for.

        Returns:
            dict: Guild-specific configuration
        """
        async with self.config_lock:
            if guild_id not in self.guild_configs:
                self.guild_configs[guild_id] = {
                    "reqrole_id": None,
                    "role_mappings": {},
                    "log_channel_id": None,
                    "role_assignment_limit": 5
                }
            return self.guild_configs[guild_id]

    async def save_guild_config(self, guild_id, config):
        """
        Save guild-specific configuration to MongoDB.

        Args:
            guild_id (int): The ID of the guild
            config (dict): Configuration to save
        """
        async with self.config_lock:
            config["guild_id"] = guild_id
            await self.config_collection.replace_one(
                {"guild_id": guild_id}, 
                config, 
                upsert=True
            )
            self.guild_configs[guild_id] = config
            logger.info(f"Saved configuration for guild {guild_id}")

    async def has_reqrole(self, ctx):
        """Check if the user has the required role for the specific guild."""
        guild_config = await self.get_guild_config(ctx.guild.id)
        reqrole_id = guild_config.get("reqrole_id")

        if reqrole_id is None:
            await ctx.send(embed=discord.Embed(
                description="<:sukoon_info:1323251063910043659> | The required role hasn't been set up for this server.",
                color=EMBED_COLOR))
            return False

        if reqrole_id not in [role.id for role in ctx.author.roles]:
            await ctx.send(embed=discord.Embed(
                description="<:sukoon_info:1323251063910043659> | You do not have the required role to use this command.",
                color=EMBED_COLOR))
            return False

        return True

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setreqrole(self, ctx, role: discord.Role):
        """Set the required role for assigning/removing roles."""
        guild_config = await self.get_guild_config(ctx.guild.id)
        guild_config["reqrole_id"] = role.id
        await self.save_guild_config(ctx.guild.id, guild_config)

        await ctx.send(embed=discord.Embed(
            description=f"<a:sukoon_whitetick:1323992464058482729> | Required role set to {role.name}.",
            color=EMBED_COLOR))
        self.generate_dynamic_commands(ctx.guild.id)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setrole(self, ctx, custom_name: str, role: discord.Role):
        """Map a custom role name to an existing role."""
        guild_config = await self.get_guild_config(ctx.guild.id)
        guild_config["role_mappings"][custom_name] = role.id
        await self.save_guild_config(ctx.guild.id, guild_config)

        await ctx.send(embed=discord.Embed(
            description=f"<a:sukoon_whitetick:1323992464058482729> | Mapped custom role name '{custom_name}' to role {role.name}.",
            color=EMBED_COLOR))
        self.generate_dynamic_commands(ctx.guild.id)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel where role assignment/removal logs will be sent."""
        guild_config = await self.get_guild_config(ctx.guild.id)
        guild_config["log_channel_id"] = channel.id
        await self.save_guild_config(ctx.guild.id, guild_config)

        await ctx.send(embed=discord.Embed(
            description=f"<a:sukoon_whitetick:1323992464058482729> | Log channel set to {channel.name}.",
            color=EMBED_COLOR))

    def generate_dynamic_commands(self, guild_id):
        """Generate dynamic commands for each custom role in a specific guild."""
        guild_config = self.guild_configs.get(guild_id, {})
        role_mappings = guild_config.get("role_mappings", {})

        for custom_name in role_mappings.keys():
            command_name = f"{guild_id}_{custom_name}"

            if command_name in self.bot.all_commands:
                continue

            async def command(ctx, member: discord.Member = None):
                await self.dynamic_role_command(ctx, custom_name, member)

            command.__name__ = command_name
            command = commands.command(name=custom_name)(command)
            setattr(self, command_name, command)
            self.bot.add_command(command)

    async def dynamic_role_command(self, ctx, custom_name: str, member: discord.Member = None):
        """Dynamic command handler for assigning/removing roles."""
        if not await self.has_reqrole(ctx):
            return

        if not member:
            await ctx.send(embed=discord.Embed(
                description="<:sukoon_info:1323251063910043659> | Please mention a user.",
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
                description=f"<:sukoon_info:1323251063910043659> | No role mapped to '{custom_name}'. Please map a role first.",
                color=EMBED_COLOR))
            return

        role = discord.utils.get(ctx.guild.roles, id=role_id)
        if not role:
            await ctx.send(embed=discord.Embed(
                description=f"<:sukoon_info:1323251063910043659> | The role mapped to '{custom_name}' no longer exists.",
                color=EMBED_COLOR))
            return

        # Determine action before assignment or removal
        action = "removed" if role in member.roles else "assigned"

        # Implement role assignment limit
        role_assignment_limit = guild_config.get("role_assignment_limit", 5)
        if action == "assigned" and len([r for r in member.roles if r.id in role_mappings.values()]) >= role_assignment_limit:
            await ctx.send(embed=discord.Embed(
                description=f"<:sukoon_info:1323251063910043659> | User has reached the maximum role assignment limit of {role_assignment_limit}.",
                color=EMBED_COLOR))
            return

        if action == "removed":
            await member.remove_roles(role)
        else:
            await member.add_roles(role)

        await ctx.send(embed=discord.Embed(
            description=f"<a:sukoon_whitetick:1323992464058482729> | Successfully {action} the {custom_name} role for {member.mention}.",
            color=EMBED_COLOR))

        # Log role changes
        log_channel_id = guild_config.get("log_channel_id")
        if log_channel_id:
            log_channel = self.bot.get_channel(log_channel_id)
            if log_channel:
                await log_channel.send(embed=discord.Embed(
                    description=f"{ctx.author} {action} the {custom_name} role for {member.mention}.",
                    color=EMBED_COLOR))

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Initialize configuration when joining a new guild."""
        logger.info(f"Joined new guild: {guild.name} (ID: {guild.id})")
        await self.get_guild_config(guild.id)

# Setup the cog
async def setup(bot):
    await bot.add_cog(RoleManagement(bot))
