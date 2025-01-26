import discord
import logging
import os
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from bson.objectid import ObjectId
import dotenv

# Setting up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
dotenv.load_dotenv()

EMBED_COLOR = 0x2f2136  # Constant embed color

class RoleManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.mongo_client = None
        self.database = None
        self.role_collection = None
        
        # Connection parameters
        self.mongo_url = os.getenv('MONGO_URL')
        if not self.mongo_url:
            logger.error("MONGO_URL environment variable is not set!")
        
        # Initialize MongoDB connection
        self.connect_to_mongodb()

    def connect_to_mongodb(self):
        """Establish connection to MongoDB."""
        try:
            # Use AsyncIOMotorClient for async operations
            self.mongo_client = AsyncIOMotorClient(self.mongo_url)
            
            # For admin operations, use synchronous PyMongo client
            self.sync_client = MongoClient(self.mongo_url)
            
            logger.info("Successfully connected to MongoDB")
        except Exception as e:
            logger.error(f"MongoDB connection error: {e}")
            raise

    async def get_server_config(self, guild_id):
        """Retrieve or create server-specific configuration."""
        server_config = await self.role_collection.find_one({'guild_id': guild_id})
        if not server_config:
            server_config = {
                'guild_id': guild_id,
                'reqrole_id': None,
                'role_mappings': {},
                'log_channel_id': None,
                'role_assignment_limit': 5
            }
            await self.role_collection.insert_one(server_config)
        return server_config

    async def update_server_config(self, guild_id, update_data):
        """Update server-specific configuration."""
        await self.role_collection.update_one(
            {'guild_id': guild_id}, 
            {'$set': update_data}
        )

    @commands.Cog.listener()
    async def on_ready(self):
        # Set up database for each guild the bot is in
        for guild in self.bot.guilds:
            database_name = f"role_management_{guild.id}"
            self.database = self.mongo_client[database_name]
            self.role_collection = self.database['server_configs']
            
            # Initialize configuration for each server
            await self.get_server_config(guild.id)
        
        logger.info(f'Logged in as {self.bot.user}')

    @commands.command()
    async def setreqrole(self, ctx, role: discord.Role):
        """Set the required role for assigning/removing roles."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send(embed=discord.Embed(description="<:sukoon_info:1323251063910043659> | You do not have permission to use this command.", color=EMBED_COLOR))
            return
        
        await self.update_server_config(ctx.guild.id, {'reqrole_id': role.id})
        logger.info(f'Required role set to {role.name} for guild {ctx.guild.id}.')
        await ctx.send(embed=discord.Embed(description=f"Required role set to {role.name}.", color=EMBED_COLOR))

    @commands.command()
    async def reset_mappings(self, ctx):
        """Reset all role mappings for the current server."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send(embed=discord.Embed(description="<:sukoon_info:1323251063910043659> | You do not have permission to use this command.", color=EMBED_COLOR))
            return
        
        await self.update_server_config(ctx.guild.id, {
            'role_mappings': {},
            'reqrole_id': None,
            'log_channel_id': None,
            'role_assignment_limit': 5
        })
        
        await ctx.send(embed=discord.Embed(description="<a:sukoon_whitetick:1323992464058482729> | All role mappings have been reset.", color=EMBED_COLOR))

    @commands.command()
    async def setrole(self, ctx, custom_name: str, role: discord.Role):
        """Map a custom role name to an existing role."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send(embed=discord.Embed(description="<:sukoon_info:1323251063910043659> | You do not have permission to use this command.", color=EMBED_COLOR))
            return

        server_config = await self.get_server_config(ctx.guild.id)
        role_mappings = server_config.get('role_mappings', {})
        
        # Allow multiple mappings for a single custom name
        if custom_name not in role_mappings:
            role_mappings[custom_name] = []
        
        # Add role ID if not already present
        if role.id not in role_mappings[custom_name]:
            role_mappings[custom_name].append(role.id)
        
        await self.update_server_config(ctx.guild.id, {'role_mappings': role_mappings})
        
        logger.info(f'Mapped custom role name "{custom_name}" to role {role.name}.')
        await ctx.send(embed=discord.Embed(description=f"<a:sukoon_whitetick:1323992464058482729> | Mapped custom role name \"{custom_name}\" to role {role.name}.", color=EMBED_COLOR))

    async def assign_or_remove_role(self, ctx, custom_name: str, member: discord.Member):
        """Assign or remove the mapped custom roles from a user."""
        server_config = await self.get_server_config(ctx.guild.id)
        role_mappings = server_config.get('role_mappings', {})
        
        if custom_name not in role_mappings:
            await ctx.send(embed=discord.Embed(description=f"<:sukoon_info:1323251063910043659> | No role mapped to '{custom_name}'. Please map a role first.", color=EMBED_COLOR))
            return

        role_ids = role_mappings[custom_name]
        roles = [discord.utils.get(ctx.guild.roles, id=role_id) for role_id in role_ids]
        
        # Remove invalid roles
        roles = [role for role in roles if role]
        
        if not roles:
            await ctx.send(embed=discord.Embed(description=f"<:sukoon_info:1323251063910043659> | The roles mapped to '{custom_name}' no longer exist.", color=EMBED_COLOR))
            return

        # Check role hierarchy permissions
        if any(role.position >= ctx.guild.me.top_role.position for role in roles):
            await ctx.send(embed=discord.Embed(description=f"<:sukoon_info:1323251063910043659> | I cannot assign/remove one or more roles as they are higher than or equal to my top role.", color=EMBED_COLOR))
            return

        # Check role assignment limit
        user_custom_roles = [role for role in member.roles if any(role.id in mapping for mapping in role_mappings.values())]
        role_limit = server_config.get('role_assignment_limit', 5)
        
        if len(user_custom_roles) >= role_limit:
            await ctx.send(embed=discord.Embed(description=f"<:sukoon_info:1323251063910043659> | {member.mention} already has the maximum number of custom roles ({role_limit}).", color=EMBED_COLOR))
            return

        # Determine action (assign or remove)
        roles_to_modify = []
        action = ""
        for role in roles:
            if role in member.roles:
                roles_to_modify.append(role)
                action = "removed"
            else:
                roles_to_modify.append(role)
                action = "assigned"

        if roles_to_modify:
            await member.add_roles(*roles_to_modify) if action == "assigned" else await member.remove_roles(*roles_to_modify)
            
            roles_names = ", ".join(role.name for role in roles_to_modify)
            await ctx.send(embed=discord.Embed(description=f"<a:sukoon_whitetick:1323992464058482729> | Successfully {action} the {roles_names} role(s) to {member.mention}.", color=EMBED_COLOR))

    # Other methods remain largely the same, just update to use async MongoDB methods

async def setup(bot):
    await bot.add_cog(RoleManagement(bot))
