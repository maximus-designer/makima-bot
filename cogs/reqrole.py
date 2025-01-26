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
        self.db_name = 'role_mappings.db'
        self.create_db()
        self.emojis = {
            'success': '✅',
            'error': '❌',
            'info': 'ℹ️',
            'warning': '⚠️',
            'roles': '🛡️',
            'log': '📋'
        }

    def create_db(self):
        """Create the database and tables if they don't exist."""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS server_configs (
                            guild_id INTEGER PRIMARY KEY,
                            reqrole_id INTEGER,
                            log_channel_id INTEGER,
                            role_assignment_limit INTEGER,
                            admin_only_commands BOOLEAN)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS role_mappings (
                            guild_id INTEGER,
                            custom_name TEXT,
                            role_id INTEGER,
                            PRIMARY KEY (guild_id, custom_name, role_id))''')
        conn.commit()
        conn.close()

    def get_server_config(self, guild_id):
        """Get or create server configuration from database."""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM server_configs WHERE guild_id = ?", (guild_id,))
        result = cursor.fetchone()
        
        if result is None:
            config = {
                'reqrole_id': None,
                'log_channel_id': None,
                'role_assignment_limit': 5,
                'admin_only_commands': True
            }
            cursor.execute("INSERT INTO server_configs (guild_id, reqrole_id, log_channel_id, role_assignment_limit, admin_only_commands) VALUES (?, ?, ?, ?, ?)",
                           (guild_id, config['reqrole_id'], config['log_channel_id'], config['role_assignment_limit'], config['admin_only_commands']))
            conn.commit()
        else:
            config = {
                'reqrole_id': result[1],
                'log_channel_id': result[2],
                'role_assignment_limit': result[3],
                'admin_only_commands': result[4]
            }
        conn.close()
        return config

    def save_server_config(self, guild_id, config):
        """Save server configuration to the database."""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("UPDATE server_configs SET reqrole_id = ?, log_channel_id = ?, role_assignment_limit = ?, admin_only_commands = ? WHERE guild_id = ?",
                       (config['reqrole_id'], config['log_channel_id'], config['role_assignment_limit'], config['admin_only_commands'], guild_id))
        conn.commit()
        conn.close()

    def get_role_mappings(self, guild_id):
        """Get all role mappings for a server."""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("SELECT custom_name, role_id FROM role_mappings WHERE guild_id = ?", (guild_id,))
        mappings = cursor.fetchall()
        conn.close()
        return {mapping[0]: [mapping[1]] for mapping in mappings}

    def save_role_mapping(self, guild_id, custom_name, role_id):
        """Save a role mapping for a server."""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO role_mappings (guild_id, custom_name, role_id) VALUES (?, ?, ?)",
                       (guild_id, custom_name, role_id))
        conn.commit()
        conn.close()

    def delete_role_mapping(self, guild_id, custom_name):
        """Delete all role mappings for a server."""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM role_mappings WHERE guild_id = ? AND custom_name = ?", (guild_id, custom_name))
        conn.commit()
        conn.close()

    async def check_required_role(self, ctx):
        """Check if user has the required role or is an administrator."""
        config = self.get_server_config(ctx.guild.id)
        reqrole_id = config.get('reqrole_id')
        
        # Always allow administrators
        if ctx.author.guild_permissions.administrator:
            return True
        
        if not reqrole_id:
            return True
        
        reqrole = ctx.guild.get_role(reqrole_id)
        if not reqrole:
            embed = discord.Embed(
                title=f"{self.emojis['error']} Configuration Error", 
                description="Required role is no longer valid.", 
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            return False
        
        if reqrole not in ctx.author.roles:
            embed = discord.Embed(
                title=f"{self.emojis['error']} Permission Denied", 
                description=f"You need the {reqrole.mention} role to use this command.", 
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            return False
        
        return True

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

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        """Set the log channel for server activities."""
        config = self.get_server_config(ctx.guild.id)
        config['log_channel_id'] = channel.id
        self.save_server_config(ctx.guild.id, config)
        
        embed = discord.Embed(
            title=f"{self.emojis['success']} Log Channel Set", 
            description=f"Logging activities to {channel.mention}", 
            color=SUCCESS_COLOR
        )
        await ctx.send(embed=embed)
        
        await self.log_activity(ctx.guild, "Log Channel Setup", f"Log channel set to {channel.name}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def reqrole(self, ctx, role: discord.Role):
        """Set the required role for role management commands."""
        config = self.get_server_config(ctx.guild.id)
        config['reqrole_id'] = role.id
        self.save_server_config(ctx.guild.id, config)
        
        embed = discord.Embed(
            title=f"{self.emojis['roles']} Required Role Set", 
            description=f"Only members with {role.mention} can now manage roles.", 
            color=SUCCESS_COLOR
        )
        await ctx.send(embed=embed)
        
        await self.log_activity(ctx.guild, "Required Role Updated", f"New required role: {role.name}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setrole(self, ctx, custom_name: str, role: discord.Role):
        """Map a custom role name to a role."""
        config = self.get_server_config(ctx.guild.id)
        
        self.save_role_mapping(ctx.guild.id, custom_name, role.id)
        
        embed = discord.Embed(
            title=f"{self.emojis['success']} Role Mapping Added", 
            description=f"Mapped '{custom_name}' to {role.mention}", 
            color=SUCCESS_COLOR
        )
        await ctx.send(embed=embed)
        
        await self.log_activity(ctx.guild, "Role Mapping", f"Mapped '{custom_name}' to {role.name}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def reset_roles(self, ctx):
        """Reset all role mappings for the server."""
        if not await self.check_required_role(ctx):
            return

        class ConfirmView(discord.ui.View):
            def __init__(self, ctx, cog):
                super().__init__()
                self.ctx = ctx
                self.cog = cog

            @discord.ui.button(label="Confirm Reset", style=discord.ButtonStyle.red)
            async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.cog.delete_role_mapping(self.ctx.guild.id, '*')
                embed = discord.Embed(
                    title=f"{self.cog.emojis['warning']} Role Mappings Reset", 
                    description="All role mappings have been cleared.", 
                    color=SUCCESS_COLOR
                )
                await interaction.response.send_message(embed=embed)
                await self.cog.log_activity(self.ctx.guild, "Role Mapping Reset", "All role mappings cleared")
                self.stop()

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
            async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                embed = discord.Embed(
                    title=f"{self.cog.emojis['error']} Reset Cancelled", 
                    description="Role mapping reset was cancelled.", 
                    color=ERROR_COLOR
                )
                await interaction.response.send_message(embed=embed)
                self.stop()

        embed = discord.Embed(
            title=f"{self.emojis['warning']} Reset Role Mappings", 
            description="Are you sure you want to reset all role mappings for this server?", 
            color=ERROR_COLOR
        )
        view = ConfirmView(ctx, self)
        await ctx.send(embed=embed, view=view)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def reset_specific_role(self, ctx, custom_name: str):
        """Reset a specific role mapping for the server."""
        if not await self.check_required_role(ctx):
            return

        config = self.get_server_config(ctx.guild.id)
        
        if custom_name not in config['role_mappings']:
            embed = discord.Embed(
                title=f"{self.emojis['error']} Role Mapping Not Found", 
                description=f"No role mapping found for '{custom_name}'", 
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            return

        self.delete_role_mapping(ctx.guild.id, custom_name)
        
        embed = discord.Embed(
            title=f"{self.emojis['success']} Role Mapping Reset", 
            description=f"Role mapping for '{custom_name}' has been cleared.", 
            color=SUCCESS_COLOR
        )
        await ctx.send(embed=embed)
        
        await self.log_activity(ctx.guild, "Role Mapping Reset", f"Role mapping for '{custom_name}' cleared")

    async def rolehelp(self, ctx):
        """Show role management commands."""
        config = self.get_server_config(ctx.guild.id)
        
        embed = discord.Embed(title=f"{self.emojis['info']} Role Management", color=INFO_COLOR)
        embed.add_field(name=".setlogchannel [@channel]", value="Set log channel for bot activities", inline=False)
        embed.add_field(name=".reqrole [@role]", value="Set required role for role management", inline=False)
        embed.add_field(name=".setrole [name] [@role]", value="Map a custom role name", inline=False)
        embed.add_field(name=".reset_roles", value="Reset all role mappings", inline=False)
        embed.add_field(name=".reset_specific_role [name]", value="Reset a specific role mapping", inline=False)
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(RoleManagement(bot))
