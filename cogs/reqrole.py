import os
import logging
import discord
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RoleManagementSystem:
    def __init__(self, bot):
        self.bot = bot
        self.mongo_client = None
        self.db = None
        
    async def connect_to_database(self):
        """Establish secure MongoDB connection."""
        try:
            mongo_uri = os.getenv('MONGO_URL')  # Changed to MONGO_URL
            if not mongo_uri:
                raise ValueError("MongoDB connection string not found in environment variables")
            
            self.mongo_client = AsyncIOMotorClient(mongo_uri)
            self.db = self.mongo_client['role_management']
            logger.info("Successfully connected to MongoDB")
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            raise

class RoleManagementCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.role_system = RoleManagementSystem(bot)
        
    async def cog_load(self):
        """Initialize database connection on cog load."""
        await self.role_system.connect_to_database()
    
    @commands.command(name="reset_all_roles")
    @commands.has_permissions(manage_roles=True)
    async def reset_all_roles(self, ctx, member: discord.Member = None):
        """
        Reset all custom roles for a user across multiple servers.
        
        Args:
            ctx (commands.Context): Command context
            member (discord.Member, optional): Member to reset roles for. Defaults to command invoker.
        """
        # Default to command invoker if no member specified
        target_member = member or ctx.author
        
        try:
            # Retrieve user's role data from database
            user_roles_doc = await self.role_system.db.user_roles.find_one(
                {"user_id": target_member.id}
            )
            
            if not user_roles_doc:
                await ctx.send(embed=discord.Embed(
                    description="No custom roles found to reset.",
                    color=discord.Color.orange()
                ))
                return
            
            # Track role reset statistics
            reset_count = 0
            failed_resets = []
            
            # Process role resets across all servers
            for guild_id, role_ids in user_roles_doc.get('roles', {}).items():
                try:
                    guild = self.bot.get_guild(int(guild_id))
                    if not guild:
                        continue
                    
                    member_in_guild = guild.get_member(target_member.id)
                    if not member_in_guild:
                        continue
                    
                    # Remove roles
                    roles_to_remove = [
                        guild.get_role(role_id) 
                        for role_id in role_ids 
                        if guild.get_role(role_id)
                    ]
                    
                    await member_in_guild.remove_roles(*roles_to_remove)
                    reset_count += len(roles_to_remove)
                
                except Exception as guild_error:
                    logger.error(f"Role reset error in guild {guild_id}: {guild_error}")
                    failed_resets.append(guild_id)
            
            # Clear user's role data in database
            await self.role_system.db.user_roles.delete_one(
                {"user_id": target_member.id}
            )
            
            # Construct comprehensive response
            embed = discord.Embed(
                title="🔄 Role Reset Summary",
                color=discord.Color.green()
            )
            embed.add_field(name="Target", value=target_member.mention, inline=False)
            embed.add_field(name="Roles Reset", value=str(reset_count), inline=True)
            
            if failed_resets:
                embed.add_field(
                    name="Failed Guilds", 
                    value=f"{len(failed_resets)} guilds could not complete reset", 
                    inline=True
                )
            
            await ctx.send(embed=embed)
        
        except Exception as e:
            logger.error(f"Comprehensive role reset error: {e}")
            await ctx.send(embed=discord.Embed(
                description="An unexpected error occurred during role reset.",
                color=discord.Color.red()
            ))

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        """
        Automatically clean up role references when a role is deleted.
        
        Args:
            role (discord.Role): Deleted role
        """
        try:
            # Remove role references from database
            result = await self.role_system.db.user_roles.update_many(
                {f"roles.{role.guild.id}": role.id},
                {"$pull": {f"roles.{role.guild.id}": role.id}}
            )
            
            logger.info(f"Cleaned up {result.modified_count} role references after role deletion")
        except Exception as e:
            logger.error(f"Role cleanup error: {e}")

async def setup(bot):
    await bot.add_cog(RoleManagementCog(bot))
