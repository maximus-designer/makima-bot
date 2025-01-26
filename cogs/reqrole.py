import sqlite3
import os
import logging
import discord
from discord.ext import commands

ERROR_COLOR = 0xFF0000

class DatabaseManager:
    def __init__(self, db_path='role_management.db'):
        """
        Initialize database connection and create tables
        
        Args:
            db_path (str): Path to SQLite database file
        """
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self.logger = logging.getLogger(__name__)
        
        # Ensure database directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        self.connect()
        self.create_tables()
        self.close()

    def connect(self):
        """Establish database connection"""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.cursor = self.conn.cursor()
        except sqlite3.Error as e:
            self.logger.error(f"Database connection error: {e}")
            raise

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None

    def create_tables(self):
        """Create necessary tables for role management"""
        try:
            # Servers table to track individual server configurations
            self.cursor.execute(''' 
                CREATE TABLE IF NOT EXISTS servers (
                    guild_id INTEGER PRIMARY KEY,
                    log_channel_id INTEGER,
                    reqrole_id INTEGER,
                    role_assignment_limit INTEGER DEFAULT 5,
                    admin_only_commands BOOLEAN DEFAULT 1
                )
            ''')

            # Role mappings table for dynamic role commands
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS role_mappings (
                    guild_id INTEGER,
                    custom_name TEXT,
                    role_id INTEGER,
                    PRIMARY KEY (guild_id, custom_name, role_id),
                    FOREIGN KEY (guild_id) REFERENCES servers(guild_id)
                )
            ''')

            # Role assignment log
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS role_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    user_id INTEGER,
                    role_id INTEGER,
                    action_type TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            self.conn.commit()
        except sqlite3.Error as e:
            self.logger.error(f"Table creation error: {e}")
            raise

    def add_server(self, guild_id):
        """Add a new server configuration"""
        try:
            self.connect()
            self.cursor.execute('''
                INSERT OR IGNORE INTO servers (guild_id) VALUES (?)
            ''', (guild_id,))
            self.conn.commit()
        except sqlite3.Error as e:
            self.logger.error(f"Error adding server: {e}")
        finally:
            self.close()

    def set_log_channel(self, guild_id, channel_id):
        """Set log channel for a server"""
        try:
            self.connect()
            self.cursor.execute('''
                UPDATE servers SET log_channel_id = ? WHERE guild_id = ?
            ''', (channel_id, guild_id))
            self.conn.commit()
        except sqlite3.Error as e:
            self.logger.error(f"Error setting log channel: {e}")
        finally:
            self.close()

    def add_role_mapping(self, guild_id, custom_name, role_id):
        """Add a role mapping"""
        try:
            self.connect()
            self.cursor.execute('''
                INSERT OR IGNORE INTO role_mappings 
                (guild_id, custom_name, role_id) VALUES (?, ?, ?)
            ''', (guild_id, custom_name, role_id))
            self.conn.commit()
        except sqlite3.Error as e:
            self.logger.error(f"Error adding role mapping: {e}")
        finally:
            self.close()

    def log_role_action(self, guild_id, user_id, role_id, action_type):
        """Log role assignment/removal"""
        try:
            self.connect()
            self.cursor.execute('''
                INSERT INTO role_logs 
                (guild_id, user_id, role_id, action_type) 
                VALUES (?, ?, ?, ?)
            ''', (guild_id, user_id, role_id, action_type))
            self.conn.commit()
        except sqlite3.Error as e:
            self.logger.error(f"Error logging role action: {e}")
        finally:
            self.close()

    def get_server_config(self, guild_id):
        """Retrieve server configuration"""
        try:
            self.connect()
            self.cursor.execute('''
                SELECT * FROM servers WHERE guild_id = ?
            ''', (guild_id,))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            self.logger.error(f"Error retrieving server config: {e}")
            return None
        finally:
            self.close()

    def get_role_mappings(self, guild_id):
        """Retrieve role mappings for a server"""
        try:
            self.connect()
            self.cursor.execute('''
                SELECT custom_name, role_id FROM role_mappings 
                WHERE guild_id = ?
            ''', (guild_id,))
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            self.logger.error(f"Error retrieving role mappings: {e}")
            return []
        finally:
            self.close()


class RoleManagementBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager()
        self.emojis = {'error': '❌'}

    async def check_authorization(self, ctx, admin_required=False):
        """
        Check user authorization based on admin or required role settings.
        
        Args:
            ctx (commands.Context): The context of the command
            admin_required (bool): Whether the command requires admin permissions
        
        Returns:
            bool: True if authorized, False otherwise
        """
        config = self.db.get_server_config(ctx.guild.id)
        
        # Always allow administrators
        if ctx.author.guild_permissions.administrator:
            return True
        
        # Check if admin-only commands are enforced
        if admin_required and config and config.get('admin_only_commands', True):
            await self.admin_only_command(ctx)
            return False
        
        # Check for required role if set
        reqrole_id = config.get('reqrole_id') if config else None
        if reqrole_id:
            reqrole = ctx.guild.get_role(reqrole_id)
            if not reqrole or reqrole not in ctx.author.roles:
                embed = discord.Embed(
                    title=f"{self.emojis['error']} Permission Denied", 
                    description=f"You must have the {reqrole.mention} role to use this command.", 
                    color=ERROR_COLOR
                )
                await ctx.send(embed=embed)
                
                # Log unauthorized access attempt
                await self.log_activity(
                    ctx.guild, 
                    "Unauthorized Command", 
                    f"{ctx.author.name} attempted to use a role-restricted command"
                )
                return False
        
        return True

    async def can_modify_roles(self, ctx, member):
        """
        Check if a user can modify roles for another member.
        
        Args:
            ctx (commands.Context): The context of the command
            member (discord.Member): The member whose roles are being modified
        
        Returns:
            bool: True if role modification is allowed, False otherwise
        """
        # Always allow administrators
        if ctx.author.guild_permissions.administrator:
            return True
        
        # Prevent modifying roles for other users by default
        if member.id != ctx.author.id:
            embed = discord.Embed(
                title=f"{self.emojis['error']} Permission Denied", 
                description="You cannot modify roles for other members.", 
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            
            # Log unauthorized role modification attempt
            await self.log_activity(
                ctx.guild, 
                "Unauthorized Role Modification", 
                f"{ctx.author.name} attempted to modify roles for {member.name}"
            )
            return False
        
        return True

    @commands.command()
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        """Set the log channel for server activities."""
        if not await self.check_authorization(ctx, admin_required=True):
            return
        
        # Set the log channel
        self.db.set_log_channel(ctx.guild.id, channel.id)
        await ctx.send(f"Log channel has been set to {channel.mention}")

    @commands.command()
    async def reqrole(self, ctx, role: discord.Role):
        """Set the required role for role management commands."""
        if not await self.check_authorization(ctx, admin_required=True):
            return
        
        # Set the required role
        self.db.set_reqrole(ctx.guild.id, role.id)
        await ctx.send(f"Required role has been set to {role.mention}")

    @commands.command()
    async def dynamic_role_command(self, ctx, member: discord.Member = None, custom_name=None):
        server_config = self.db.get_server_config(ctx.guild.id)
        member = member or ctx.author
        
        # Add role modification permission check
        if not await self.can_modify_roles(ctx, member):
            return
        
        # Add dynamic role handling code here
        # Example:
        if custom_name:
            # Implement role assignment logic
            pass
        
        await ctx.send(f"Role for {member.name} has been updated.")

    async def log_activity(self, guild, action, description):
        """Log activity for the server."""
        self.db.log_role_action(
            guild.id, 
            0,  # This is a placeholder user ID for logging purposes.
            0,  # Placeholder role ID
            action
        )


bot = commands.Bot(command_prefix='!')

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

bot.add_cog(RoleManagementBot(bot))

bot.run('YOUR_BOT_TOKEN')
