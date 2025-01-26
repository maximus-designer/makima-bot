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

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info(f'Role Management Cog is ready. Logged in as {self.bot.user}')

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def reset_all_roles(self, ctx):
        """Reset all custom roles for the current server."""
        guild_id = str(ctx.guild.id)
        
        # Find all custom role mappings for this guild
        role_mappings = await self.role_mappings.find({"guild_id": guild_id}).to_list(length=None)
        
        if not role_mappings:
            await ctx.send(embed=discord.Embed(
                description="No custom role mappings found for this server.", 
                color=self.EMBED_COLOR
            ))
            return
        
        # Collect roles to remove
        roles_to_remove = []
        for mapping in role_mappings:
            role = ctx.guild.get_role(mapping['role_id'])
            if role:
                roles_to_remove.append(role)
        
        # Remove custom roles from all members
        removed_count = 0
        for member in ctx.guild.members:
            member_roles = [role for role in member.roles if role in roles_to_remove]
            if member_roles:
                await member.remove_roles(*member_roles)
                removed_count += 1
        
        # Send confirmation
        await ctx.send(embed=discord.Embed(
            description=f"Removed custom roles from {removed_count} members.", 
            color=self.EMBED_COLOR
        ))
        
        # Log the action
        logger.info(f"Reset all custom roles for guild {guild_id}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def set_role_limit(self, ctx, limit: int):
        """Set the maximum number of custom roles per user for the server."""
        guild_id = str(ctx.guild.id)
        
        # Update or create guild configuration
        await self.guild_configs.update_one(
            {"guild_id": guild_id},
            {"$set": {"role_assignment_limit": limit}},
            upsert=True
        )
        
        await ctx.send(embed=discord.Embed(
            description=f"Role assignment limit set to {limit} for this server.", 
            color=self.EMBED_COLOR
        ))

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def map_role(self, ctx, custom_name: str, role: discord.Role):
        """Map a custom role name to an existing role."""
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
    async def assign_role(self, ctx, custom_name: str, member: discord.Member = None):
        """Assign or remove a custom role."""
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
                    description=f"You've reached the maximum of {role_limit} custom roles.", 
                    color=self.EMBED_COLOR
                ))
                return
            
            # Add role
            await member.add_roles(role)
            action = "assigned"
        
        await ctx.send(embed=discord.Embed(
            description=f"{action.capitalize()} {custom_name} role to {member.mention}", 
            color=self.EMBED_COLOR
        ))

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def unmap_role(self, ctx, custom_name: str):
        """Remove a role mapping."""
        guild_id = str(ctx.guild.id)
        
        result = await self.role_mappings.delete_one({
            "guild_id": guild_id, 
            "custom_name": custom_name
        })
        
        if result.deleted_count:
            await ctx.send(embed=discord.Embed(
                description=f"Unmapped role '{custom_name}'.", 
                color=self.EMBED_COLOR
            ))
        else:
            await ctx.send(embed=discord.Embed(
                description=f"No role mapping found for '{custom_name}'.", 
                color=self.EMBED_COLOR
            ))

async def setup(bot):
    await bot.add_cog(RoleManagementCog(bot))
