import discord
import logging
import os
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

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
        self.reqrole_id = None
        self.role_mappings = {}
        self.log_channel_id = None
        self.role_assignment_limit = 5

    async def cog_load(self):
        """Ensure load_data is awaited properly when the cog is loaded."""
        await self.load_data()

    async def load_data(self):
        """Load role mappings and configurations from MongoDB."""
        config = await self.config_collection.find_one({"_id": "role_management"})
        if config:
            self.reqrole_id = config.get("reqrole_id")
            self.role_mappings = config.get("role_mappings", {})
            self.log_channel_id = config.get("log_channel_id")
            self.role_assignment_limit = config.get("role_assignment_limit", 5)
            logger.info("Configuration loaded from MongoDB.")
        else:
            logger.info("No existing configuration found in MongoDB. Starting fresh.")


    async def save_data(self):
        """Save role mappings and configurations to MongoDB."""
        config = {
            "_id": "role_management",
            "reqrole_id": self.reqrole_id,
            "role_mappings": self.role_mappings,
            "log_channel_id": self.log_channel_id,
            "role_assignment_limit": self.role_assignment_limit
        }
        await self.config_collection.replace_one({"_id": "role_management"}, config, upsert=True)
        logger.info("Configuration saved to MongoDB for reqrole.")

    async def has_reqrole(self, ctx):
        """Check if the user has the required role."""
        if self.reqrole_id is None:
            await ctx.send(embed=discord.Embed(
                description="<:sukoon_info:1323251063910043659> | The required role hasn't been set up yet!",
                color=EMBED_COLOR))
            return False
        if self.reqrole_id not in [role.id for role in ctx.author.roles]:
            await ctx.send(embed=discord.Embed(
                description="<:sukoon_info:1323251063910043659> | You do not have the required role to use this command.",
                color=EMBED_COLOR))
            return False
        return True

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info(f"Logged in as {self.bot.user}")
        self.generate_dynamic_commands()

    @commands.command()
    async def setreqrole(self, ctx, role: discord.Role):
        """Set the required role for assigning/removing roles."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send(embed=discord.Embed(
                description="<:sukoon_info:1323251063910043659> | You do not have permission to use this command.",
                color=EMBED_COLOR))
            return
        self.reqrole_id = role.id
        await self.save_data()
        await ctx.send(embed=discord.Embed(
            description=f"<a:sukoon_whitetick:1323992464058482729> | Required role set to {role.name}.",
            color=EMBED_COLOR))

    @commands.command()
    async def setrole(self, ctx, custom_name: str, role: discord.Role):
        """Map a custom role name to an existing role."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send(embed=discord.Embed(
                description="<:sukoon_info:1323251063910043659> | You do not have permission to use this command.",
                color=EMBED_COLOR))
            return

        self.role_mappings[custom_name] = role.id
        await self.save_data()
        await ctx.send(embed=discord.Embed(
            description=f"<a:sukoon_whitetick:1323992464058482729> | Mapped custom role name '{custom_name}' to role {role.name}.",
            color=EMBED_COLOR))
        self.generate_dynamic_commands()

    @commands.command()
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel where role assignment/removal logs will be sent."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send(embed=discord.Embed(
                description="<:sukoon_info:1323251063910043659> | You do not have permission to use this command.",
                color=EMBED_COLOR))
            return
        self.log_channel_id = channel.id
        await self.save_data()
        await ctx.send(embed=discord.Embed(
            description=f"<a:sukoon_whitetick:1323992464058482729> | Log channel set to {channel.name}.",
            color=EMBED_COLOR))

    def generate_dynamic_commands(self):
        """Generate dynamic commands for each custom role."""
        for custom_name in self.role_mappings.keys():
            if custom_name in self.bot.all_commands:
                continue

            async def command(ctx, member: discord.Member = None):
                await self.dynamic_role_command(ctx, custom_name, member)

            command.__name__ = custom_name
            command = commands.command()(command)
            setattr(self, custom_name, command)
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
        role_id = self.role_mappings.get(custom_name)
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

        if role in member.roles:
            await member.remove_roles(role)
            action = "removed"
        else:
            await member.add_roles(role)
            action = "assigned"

        await ctx.send(embed=discord.Embed(
            description=f"<a:sukoon_whitetick:1323992464058482729> | Successfully {action} the {custom_name} role for {member.mention}.",
            color=EMBED_COLOR))

        if self.log_channel_id:
            log_channel = self.bot.get_channel(self.log_channel_id)
            if log_channel:
                await log_channel.send(embed=discord.Embed(
                    description=f"{ctx.author} {action} the {custom_name} role for {member.mention}.",
                    color=EMBED_COLOR))

# Setup the cog
async def setup(bot):
    cog = RoleManagement(bot)
    await bot.add_cog(cog)
