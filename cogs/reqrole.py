import os
import discord
import logging
import motor.motor_asyncio
from discord.ext import commands
from dotenv import load_dotenv
from typing import Dict, List

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class RoleManagementCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.EMBED_COLOR = 0x2f2136
        
        # MongoDB connection with separate database for each server
        self.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(os.getenv('MONGO_URL'))
        
    def get_guild_db(self, guild_id: str):
        """Create a separate database for each guild."""
        return self.mongo_client[f'discord_role_management_{guild_id}']

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setreqrole(self, ctx, role: discord.Role):
        """Set the role required for assigning/removing roles."""
        guild_db = self.get_guild_db(str(ctx.guild.id))
        guild_configs = guild_db['guild_configurations']
        
        # Update guild configuration with required role
        await guild_configs.update_one(
            {"config_type": "role_management"},
            {"$set": {"required_role_id": role.id}},
            upsert=True
        )
        
        await ctx.send(embed=discord.Embed(
            description=f"Required role set to {role.name}", 
            color=self.EMBED_COLOR
        ))
        logger.info(f"Required role set to {role.name} for guild {ctx.guild.id}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setrole(self, ctx, custom_name: str, role: discord.Role):
        """Map a custom name to a role and allow multiple roles."""
        guild_db = self.get_guild_db(str(ctx.guild.id))
        role_mappings = guild_db['role_mappings']
        
        # Check bot's role hierarchy
        if role.position >= ctx.guild.me.top_role.position:
            await ctx.send(embed=discord.Embed(
                description="Cannot map a role higher than my top role.", 
                color=self.EMBED_COLOR
            ))
            return
        
        # Store role mapping with unique identifier
        await role_mappings.update_one(
            {
                "custom_name": custom_name.lower()
            },
            {"$set": {
                "role_id": role.id, 
                "role_name": role.name,
                "guild_id": str(ctx.guild.id)
            }},
            upsert=True
        )
        
        await ctx.send(embed=discord.Embed(
            description=f"Mapped '{custom_name}' to role {role.name}", 
            color=self.EMBED_COLOR
        ))

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        """Set the log channel for role actions."""
        guild_db = self.get_guild_db(str(ctx.guild.id))
        guild_configs = guild_db['guild_configurations']
        
        # Update guild configuration with log channel
        await guild_configs.update_one(
            {"config_type": "role_management"},
            {"$set": {"log_channel_id": channel.id}},
            upsert=True
        )
        
        await ctx.send(embed=discord.Embed(
            description=f"Log channel set to {channel.mention}", 
            color=self.EMBED_COLOR
        ))
        logger.info(f"Log channel set to {channel.name} for guild {ctx.guild.id}")

    async def check_required_role(self, ctx):
        """Check if the user has the required role."""
        guild_db = self.get_guild_db(str(ctx.guild.id))
        guild_configs = guild_db['guild_configurations']
        
        # Fetch guild configuration
        config = await guild_configs.find_one({"config_type": "role_management"})
        
        if not config or 'required_role_id' not in config:
            await ctx.send(embed=discord.Embed(
                description="No required role has been set up.", 
                color=self.EMBED_COLOR
            ))
            return False
        
        required_role = ctx.guild.get_role(config['required_role_id'])
        if not required_role:
            await ctx.send(embed=discord.Embed(
                description="The required role no longer exists.", 
                color=self.EMBED_COLOR
            ))
            return False
        
        if required_role not in ctx.author.roles:
            await ctx.send(embed=discord.Embed(
                description="You do not have the required role to use this command.", 
                color=self.EMBED_COLOR
            ))
            return False
        
        return True

    async def dynamic_role_command(self, ctx, custom_name: str, member: discord.Member = None):
        """Dynamic command handler for assigning/removing roles."""
        # Check required role
        if not await self.check_required_role(ctx):
            return
        
        guild_id = str(ctx.guild.id)
        guild_db = self.get_guild_db(guild_id)
        role_mappings = guild_db['role_mappings']
        guild_configs = guild_db['guild_configurations']
        
        member = member or ctx.author
        
        # Get role mapping (case-insensitive)
        mapping = await role_mappings.find_one({
            "custom_name": custom_name.lower()
        })
        
        if not mapping:
            await ctx.send(embed=discord.Embed(
                description=f"No role mapped to '{custom_name}'.", 
                color=self.EMBED_COLOR
            ))
            return
        
        # Get role configuration
        config = await guild_configs.find_one({"config_type": "role_management"}) or {}
        role_limit = config.get('role_assignment_limit', 10)  # Increased default limit
        
        # Get the role object
        role = ctx.guild.get_role(mapping['role_id'])
        
        if not role:
            await ctx.send(embed=discord.Embed(
                description="The mapped role no longer exists.", 
                color=self.EMBED_COLOR
            ))
            return
        
        # Check role hierarchy
        if role.position >= ctx.guild.me.top_role.position:
            await ctx.send(embed=discord.Embed(
                description="Cannot assign a role higher than my top role.", 
                color=self.EMBED_COLOR
            ))
            return
        
        # Find all custom roles for this guild
        custom_roles = []
        async for r in role_mappings.find():
            custom_role = ctx.guild.get_role(r['role_id'])
            if custom_role and custom_role in member.roles:
                custom_roles.append(custom_role)
        
        if role in member.roles:
            # Remove role
            await member.remove_roles(role)
            action = "removed"
        else:
            # Check role limit
            if len(custom_roles) >= role_limit:
                await ctx.send(embed=discord.Embed(
                    description=f"Maximum of {role_limit} custom roles reached.", 
                    color=self.EMBED_COLOR
                ))
                return
            
            # Add role
            await member.add_roles(role)
            action = "assigned"
        
        # Log channel notification
        if config and 'log_channel_id' in config:
            log_channel = ctx.guild.get_channel(config['log_channel_id'])
            if log_channel:
                await log_channel.send(embed=discord.Embed(
                    description=f"{ctx.author.mention} {action} {custom_name} role to {member.mention}", 
                    color=self.EMBED_COLOR
                ))
        
        await ctx.send(embed=discord.Embed(
            description=f"{action.capitalize()} {custom_name} role to {member.mention}", 
            color=self.EMBED_COLOR
        ))

    async def cog_load(self):
        """Generate dynamic commands for each custom role when the cog loads."""
        for guild in self.bot.guilds:
            guild_id = str(guild.id)
            guild_db = self.get_guild_db(guild_id)
            role_mappings = guild_db['role_mappings']
            
            # Find all role mappings for this guild
            async for mapping in role_mappings.find():
                custom_name = mapping['custom_name']
                
                # Create a dynamic command if it doesn't already exist
                if not hasattr(self, custom_name):
                    async def dynamic_command(ctx, member: discord.Member = None, cn=custom_name):
                        await self.dynamic_role_command(ctx, cn, member)
                    
                    dynamic_command.__name__ = custom_name
                    setattr(self, custom_name, commands.command()(dynamic_command))
                    self.bot.add_command(getattr(self, custom_name))

    @commands.command()
    async def role(self, ctx):
        """Shows all available role management commands."""
        embed = discord.Embed(title="Role Management Commands", color=self.EMBED_COLOR)
        embed.add_field(name=".setreqrole [role]", value="Set the role required for assigning/removing roles.", inline=False)
        embed.add_field(name=".setrole [custom_name] [@role]", value="Map a custom name to a role (multiple roles allowed).", inline=False)
        embed.add_field(name=".setlogchannel [channel]", value="Set the log channel for role actions.", inline=False)
        embed.add_field(name=".[custom_name] [@user]", value="Assign/remove the mapped role to/from a user.", inline=False)
        embed.set_footer(text="Role Management Bot")
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(RoleManagementCog(bot))
