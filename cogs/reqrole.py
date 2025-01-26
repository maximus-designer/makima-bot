import discord
import logging
import os
import json
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

class RoleManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_dir = 'server_configs'
        os.makedirs(self.config_dir, exist_ok=True)
        
        # Initialize SQLite database for role mappings
        self.db_path = os.path.join(self.config_dir, 'role_mappings.db')
        self.init_database()
        
        self.emojis = {
            'success': '✅',
            'error': '❌',
            'info': 'ℹ️',
            'warning': '⚠️',
            'roles': '🛡️',
            'log': '📋'
        }

    def init_database(self):
        """Initialize SQLite database for persistent role mappings."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS role_mappings (
                    guild_id INTEGER,
                    custom_name TEXT,
                    role_id INTEGER,
                    PRIMARY KEY (guild_id, custom_name, role_id)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS server_configs (
                    guild_id INTEGER PRIMARY KEY,
                    log_channel_id INTEGER,
                    reqrole_id INTEGER,
                    role_assignment_limit INTEGER DEFAULT 5,
                    admin_only_commands INTEGER DEFAULT 1
                )
            ''')
            conn.commit()

    def get_config_path(self, guild_id):
        """Get JSON config file path for backward compatibility."""
        return os.path.join(self.config_dir, f'{guild_id}.json')

    def load_configs(self, guild_id):
        """Load server configurations from JSON for backward compatibility."""
        config_path = self.get_config_path(guild_id)
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def save_configs(self, guild_id, config):
        """Save server configurations to JSON for backward compatibility."""
        config_path = self.get_config_path(guild_id)
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=4)

    def get_server_config(self, guild_id):
        """Get or create server configuration."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT log_channel_id, reqrole_id, role_assignment_limit, admin_only_commands 
                FROM server_configs 
                WHERE guild_id = ?
            ''', (guild_id,))
            result = cursor.fetchone()
            
            if not result:
                # Default configuration
                default_config = {
                    'role_mappings': {},
                    'reqrole_id': None,
                    'log_channel_id': None,
                    'role_assignment_limit': 5,
                    'admin_only_commands': True
                }
                # Save to SQLite
                cursor.execute('''
                    INSERT INTO server_configs 
                    (guild_id, log_channel_id, reqrole_id, role_assignment_limit, admin_only_commands) 
                    VALUES (?, ?, ?, ?, ?)
                ''', (guild_id, None, None, 5, 1))
                conn.commit()
                
                # Backward compatibility - save to JSON
                self.save_configs(guild_id, default_config)
                return default_config
            
            # Convert result to dict
            log_channel_id, reqrole_id, role_assignment_limit, admin_only_commands = result
            return {
                'role_mappings': self.get_role_mappings(guild_id),
                'reqrole_id': reqrole_id,
                'log_channel_id': log_channel_id,
                'role_assignment_limit': role_assignment_limit,
                'admin_only_commands': bool(admin_only_commands)
            }

    async def log_activity(self, guild, action, details):
        """Log activities to the designated log channel."""
        config = self.get_server_config(guild.id)
        log_channel_id = config.get('log_channel_id')
        
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

    async def check_role_permission(self, ctx):
        """
        Check if the user has permission to assign roles.
        Returns a tuple (is_allowed, error_message)
        """
        config = self.get_server_config(ctx.guild.id)
        req_role_id = config.get('reqrole_id')

        # Admin check
        if ctx.author.guild_permissions.administrator:
            return True, None

        # Required role check
        if req_role_id:
            req_role = ctx.guild.get_role(req_role_id)
            if req_role in ctx.author.roles:
                return True, None
            return False, (
                f"{self.emojis['error']} Permission Denied", 
                f"You must have the {req_role.mention} role to manage roles."
            )

        # No specific requirements set
        return False, (
            f"{self.emojis['error']} Role Management Disabled", 
            "Role management has not been configured for this server."
        )

    async def admin_only_command(self, ctx):
        """Handle unauthorized admin command attempts."""
        embed = discord.Embed(
            title=f"{self.emojis['error']} Permission Denied", 
            description="You must be a server administrator to use this command.", 
            color=ERROR_COLOR
        )
        await ctx.send(embed=embed)
        
        # Log unauthorized access attempt
        await self.log_activity(
            ctx.guild, 
            "Unauthorized Command", 
            f"{ctx.author.name} attempted to use an admin-only command"
        )

    # Rest of the methods from previous implementation follow the same pattern
    # (setlogchannel, reqrole, setrole, reset_role, create_dynamic_role_commands, 
    # on_ready, rolehelp would be implemented similarly to previous version)

    def save_role_mapping(self, guild_id, custom_name, role_id):
        """Save role mapping to SQLite database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO role_mappings (guild_id, custom_name, role_id)
                VALUES (?, ?, ?)
            ''', (guild_id, custom_name, role_id))
            conn.commit()

    def get_role_mappings(self, guild_id):
        """Retrieve role mappings for a specific guild."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT custom_name, role_id 
                FROM role_mappings 
                WHERE guild_id = ?
            ''', (guild_id,))
            mappings = {}
            for custom_name, role_id in cursor.fetchall():
                if custom_name not in mappings:
                    mappings[custom_name] = []
                mappings[custom_name].append(role_id)
            return mappings

    def delete_role_mapping(self, guild_id, custom_name=None):
        """Delete role mappings, optionally filtered by custom name."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if custom_name:
                cursor.execute('''
                    DELETE FROM role_mappings 
                    WHERE guild_id = ? AND custom_name = ?
                ''', (guild_id, custom_name))
            else:
                cursor.execute('''
                    DELETE FROM role_mappings 
                    WHERE guild_id = ?
                ''', (guild_id,))
            conn.commit()

    # All other methods from the original implementation would be preserved here

async def setup(bot):
    await bot.add_cog(RoleManagement(bot))
