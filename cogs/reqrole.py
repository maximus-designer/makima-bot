import os
import discord
import logging
import motor.motor_asyncio
from discord.ext import commands
from dotenv import load_dotenv

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
        
        # MongoDB connection
        self.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(os.getenv('MONGO_URL'))
        self.db = self.mongo_client['discord_role_management']
        self.guild_configs = self.db['guild_configurations']
        self.role_mappings = self.db['role_mappings']

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setreqrole(self, ctx, role: discord.Role):
        """Set the role required for assigning/removing roles."""
        guild_id = str(ctx.guild.id)
        
        # Update guild configuration with required role
        await self.guild_configs.update_one(
            {"guild_id": guild_id},
            {"$set": {"required_role_id": role.id}},
            upsert=True
        )
        
        await ctx.send(embed=discord.Embed(
            description=f"Required role set to {role.name}", 
            color=self.EMBED_COLOR
        ))
        logger.info(f"Required role set to {role.name} for guild {guild_id}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setrole(self, ctx, custom_name: str, role: discord.Role):
        """Map a custom name to a role."""
        guild_id = str(ctx.guild.id)
        
        # Check bot's role hierarchy
        if role.position >= ctx.guild.me.top_role.position:
            await ctx.send(embed=discord.Embed(
                description="Cannot map a role higher than my top role.", 
                color=self.EMBED_COLOR
            ))
            return
        
        # Store role mapping
        await self.role_mappings.update_one(
            {
                "guild_id": guild_id, 
                "custom_name": custom_name
            },
            {"$set": {
                "role_id": role.id, 
                "role_name": role.name
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
        guild_id = str(ctx.guild.id)
        
        # Update guild configuration with log channel
        await self.guild_configs.update_one(
            {"guild_id": guild_id},
            {"$set": {"log_channel_id": channel.id}},
            upsert=True
        )
        
        await ctx.send(embed=discord.Embed(
            description=f"Log channel set to {channel.mention}", 
            color=self.EMBED_COLOR
        ))
        logger.info(f"Log channel set to {channel.name} for guild {guild_id}")

    async def check_required_role(self, ctx):
        """Check if the user has the required role."""
        guild_id = str(ctx.guild.id)
        
        # Fetch guild configuration
        config = await self.guild_configs.find_one({"guild_id": guild_id})
        
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
        member = member or ctx.author
        
        # Get role mapping
        mapping = await self.role_mappings.find_one({
            "guild_id": guild_id, 
            "custom_name": custom_name
        })
        
        if not mapping:
            await ctx.send(embed=discord.Embed(
                description=f"No role mapped to '{custom_name}'.", 
                color=self.EMBED_COLOR
            ))
            return
        
        # Get role configuration
        config = await self.guild_configs.find_one({"guild_id": guild_id}) or {}
        role_limit = config.get('role_assignment_limit', 5)
        
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
        
        # Check current custom roles
        custom_roles = [r for r in member.roles if r.id in 
                        [m['role_id'] for m in await self.role_mappings.find({"guild_id": guild_id}).to_list(length=None)]]
        
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
        
        # Log the action if log channel is set
        config = await self.guild_configs.find_one({"guild_id": guild_id})
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
            # Find all role mappings for this guild
            mappings = await self.role_mappings.find({"guild_id": guild_id}).to_list(length=None)
            
            for mapping in mappings:
                custom_name = mapping['custom_name']
                
                # Create a dynamic command if it doesn't already exist
                if not hasattr(self, custom_name):
                    async def dynamic_command(ctx, member: discord.Member = None, cn=custom_name):
                        await self.dynamic_role_command(ctx, cn, member)
                    
                    dynamic_command.__name__ = custom_name
                    setattr(self, custom_name, commands.command()(dynamic_command))
                    self.bot.add_command(getattr(self, custom_name))

async def setup(bot):
    await bot.add_cog(RoleManagementCog(bot))
