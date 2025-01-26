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
            config = self.cursor.fetchone()
            if not config:
                # Create default config if not exists
                self.cursor.execute('''
                    INSERT INTO servers (guild_id, role_assignment_limit, admin_only_commands) 
                    VALUES (?, 5, 1)
                ''', (guild_id,))
                self.conn.commit()
                config = self.get_server_config(guild_id)
            return config
        except sqlite3.Error as e:
            self.logger.error(f"Error retrieving server config: {e}")
            return None
        finally:
            self.close()

    def set_log_channel(self, guild_id, channel_id):
        try:
            self.connect()
            self.cursor.execute('''
                INSERT OR REPLACE INTO servers (guild_id, log_channel_id) 
                VALUES (?, ?)
            ''', (guild_id, channel_id))
            self.conn.commit()
        except sqlite3.Error as e:
            self.logger.error(f"Error setting log channel: {e}")
        finally:
            self.close()

    def set_reqrole(self, guild_id, role_id):
        try:
            self.connect()
            self.cursor.execute('''
                UPDATE servers SET reqrole_id = ? WHERE guild_id = ?
            ''', (role_id, guild_id))
            self.conn.commit()
        except sqlite3.Error as e:
            self.logger.error(f"Error setting required role: {e}")
        finally:
            self.close()

    def get_role_mappings(self, guild_id):
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

    def add_role_mapping(self, guild_id, custom_name, role_id):
        try:
            self.connect()
            self.cursor.execute('''
                INSERT OR REPLACE INTO role_mappings 
                (guild_id, custom_name, role_id) VALUES (?, ?, ?)
            ''', (guild_id, custom_name, role_id))
            self.conn.commit()
        except sqlite3.Error as e:
            self.logger.error(f"Error adding role mapping: {e}")
        finally:
            self.close()

    def remove_role_mapping(self, guild_id, custom_name):
        try:
            self.connect()
            self.cursor.execute('''
                DELETE FROM role_mappings 
                WHERE guild_id = ? AND custom_name = ?
            ''', (guild_id, custom_name))
            self.conn.commit()
        except sqlite3.Error as e:
            self.logger.error(f"Error removing role mapping: {e}")
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

        self.db.set_reqrole(ctx.guild.id, role.id)
        embed = discord.Embed(
            title=f"{self.emojis['roles']} Required Role Set",
            description=f"Only members with {role.mention} can now manage roles.",
            color=SUCCESS_COLOR
        )
        await ctx.send(embed=embed)
        await self.log_activity(ctx.guild, "Required Role Updated", f"New required role: {role.name}")

    @commands.command()
    async def setrole(self, ctx, custom_name: str, role: discord.Role):
        """Map a custom role name to a role."""
        if not await self.check_authorization(ctx, admin_required=True):
            return

        self.db.add_role_mapping(ctx.guild.id, custom_name, role.id)
        embed = discord.Embed(
            title=f"{self.emojis['success']} Role Mapping Added",
            description=f"Mapped '{custom_name}' to {role.mention}",
            color=SUCCESS_COLOR
        )
        await ctx.send(embed=embed)
        await self.log_activity(ctx.guild, "Role Mapping", f"Mapped '{custom_name}' to {role.name}")
        self.create_dynamic_role_commands()

    @commands.command()
    async def reset_role(self, ctx):
        """Reset role mappings with interactive options."""
        if not await self.check_authorization(ctx, admin_required=True):
            return

        mappings = self.db.get_role_mappings(ctx.guild.id)
        
        if not mappings:
            embed = discord.Embed(
                title=f"{self.emojis['info']} No Mappings",
                description="There are no role mappings to reset.",
                color=INFO_COLOR
            )
            await ctx.send(embed=embed)
            return

        class ResetRoleView(discord.ui.View):
            def __init__(self, ctx, cog, mappings):
                super().__init__()
                self.ctx = ctx
                self.cog = cog
                self.mappings = mappings

                # Populate dropdown with role mapping options
                self.select_menu.options = [
                    discord.SelectOption(
                        label=name, 
                        description=f"Reset mapping for '{name}'"
                    ) for name, _ in mappings
                ]
                
                # Add "Reset All" option
                self.select_menu.options.append(
                    discord.SelectOption(
                        label="Reset All Mappings", 
                        description="Reset ALL role mappings", 
                        value="_reset_all"
                    )
                )

            @discord.ui.select(placeholder="Select Role Mapping to Reset")
            async def select_menu(self, interaction: discord.Interaction, select: discord.ui.Select):
                selected = select.values[0]
                
                if selected == "_reset_all":
                    # Reset all mappings
                    for name, _ in self.mappings:
                        self.cog.db.remove_role_mapping(self.ctx.guild.id, name)
                    
                    embed = discord.Embed(
                        title=f"{self.cog.emojis['warning']} All Role Mappings Reset", 
                        description="All role mappings have been cleared.", 
                        color=SUCCESS_COLOR
                    )
                    await interaction.response.send_message(embed=embed)
                    
                    await self.cog.log_activity(
                        self.ctx.guild, 
                        "Role Mapping Reset", 
                        "All role mappings cleared"
                    )
                else:
                    # Reset specific mapping
                    self.cog.db.remove_role_mapping(self.ctx.guild.id, selected)
                    
                    embed = discord.Embed(
                        title=f"{self.cog.emojis['warning']} Role Mapping Reset", 
                        description=f"Mapping for '{selected}' has been removed.", 
                        color=SUCCESS_COLOR
                    )
                    await interaction.response.send_message(embed=embed)
                    
                    await self.cog.log_activity(
                        self.ctx.guild, 
                        "Role Mapping Removed", 
                        f"Mapping for '{selected}' deleted"
                    )
                
                # Regenerate dynamic commands
                self.cog.create_dynamic_role_commands()
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
            description="Select a role mapping to reset or choose to reset all mappings.", 
            color=WARNING_COLOR
        )
        view = ResetRoleView(ctx, self, mappings)
        await ctx.send(embed=embed, view=view)

    def create_dynamic_role_commands(self):
        """Dynamically create role commands for each server."""
        # Remove existing dynamic commands
        for guild_id in set(entry[0] for entry in self.db.get_role_mappings(0)):
            mappings = self.db.get_role_mappings(guild_id)
            
            for custom_name, _ in mappings:
                if custom_name in self.bot.all_commands:
                    del self.bot.all_commands[custom_name]

        # Create new dynamic commands for each server's mappings
        for guild_id in set(entry[0] for entry in self.db.get_role_mappings(0)):
            mappings = self.db.get_role_mappings(guild_id)
            
            for custom_name, role_id in mappings:
                async def dynamic_role_command(ctx, member: discord.Member = None, custom_name=custom_name):
                    # Get server configuration
                    config = self.db.get_server_config(ctx.guild.id)
                    
                    # Check authorization if admin-only is enabled
                    if config[4] and not ctx.author.guild_permissions.administrator:
                        embed = discord.Embed(
                            title=f"{self.emojis['error']} Admin Only",
                            description="Role management is restricted to administrators.",
                            color=ERROR_COLOR
                        )
                        await ctx.send(embed=embed)
                        return

                    # Default to command invoker if no member specified
                    member = member or ctx.author
                    
                    # Retrieve role mappings for this custom name
                    mappings = self.db.get_role_mappings(ctx.guild.id)
                    role_ids = [rid for name, rid in mappings if name == custom_name]
                    
                    if not role_ids:
                        embed = discord.Embed(
                            title=f"{self.emojis['error']} Role Error", 
                            description=f"No roles found for '{custom_name}'", 
                            color=ERROR_COLOR
                        )
                        await ctx.send(embed=embed)
                        return

                    # Get actual role objects
                    roles = [ctx.guild.get_role(role_id) for role_id in role_ids if ctx.guild.get_role(role_id)]
                    
                    if not roles:
                        embed = discord.Embed(
                            title=f"{self.emojis['error']} Role Error", 
                            description="No valid roles found for this mapping", 
                            color=ERROR_COLOR
                        )
                        await ctx.send(embed=embed)
                        return

                    # Track role changes
                    roles_added = []
                    roles_removed = []

                    # Toggle roles
                    for role in roles:
                        if role in member.roles:
                            await member.remove_roles(role)
                            roles_removed.append(role)
                        else:
                            await member.add_roles(role)
                            roles_added.append(role)

                    # Provide feedback
                    if roles_added:
                        embed = discord.Embed(
                            title=f"{self.emojis['success']} Roles Added", 
                            description=f"Added: {', '.join(r.name for r in roles_added)}", 
                            color=SUCCESS_COLOR
                        )
                        await ctx.send(embed=embed)
                    
                    if roles_removed:
                        embed = discord.Embed(
                            title=f"{self.emojis['warning']} Roles Removed", 
                            description=f"Removed: {', '.join(r.name for r in roles_removed)}", 
                            color=WARNING_COLOR
                        )
                        await ctx.send(embed=embed)

                    # Log the activity
                    action_type = "Added" if roles_added else "Removed"
                    roles_list = roles_added or roles_removed
                    await self.log_activity(
                        ctx.guild, 
                        f"Role {action_type}", 
                        f"{member.name} {action_type.lower()} roles: {', '.join(r.name for r in roles_list)}"
                    )

                # Dynamically create the command
                command = commands.command(name=custom_name)(dynamic_role_command)
                self.bot.add_command(command)

    @commands.command()
    async def rolehelp(self, ctx):
        """Show available role management commands."""
        mappings = self.db.get_role_mappings(ctx.guild.id)
        
        embed = discord.Embed(
            title=f"{self.emojis['info']} Role Management Commands", 
            color=INFO_COLOR
        )
        
        # Admin commands
        embed.add_field(
            name="Admin Commands", 
            value=(
                "• `.setlogchannel [@channel]`: Set log channel\n"
                "• `.reqrole [@role]`: Set required role\n"
                "• `.setrole [name] [@role]`: Map custom role name\n"
                "• `.reset_role`: Reset role mappings"
            ), 
            inline=False
        )
        
        # Dynamic role commands
        if mappings:
            roles_list = "\n".join(f"• `.{name} [@user]`: Toggle role(s)" for name, _ in mappings)
            embed.add_field(
                name="Dynamic Role Commands", 
                value=roles_list, 
                inline=False
            )
        
        await ctx.send(embed=embed)
        async def setup(bot):
    await bot.add_cog(RoleManagement(bot))
