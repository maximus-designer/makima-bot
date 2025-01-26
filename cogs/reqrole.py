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
