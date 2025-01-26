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

    @commands.command()
    async def reset_role(self, ctx):
        """Reset role mappings with interactive options."""
        # Strict admin-only check
        if not ctx.author.guild_permissions.administrator:
            await self.admin_only_command(ctx)
            return

        role_mappings = self.get_role_mappings(ctx.guild.id)

        class ResetRoleView(discord.ui.View):
            def __init__(self, ctx, cog, role_mappings):
                super().__init__()
                self.ctx = ctx
                self.cog = cog
                self.role_mappings = role_mappings

                # Populate dropdown with role mapping options
                self.select_menu.options = [
                    discord.SelectOption(
                        label=name, 
                        description=f"Reset mapping for '{name}'"
                    ) for name in role_mappings.keys()
                ]
                
                # Add "Reset All" option
                self.select_menu.options.append(
                    discord.SelectOption(
                        label="Reset All Mappings", 
                        description="Reset ALL role mappings", 
                        value="_reset_all"
                    )
                )

            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                """Ensure only the original admin can interact with the view."""
                return interaction.user.guild_permissions.administrator and interaction.user.id == self.ctx.author.id

            @discord.ui.select(placeholder="Select Role Mapping to Reset")
            async def select_menu(self, interaction: discord.Interaction, select: discord.ui.Select):
                selected = select.values[0]
                
                if selected == "_reset_all":
                    # Reset all mappings
                    self.cog.delete_role_mapping(self.ctx.guild.id)
                    
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
                    self.cog.delete_role_mapping(self.ctx.guild.id, selected)
                    
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

        # Check if there are any role mappings
        if not role_mappings:
            embed = discord.Embed(
                title=f"{self.emojis['info']} No Mappings", 
                description="There are no role mappings to reset.", 
                color=INFO_COLOR
            )
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(
            title=f"{self.emojis['warning']} Reset Role Mappings", 
            description="Select a role mapping to reset or choose to reset all mappings.", 
            color=WARNING_COLOR
        )
        view = ResetRoleView(ctx, self, role_mappings)
        await ctx.send(embed=embed, view=view)

    @commands.command()
    async def setrole(self, ctx, custom_name: str, role: discord.Role):
        """Map a custom role name to a role."""
        if not ctx.author.guild_permissions.administrator:
            return await self.admin_only_command(ctx)
        
        # Save to SQLite database
        self.save_role_mapping(ctx.guild.id, custom_name, role.id)
        
        embed = discord.Embed(
            title=f"{self.emojis['success']} Role Mapping Added", 
            description=f"Mapped '{custom_name}' to {role.mention}", 
            color=SUCCESS_COLOR
        )
        await ctx.send(embed=embed)
        
        # Regenerate dynamic commands
        self.create_dynamic_role_commands()
        
        await self.log_activity(ctx.guild, "Role Mapping", f"Mapped '{custom_name}' to {role.name}")

    def create_dynamic_role_commands(self):
        """Dynamically create role commands for each server."""
        # Remove existing dynamic commands
        config_files = [f for f in os.listdir(self.config_dir) if f.endswith('.json')]
        for guild_file in config_files:
            guild_id = int(guild_file.split('.')[0])
            role_mappings = self.get_role_mappings(guild_id)
            
            for custom_name in role_mappings.keys():
                if custom_name in self.bot.all_commands:
                    del self.bot.all_commands[custom_name]

        # Create new dynamic commands
        config_files = [f for f in os.listdir(self.config_dir) if f.endswith('.json')]
        for guild_file in config_files:
            guild_id = int(guild_file.split('.')[0])
            role_mappings = self.get_role_mappings(guild_id)
            
            for custom_name in role_mappings.keys():
                async def dynamic_role_command(ctx, member: discord.Member, custom_name=custom_name):
                    # Rest of the implementation remains the same as in the previous version
                    # ... [previous implementation copied here]
                
                # Dynamically create the command
                command = commands.command(name=custom_name)(dynamic_role_command)
                self.bot.add_command(command)

    # Rest of the class implementation remains the same...

async def setup(bot):
    await bot.add_cog(RoleManagement(bot))
