import discord
import logging
import os
import json
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
        self.emojis = {
            'success': '✅',
            'error': '❌',
            'info': 'ℹ️',
            'warning': '⚠️',
            'roles': '🛡️',
            'log': '📋'
        }

    def get_config_path(self, guild_id):
        return os.path.join(self.config_dir, f'{guild_id}.json')

    def load_configs(self, guild_id):
        """Load server configurations from JSON."""
        config_path = self.get_config_path(guild_id)
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def save_configs(self, guild_id, config):
        """Save server configurations to JSON."""
        config_path = self.get_config_path(guild_id)
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=4)

    def get_server_config(self, guild_id):
        """Get or create server configuration."""
        config = self.load_configs(guild_id)
        if not config:
            config = {
                'role_mappings': {},
                'reqrole_id': None,
                'log_channel_id': None,
                'role_assignment_limit': 5,
                'admin_only_commands': True
            }
            self.save_configs(guild_id, config)
        return config

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

    async def handle_non_admin_attempt(self, ctx):
        """Handle scenarios where a non-admin user tries to use an admin command."""
        embed = discord.Embed(
            title=f"{self.emojis['error']} Access Denied",
            description="You do not have the required administrative permissions to execute this command.",
            color=ERROR_COLOR
        )
        await ctx.send(embed=embed)

    async def warn_non_admin(self, ctx):
        """Warn non-admin users about attempting to use admin commands."""
        embed = discord.Embed(
            title=f"{self.emojis['warning']} Restricted Command",
            description="This command is restricted to administrators only. Please contact a server admin for assistance.",
            color=WARNING_COLOR
        )
        await ctx.send(embed=embed)

    async def cog_before_invoke(self, ctx):
        """Hook called before any command invocation."""
        if ctx.command and ctx.command.name in self.bot.all_commands and not ctx.author.guild_permissions.administrator:
            await self.warn_non_admin(ctx)
            raise commands.CheckFailure("User does not have admin permissions.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        """Set the log channel for server activities."""
        config = self.get_server_config(ctx.guild.id)
        config['log_channel_id'] = channel.id
        self.save_configs(ctx.guild.id, config)
        
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
        self.save_configs(ctx.guild.id, config)
        
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
        
        if custom_name not in config['role_mappings']:
            config['role_mappings'][custom_name] = []
        
        if role.id not in config['role_mappings'][custom_name]:
            config['role_mappings'][custom_name].append(role.id)
        
        self.save_configs(ctx.guild.id, config)
        
        embed = discord.Embed(
            title=f"{self.emojis['success']} Role Mapping Added", 
            description=f"Mapped '{custom_name}' to {role.mention}", 
            color=SUCCESS_COLOR
        )
        await ctx.send(embed=embed)
        
        # Regenerate dynamic commands
        self.create_dynamic_role_commands()
        
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
                config = self.cog.get_server_config(self.ctx.guild.id)
                config['role_mappings'] = {}
                self.cog.save_configs(self.ctx.guild.id, config)
                
                # Remove all dynamic commands
                self.cog.create_dynamic_role_commands()
                
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

        del config['role_mappings'][custom_name]
        self.save_configs(ctx.guild.id, config)
        
        # Remove dynamic commands
        self.create_dynamic_role_commands()

        embed = discord.Embed(
            title=f"{self.emojis['success']} Role Mapping Reset", 
            description=f"Role mapping for '{custom_name}' has been cleared.", 
            color=SUCCESS_COLOR
        )
        await ctx.send(embed=embed)
        
        await self.log_activity(ctx.guild, "Role Mapping Reset", f"Role mapping for '{custom_name}' cleared")

    def create_dynamic_role_commands(self):
        """Dynamically create role commands for each server."""
        # Remove existing dynamic commands
        for guild_id in os.listdir(self.config_dir):
            config = self.load_configs(guild_id.split('.')[0])
            for custom_name in config.get('role_mappings', {}).keys():
                if custom_name in self.bot.all_commands:
                    del self.bot.all_commands[custom_name]

        # Create new dynamic commands
        for guild_id in os.listdir(self.config_dir):
            config = self.load_configs(guild_id.split('.')[0])
            for custom_name in config.get('role_mappings', {}).keys():
                async def dynamic_role_command(ctx, member: discord.Member = None, custom_name=custom_name):
                    # Check required role or admin permissions
                    if not await self.check_required_role(ctx):
                        return
                    
                    server_config = self.get_server_config(ctx.guild.id)
                    member = member or ctx.author
                    role_ids = server_config['role_mappings'].get(custom_name, [])
                    
                    if not role_ids:
                        embed = discord.Embed(
                            title=f"{self.emojis['error']} Role Error", 
                            description=f"No roles mapped to '{custom_name}'", 
                            color=ERROR_COLOR
                        )
                        await ctx.send(embed=embed)
                        return

                    roles = [ctx.guild.get_role(role_id) for role_id in role_ids if ctx.guild.get_role(role_id)]
                    
                    if not roles:
                        embed = discord.Embed(
                            title=f"{self.emojis['error']} Role Error", 
                            description="No valid roles found for this mapping", 
                            color=ERROR_COLOR
                        )
                        await ctx.send(embed=embed)
                        return

                    # Modify roles
                    roles_added = []
                    roles_removed = []
                    for role in roles:
                        if role in member.roles:
                            await member.remove_roles(role)
                            roles_removed.append(role)
                        else:
                            await member.add_roles(role)
                            roles_added.append(role)

                    # Send feedback
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
                            color=ERROR_COLOR
                        )
                        await ctx.send(embed=embed)

                    # Log
                    added_names = ', '.join(r.name for r in roles_added)
                    removed_names = ', '.join(r.name for r in roles_removed)
                    log_details = f"Added: {added_names
                    log_details = f"Added: {added_names}" if added_names else ""
                    if removed_names:
                        log_details += f" | Removed: {removed_names}"

                    await self.log_activity(
                        ctx.guild,
                        "Dynamic Role Command",
                        f"Roles modified for {member.display_name}: {log_details}"
                    )

                # Add the dynamic command to the bot
                dynamic_role_command.__name__ = custom_name
                dynamic_command = commands.Command(
                    name=custom_name,
                    callback=dynamic_role_command,
                    help=f"Assign or remove roles mapped to '{custom_name}'."
                )
                self.bot.add_command(dynamic_command)
