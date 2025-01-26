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

    def get_guild_collections(self, guild_id):
        """Get database collections for a specific guild."""
        db = self.mongo_client[f'discord_role_management_{guild_id}']
        return {
            'configs': db['guild_configurations'],
            'roles': db['role_mappings']
        }

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setrole(self, ctx, custom_name: str, role: discord.Role):
        """Map a custom name to a role with improved handling."""
        collections = self.get_guild_collections(str(ctx.guild.id))
        
        # Validate role hierarchy
        if role.position >= ctx.guild.me.top_role.position:
            await ctx.send(embed=discord.Embed(
                description="Cannot map a role higher than my top role.", 
                color=self.EMBED_COLOR
            ))
            return
        
        # Normalize custom name (lowercase, replace spaces)
        normalized_name = custom_name.lower().replace(' ', '_')
        
        # Store role mapping
        await collections['roles'].update_one(
            {"custom_name": normalized_name},
            {"$set": {
                "role_id": role.id, 
                "role_name": role.name,
                "guild_id": str(ctx.guild.id)
            }},
            upsert=True
        )
        
        await ctx.send(embed=discord.Embed(
            description=f"Mapped '{normalized_name}' to role {role.name}", 
            color=self.EMBED_COLOR
        ))

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def reset_mapped_roles(self, ctx, confirmation: str = None):
        """Reset all mapped roles for the server."""
        collections = self.get_guild_collections(str(ctx.guild.id))
        
        # Confirmation check
        if confirmation != "confirm":
            await ctx.send(embed=discord.Embed(
                title="⚠️ Role Reset Confirmation",
                description=(
                    "This will remove ALL mapped roles from server members.\n\n"
                    "To proceed, type `.reset_mapped_roles confirm`\n"
                    "This action cannot be undone!"
                ), 
                color=self.EMBED_COLOR
            ))
            return
        
        # Fetch all mapped role IDs
        mapped_roles = await collections['roles'].find().to_list(length=None)
        
        if not mapped_roles:
            await ctx.send(embed=discord.Embed(
                description="No mapped roles found for this server.", 
                color=self.EMBED_COLOR
            ))
            return
        
        # Get role IDs
        mapped_role_ids = [role['role_id'] for role in mapped_roles]
        
        # Remove mapped roles from members
        removed_count = 0
        for member in ctx.guild.members:
            # Find roles to remove (only those mapped)
            roles_to_remove = [
                role for role in member.roles 
                if role.id in mapped_role_ids
            ]
            
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove)
                removed_count += 1
        
        # Clear role mappings from database
        await collections['roles'].delete_many({})
        
        # Send confirmation
        await ctx.send(embed=discord.Embed(
            description=f"Removed mapped roles from {removed_count} members and cleared all role mappings.", 
            color=self.EMBED_COLOR
        ))
        
        logger.info(f"Reset all mapped roles for guild {ctx.guild.id}")

    async def get_mapped_role(self, guild_id, custom_name):
        """Retrieve mapped role with normalized name."""
        collections = self.get_guild_collections(str(guild_id))
        normalized_name = custom_name.lower().replace(' ', '_')
        
        return await collections['roles'].find_one({"custom_name": normalized_name})

    async def dynamic_role_command(self, ctx, custom_name: str, member: discord.Member = None):
        """Dynamic role assignment handler."""
        member = member or ctx.author
        
        # Find mapped role
        mapped_role = await self.get_mapped_role(ctx.guild.id, custom_name)
        
        if not mapped_role:
            await ctx.send(embed=discord.Embed(
                description=f"No role mapped to '{custom_name}'.", 
                color=self.EMBED_COLOR
            ))
            return
        
        # Get the actual role object
        role = ctx.guild.get_role(mapped_role['role_id'])
        
        if not role:
            await ctx.send(embed=discord.Embed(
                description="The mapped role no longer exists.", 
                color=self.EMBED_COLOR
            ))
            return
        
        # Toggle role
        if role in member.roles:
            await member.remove_roles(role)
            action = "removed"
        else:
            await member.add_roles(role)
            action = "assigned"
        
        await ctx.send(embed=discord.Embed(
            description=f"{action.capitalize()} {custom_name} role to {member.mention}", 
            color=self.EMBED_COLOR
        ))

    async def cog_load(self):
        """Generate dynamic commands for each custom role."""
        for guild in self.bot.guilds:
            collections = self.get_guild_collections(str(guild.id))
            
            # Find all role mappings
            mapped_roles = await collections['roles'].find().to_list(length=None)
            
            for role_map in mapped_roles:
                custom_name = role_map['custom_name']
                
                # Create dynamic command
                async def dynamic_command(ctx, member: discord.Member = None, cn=custom_name):
                    await self.dynamic_role_command(ctx, cn, member)
                
                dynamic_command.__name__ = custom_name
                setattr(self, custom_name, commands.command()(dynamic_command))
                self.bot.add_command(getattr(self, custom_name))

async def setup(bot):
    await bot.add_cog(RoleManagementCog(bot))
