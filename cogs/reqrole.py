import discord
from discord.ext import commands
import sqlite3
import os

class RoleManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_dir = 'server_databases'
        os.makedirs(self.db_dir, exist_ok=True)

    def get_db_connection(self, guild_id):
        """Create or connect to a server-specific database."""
        db_path = os.path.join(self.db_dir, f'roles_{guild_id}.db')
        conn = sqlite3.connect(db_path)
        return conn

    def init_database(self, guild_id):
        """Initialize database tables for a server."""
        conn = self.get_db_connection(guild_id)
        cursor = conn.cursor()
        
        # Table for required role
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS req_role (
                guild_id INTEGER PRIMARY KEY,
                role_id INTEGER
            )
        ''')
        
        # Table for role mappings
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS role_mappings (
                guild_id INTEGER,
                custom_name TEXT,
                role_id INTEGER,
                PRIMARY KEY (guild_id, custom_name, role_id)
            )
        ''')
        
        # Table for log channel
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS log_channel (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER
            )
        ''')
        
        conn.commit()
        conn.close()

    @commands.command(name='setreqrole')
    @commands.has_permissions(manage_roles=True)
    async def set_req_role(self, ctx, role: discord.Role):
        """Set the role required for role management."""
        guild_id = ctx.guild.id
        self.init_database(guild_id)
        
        conn = self.get_db_connection(guild_id)
        cursor = conn.cursor()
        
        cursor.execute('REPLACE INTO req_role (guild_id, role_id) VALUES (?, ?)', 
                       (guild_id, role.id))
        conn.commit()
        conn.close()
        
        await ctx.send(f'Required role set to {role.mention}')

    @commands.command(name='setrole')
    @commands.has_permissions(manage_roles=True)
    async def set_role_mapping(self, ctx, custom_name: str, role: discord.Role):
        """Map a custom name to a role."""
        guild_id = ctx.guild.id
        self.init_database(guild_id)
        
        conn = self.get_db_connection(guild_id)
        cursor = conn.cursor()
        
        cursor.execute('INSERT OR REPLACE INTO role_mappings (guild_id, custom_name, role_id) VALUES (?, ?, ?)', 
                       (guild_id, custom_name.lower(), role.id))
        conn.commit()
        conn.close()
        
        await ctx.send(f'Mapped "{custom_name}" to {role.mention}')

    @commands.command(name='setlogchannel')
    @commands.has_permissions(manage_channels=True)
    async def set_log_channel(self, ctx, channel: discord.TextChannel):
        """Set the log channel for role actions."""
        guild_id = ctx.guild.id
        self.init_database(guild_id)
        
        conn = self.get_db_connection(guild_id)
        cursor = conn.cursor()
        
        cursor.execute('REPLACE INTO log_channel (guild_id, channel_id) VALUES (?, ?)', 
                       (guild_id, channel.id))
        conn.commit()
        conn.close()
        
        await ctx.send(f'Log channel set to {channel.mention}')

    async def log_role_action(self, guild, user, roles, action):
        """Log role actions to the designated log channel."""
        conn = self.get_db_connection(guild.id)
        cursor = conn.cursor()
        
        cursor.execute('SELECT channel_id FROM log_channel WHERE guild_id = ?', (guild.id,))
        log_channel_id = cursor.fetchone()
        conn.close()
        
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id[0])
            if log_channel:
                roles_str = ', '.join([role.name for role in roles])
                await log_channel.send(f'{action}: {user.mention} - Roles: {roles_str}')

    @commands.command()
    async def reset_all_roles(self, ctx):
        """Reset all role mappings for the server."""
        guild_id = ctx.guild.id
        conn = self.get_db_connection(guild_id)
        cursor = conn.cursor()
        
        # Check if user has required role
        cursor.execute('SELECT role_id FROM req_role WHERE guild_id = ?', (guild_id,))
        req_role_id = cursor.fetchone()
        
        if req_role_id:
            req_role = ctx.guild.get_role(req_role_id[0])
            if req_role not in ctx.author.roles:
                await ctx.send(f'You must have the {req_role.mention} to reset roles.')
                return
        
        # Delete all role mappings
        cursor.execute('DELETE FROM role_mappings WHERE guild_id = ?', (guild_id,))
        conn.commit()
        conn.close()
        
        await ctx.send('All role mappings have been reset.')

    @commands.command()
    async def custom_role_command(self, ctx, custom_name: str, member: discord.Member = None):
        """Dynamic role assignment/removal based on custom name."""
        guild_id = ctx.guild.id
        conn = self.get_db_connection(guild_id)
        cursor = conn.cursor()
        
        # Check for required role if set
        cursor.execute('SELECT role_id FROM req_role WHERE guild_id = ?', (guild_id,))
        req_role_id = cursor.fetchone()
        
        if req_role_id:
            req_role = ctx.guild.get_role(req_role_id[0])
            if req_role not in ctx.author.roles:
                await ctx.send(f'You must have the {req_role.mention} to manage roles.')
                conn.close()
                return
        
        # Find roles mapped to custom name
        cursor.execute('SELECT role_id FROM role_mappings WHERE guild_id = ? AND custom_name = ?', 
                       (guild_id, custom_name.lower()))
        mapped_role_ids = cursor.fetchall()
        conn.close()
        
        if not mapped_role_ids:
            await ctx.send(f'No roles found for "{custom_name}"')
            return
        
        # Use author if no member specified
        target = member or ctx.author
        
        # Collect roles to add/remove
        roles_to_modify = []
        for (role_id,) in mapped_role_ids:
            role = ctx.guild.get_role(role_id)
            if role:
                roles_to_modify.append(role)
        
        # Toggle roles
        if any(role in target.roles for role in roles_to_modify):
            await target.remove_roles(*roles_to_modify)
            await self.log_role_action(ctx.guild, target, roles_to_modify, 'Roles Removed')
            await ctx.send(f'Removed roles from {target.mention}')
        else:
            await target.add_roles(*roles_to_modify)
            await self.log_role_action(ctx.guild, target, roles_to_modify, 'Roles Added')
            await ctx.send(f'Added roles to {target.mention}')

    # Dynamic command registration
    def cog_load(self):
        """Dynamically register custom role commands from database."""
        for guild in self.bot.guilds:
            conn = self.get_db_connection(guild.id)
            cursor = conn.cursor()
            
            # Fetch unique custom names
            cursor.execute('SELECT DISTINCT custom_name FROM role_mappings WHERE guild_id = ?', (guild.id,))
            custom_names = cursor.fetchall()
            conn.close()
            
            # Dynamically add commands for each custom name
            for (name,) in custom_names:
                if not hasattr(self, name):
                    cmd = commands.Command(self.custom_role_command, name=name)
                    self.bot.add_command(cmd)

def setup(bot):
    bot.add_cog(RoleManagement(bot))
