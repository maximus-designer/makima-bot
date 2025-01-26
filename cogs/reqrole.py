import discord
import logging
import os
import sqlite3
from discord.ext import commands

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enhanced color palette
EMBED_COLOR = 0x2f2136
SUCCESS_COLOR = 0x2ecc71
ERROR_COLOR = 0xe74c3c
INFO_COLOR = 0x3498db
WARNING_COLOR = 0xf39c12


class DatabaseManager:
    def __init__(self, db_path='role_management.db'):
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self.logger = logging.getLogger(__name__)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.connect()
        self.create_tables()
        self.close()

    def connect(self):
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.cursor = self.conn.cursor()
        except sqlite3.Error as e:
            self.logger.error(f"Database connection error: {e}")
            raise

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None

    def create_tables(self):
        try:
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS servers (
                    guild_id INTEGER PRIMARY KEY,
                    log_channel_id INTEGER,
                    reqrole_id INTEGER,
                    role_assignment_limit INTEGER DEFAULT 5,
                    admin_only_commands BOOLEAN DEFAULT 1
                )
            ''')
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS role_mappings (
                    guild_id INTEGER,
                    custom_name TEXT,
                    role_id INTEGER,
                    PRIMARY KEY (guild_id, custom_name, role_id),
                    FOREIGN KEY (guild_id) REFERENCES servers(guild_id)
                )
            ''')
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

    def get_server_config(self, guild_id):
        try:
            self.connect()
            self.cursor.execute('SELECT * FROM servers WHERE guild_id = ?', (guild_id,))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            self.logger.error(f"Error retrieving server config: {e}")
            return None
        finally:
            self.close()

    def set_log_channel(self, guild_id, channel_id):
        try:
            self.connect()
            self.cursor.execute('UPDATE servers SET log_channel_id = ? WHERE guild_id = ?', (channel_id, guild_id))
            self.conn.commit()
        except sqlite3.Error as e:
            self.logger.error(f"Error setting log channel: {e}")
        finally:
            self.close()


class RoleManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager()
        self.emojis = {
            'success': '✅',
            'error': '❌',
            'info': 'ℹ️',
            'warning': '⚠️',
            'roles': '🛡️',
            'log': '📋'
        }

    async def log_activity(self, guild, action, details):
        config = self.db.get_server_config(guild.id)
        log_channel_id = config[1] if config else None

        if log_channel_id:
            try:
                log_channel = guild.get_channel(log_channel_id)
                if log_channel:
                    embed = discord.Embed(
                        title=f"{self.emojis['log']} Activity Log",
                        description=f"**Action:** {action}\n**Details:** {details}",
                        color=INFO_COLOR
                    )
                    await log_channel.send(embed=embed)
            except Exception as e:
                logger.error(f"Logging error: {e}")

    async def check_authorization(self, ctx, admin_required=False):
        """
        Check user authorization based on admin or required role settings.
        """
        config = self.db.get_server_config(ctx.guild.id)
        if not config:
            await ctx.send("Server configuration not found.")
            return False

        # Always allow administrators
        if ctx.author.guild_permissions.administrator:
            return True

        # Check if admin-only commands are enforced
        if admin_required and config[4]:  # admin_only_commands is at index 4
            embed = discord.Embed(
                title=f"{self.emojis['error']} Admin Only",
                description="This command is restricted to administrators.",
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            return False

        # Check for required role if set
        reqrole_id = config[2]  # reqrole_id is at index 2
        if reqrole_id:
            reqrole = ctx.guild.get_role(reqrole_id)
            if not reqrole or reqrole not in ctx.author.roles:
                embed = discord.Embed(
                    title=f"{self.emojis['error']} Permission Denied",
                    description=f"You must have the {reqrole.mention} role to use this command.",
                    color=ERROR_COLOR
                )
                await ctx.send(embed=embed)
                await self.log_activity(
                    ctx.guild,
                    "Unauthorized Command",
                    f"{ctx.author.name} attempted to use a role-restricted command"
                )
                return False

        return True

    @commands.command()
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        """Set the log channel for server activities."""
        if not await self.check_authorization(ctx, admin_required=True):
            return

        self.db.set_log_channel(ctx.guild.id, channel.id)
        embed = discord.Embed(
            title=f"{self.emojis['success']} Log Channel Set",
            description=f"Logging activities to {channel.mention}",
            color=SUCCESS_COLOR
        )
        await ctx.send(embed=embed)

        await self.log_activity(ctx.guild, "Log Channel Setup", f"Log channel set to {channel.name}")

    @commands.command()
    async def reqrole(self, ctx, role: discord.Role):
        """Set the required role for role management commands."""
        if not await self.check_authorization(ctx, admin_required=True):
            return

        config = self.db.get_server_config(ctx.guild.id)
        if not config:
            await ctx.send("Server configuration not found.")
            return

        self.db.set_reqrole(ctx.guild.id, role.id)
        embed = discord.Embed(
            title=f"{self.emojis['success']} Required Role Set",
            description=f"The required role for commands is now {role.mention}.",
            color=SUCCESS_COLOR
        )
        await ctx.send(embed=embed)

        await self.log_activity(ctx.guild, "Required Role Set", f"Required role set to {role.name}")

async def setup(bot):
    await bot.add_cog(RoleManagement(bot))
