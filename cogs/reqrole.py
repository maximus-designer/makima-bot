import discord
from discord.ext import commands
import sqlite3
import os

class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.create_tables()

    def create_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.executescript('''
                CREATE TABLE IF NOT EXISTS req_role (
                    guild_id INTEGER PRIMARY KEY,
                    role_id INTEGER
                );
                CREATE TABLE IF NOT EXISTS role_mappings (
                    guild_id INTEGER,
                    custom_name TEXT,
                    role_id INTEGER,
                    PRIMARY KEY (guild_id, custom_name, role_id)
                );
                CREATE TABLE IF NOT EXISTS log_channel (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER
                );
            ''')
            conn.commit()

    def set_req_role(self, guild_id, role_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('REPLACE INTO req_role (guild_id, role_id) VALUES (?, ?)', 
                           (guild_id, role_id))
            conn.commit()

    def set_role_mapping(self, guild_id, custom_name, role_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO role_mappings (guild_id, custom_name, role_id) VALUES (?, ?, ?)', 
                           (guild_id, custom_name.lower(), role_id))
            conn.commit()

    def set_log_channel(self, guild_id, channel_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('REPLACE INTO log_channel (guild_id, channel_id) VALUES (?, ?)', 
                           (guild_id, channel_id))
            conn.commit()

    def get_req_role(self, guild_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT role_id FROM req_role WHERE guild_id = ?', (guild_id,))
            return cursor.fetchone()

    def get_role_mappings(self, guild_id, custom_name):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT role_id FROM role_mappings WHERE guild_id = ? AND custom_name = ?', 
                           (guild_id, custom_name.lower()))
            return cursor.fetchall()

    def get_log_channel(self, guild_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT channel_id FROM log_channel WHERE guild_id = ?', (guild_id,))
            return cursor.fetchone()

    def reset_role_mappings(self, guild_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM role_mappings WHERE guild_id = ?', (guild_id,))
            conn.commit()

class RoleManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        os.makedirs('databases', exist_ok=True)
        self.db_managers = {}

    def get_db_manager(self, guild_id):
        if guild_id not in self.db_managers:
            db_path = f'databases/roles_{guild_id}.db'
            self.db_managers[guild_id] = DatabaseManager(db_path)
        return self.db_managers[guild_id]

    @commands.command(name='setreqrole')
    @commands.has_permissions(manage_roles=True)
    async def set_req_role(self, ctx, role: discord.Role):
        db = self.get_db_manager(ctx.guild.id)
        db.set_req_role(ctx.guild.id, role.id)
        await ctx.send(f'Required role set to {role.mention}')

    @commands.command(name='setrole')
    @commands.has_permissions(manage_roles=True)
    async def set_role_mapping(self, ctx, custom_name: str, role: discord.Role):
        db = self.get_db_manager(ctx.guild.id)
        db.set_role_mapping(ctx.guild.id, custom_name, role.id)
        await ctx.send(f'Mapped "{custom_name}" to {role.mention}')

    @commands.command(name='setlogchannel')
    @commands.has_permissions(manage_channels=True)
    async def set_log_channel(self, ctx, channel: discord.TextChannel):
        db = self.get_db_manager(ctx.guild.id)
        db.set_log_channel(ctx.guild.id, channel.id)
        await ctx.send(f'Log channel set to {channel.mention}')

    @commands.command(name='reset_all_roles')
    @commands.has_permissions(manage_roles=True)
    async def reset_all_roles(self, ctx):
        db = self.get_db_manager(ctx.guild.id)
        db.reset_role_mappings(ctx.guild.id)
        await ctx.send('All role mappings have been reset.')

    @commands.command()
    async def custom_role_command(self, ctx, custom_name: str, member: discord.Member = None):
        db = self.get_db_manager(ctx.guild.id)
        
        # Check required role
        req_role_id = db.get_req_role(ctx.guild.id)
        if req_role_id and ctx.guild.get_role(req_role_id[0]) not in ctx.author.roles:
            return await ctx.send('Insufficient permissions.')

        # Get mapped roles
        mapped_role_ids = db.get_role_mappings(ctx.guild.id, custom_name)
        if not mapped_role_ids:
            return await ctx.send(f'No roles found for "{custom_name}"')

        # Determine target and roles
        target = member or ctx.author
        roles_to_modify = [ctx.guild.get_role(role_id[0]) for role_id in mapped_role_ids if ctx.guild.get_role(role_id[0])]

        # Toggle roles
        if any(role in target.roles for role in roles_to_modify):
            await target.remove_roles(*roles_to_modify)
            await ctx.send(f'Removed roles from {target.mention}')
        else:
            await target.add_roles(*roles_to_modify)
            await ctx.send(f'Added roles to {target.mention}')

def setup(bot):
    bot.add_cog(RoleManagement(bot))
