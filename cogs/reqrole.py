import discord
import logging
import os
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
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
        self.mongo_url = os.getenv('MONGO_URL')
        self.mongo_client = AsyncIOMotorClient(self.mongo_url) if self.mongo_url else None
        self.server_configs = {}

    async def get_server_config(self, guild_id):
        """Retrieve or create server-specific configuration."""
        if not self.mongo_client:
            return None

        database = self.mongo_client[f"role_management_{guild_id}"]
        collection = database['server_config']
        
        config = await collection.find_one({'guild_id': guild_id})
        if not config:
            config = {
                'guild_id': guild_id,
                'reqrole_id': None,
                'role_mappings': {},
                'log_channel_id': None,
                'role_assignment_limit': 5
            }
            await collection.insert_one(config)
        
        self.server_configs[guild_id] = {
            'collection': collection,
            'config': config
        }
        return config

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize configurations for all guilds."""
        for guild in self.bot.guilds:
            await self.get_server_config(guild.id)
        logger.info(f'Logged in as {self.bot.user}')
        self.generate_role_commands()

    def generate_role_commands(self):
        """Dynamically generate role commands based on server configurations."""
        for guild_id, server_data in self.server_configs.items():
            role_mappings = server_data['config'].get('role_mappings', {})
            
            for custom_name in role_mappings.keys():
                # Dynamically create a command for each custom role
                async def role_command(ctx, member: discord.Member = None, custom_name=custom_name):
                    await self.assign_role(ctx, custom_name, member)
                
                # Set the command name and add it to the bot
                role_command.name = custom_name
                role_command = commands.command(name=custom_name)(role_command)
                self.bot.add_command(role_command)

    async def assign_role(self, ctx, custom_name, member=None):
        """Assign or remove a role."""
        # Verify server configuration exists
        server_config = self.server_configs.get(ctx.guild.id)
        if not server_config:
            await ctx.send("Server configuration not found.")
            return

        # Check for required role
        config = server_config['config']
        if config['reqrole_id']:
            reqrole = discord.utils.get(ctx.author.roles, id=config['reqrole_id'])
            if not reqrole:
                await ctx.send("You do not have the required role.")
                return

        # Validate member
        if not member:
            await ctx.send("Please mention a user.")
            return

        # Get role mappings
        role_mappings = config.get('role_mappings', {})
        if custom_name not in role_mappings:
            await ctx.send(f"No role mapped to '{custom_name}'.")
            return

        # Get roles to modify
        role_ids = role_mappings[custom_name]
        roles_to_modify = [ctx.guild.get_role(role_id) for role_id in role_ids if ctx.guild.get_role(role_id)]

        if not roles_to_modify:
            await ctx.send("No valid roles found for this mapping.")
            return

        # Check role hierarchy
        if any(role.position >= ctx.guild.me.top_role.position for role in roles_to_modify):
            await ctx.send("Cannot modify roles higher than my top role.")
            return

        # Determine action
        roles_to_add = []
        roles_to_remove = []
        for role in roles_to_modify:
            if role in member.roles:
                roles_to_remove.append(role)
            else:
                roles_to_add.append(role)

        # Modify roles
        if roles_to_add:
            await member.add_roles(*roles_to_add)
            await ctx.send(f"Added {', '.join(role.name for role in roles_to_add)} to {member.name}")
        
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove)
            await ctx.send(f"Removed {', '.join(role.name for role in roles_to_remove)} from {member.name}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setrole(self, ctx, custom_name: str, role: discord.Role):
        """Map a custom role name to a role."""
        server_config = self.server_configs.get(ctx.guild.id)
        if not server_config:
            await ctx.send("Server configuration not found.")
            return

        collection = server_config['collection']
        config = server_config['config']

        # Update role mappings
        role_mappings = config.get('role_mappings', {})
        if custom_name not in role_mappings:
            role_mappings[custom_name] = []
        
        if role.id not in role_mappings[custom_name]:
            role_mappings[custom_name].append(role.id)

        # Update configuration
        await collection.update_one(
            {'guild_id': ctx.guild.id},
            {'$set': {'role_mappings': role_mappings}}
        )

        # Regenerate commands
        self.generate_role_commands()

        await ctx.send(f"Mapped '{custom_name}' to {role.name}")

    @commands.command()
    async def rolehelp(self, ctx):
        """Show role management commands."""
        embed = discord.Embed(title="Role Management Commands", color=EMBED_COLOR)
        embed.add_field(name=".setrole [custom_name] [@role]", value="Map a custom name to a role", inline=False)
        embed.add_field(name=".[custom_name] [@user]", value="Assign/remove mapped role", inline=False)
        
        # Add dynamically generated role commands
        config = self.server_configs.get(ctx.guild.id, {}).get('config', {})
        role_mappings = config.get('role_mappings', {})
        
        if role_mappings:
            mapped_roles = "\n".join(f"- .{name}" for name in role_mappings.keys())
            embed.add_field(name="Available Role Commands", value=mapped_roles, inline=False)
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(RoleManagement(bot))
