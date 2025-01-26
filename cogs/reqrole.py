import discord
import logging
import os
import json
from discord.ext import commands
from discord.ui import Select, View

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
    async def reset_role(self, ctx):
        """Reset specific role mappings or all role mappings."""
        if not await self.check_required_role(ctx):
            return
        
        config = self.get_server_config(ctx.guild.id)
        role_mappings = config.get('role_mappings', {})
        
        if not role_mappings:
            embed = discord.Embed(
                title=f"{self.emojis['error']} No Role Mappings",
                description="There are no role mappings to reset.",
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            return

        class RoleMappingSelect(Select):
            def __init__(self):
                options = [
                    discord.SelectOption(label=name, value=name)
                    for name in role_mappings.keys()
                ]
                super().__init__(placeholder="Select a role mapping to reset...", min_values=1, max_values=1, options=options)

            async def callback(self, interaction: discord.Interaction):
                custom_name = self.values[0]
                embed = discord.Embed(
                    title=f"{self.emojis['warning']} Reset Role Mapping",
                    description=f"Are you sure you want to reset the '{custom_name}' role mapping?",
                    color=ERROR_COLOR
                )
                await interaction.response.send_message(embed=embed, view=ConfirmResetView(ctx, custom_name))

        class ConfirmResetView(View):
            def __init__(self, ctx, custom_name):
                super().__init__()
                self.ctx = ctx
                self.custom_name = custom_name

            @discord.ui.button(label="Confirm", style=discord.ButtonStyle.red)
            async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
                config = self.ctx.bot.get_server_config(self.ctx.guild.id)
                del config['role_mappings'][self.custom_name]
                self.ctx.bot.save_configs(self.ctx.guild.id, config)

                embed = discord.Embed(
                    title=f"{self.ctx.bot.emojis['success']} Role Mapping Reset",
                    description=f"Role mapping '{self.custom_name}' has been reset.",
                    color=SUCCESS_COLOR
                )
                await interaction.response.send_message(embed=embed)
                await self.ctx.bot.log_activity(self.ctx.guild, "Role Mapping Reset", f"'{self.custom_name}' role mapping cleared.")
                self.stop()

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
            async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                embed = discord.Embed(
                    title=f"{self.ctx.bot.emojis['info']} Reset Cancelled",
                    description="The reset action has been cancelled.",
                    color=INFO_COLOR
                )
                await interaction.response.send_message(embed=embed)
                self.stop()

        # Provide options to select a role mapping to reset
        select_menu = RoleMappingSelect()
        view = View()
        view.add_item(select_menu)
        
        embed = discord.Embed(
            title=f"{self.emojis['warning']} Select Role Mapping to Reset",
            description="Select the role mapping you want to reset or cancel.",
            color=INFO_COLOR
        )
        await ctx.send(embed=embed, view=view)

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

                    # Log the activity
                    action_type = "Added" if roles_added else "Removed"
                    roles_list = roles_added or roles_removed
                    await self.log_activity(ctx.guild, f"Role {action_type}", f"'{', '.join(r.name for r in roles_list)}' for '{custom_name}'")

                dynamic_command = commands.Command(dynamic_role_command)
                self.bot.add_command(dynamic_command)

    @commands.command()
    async def list_roles(self, ctx):
        """List all available custom role mappings."""
        config = self.get_server_config(ctx.guild.id)
        role_mappings = config.get('role_mappings', {})
        
        if not role_mappings:
            embed = discord.Embed(
                title=f"{self.emojis['error']} No Role Mappings",
                description="There are no custom role mappings.",
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            return
        
        description = "\n".join([f"• {name}" for name in role_mappings.keys()])
        embed = discord.Embed(
            title=f"{self.emojis['roles']} Custom Role Mappings",
            description=description,
            color=INFO_COLOR
        )
        await ctx.send(embed=embed)

def setup(bot):
    bot.add_cog(RoleManagement(bot))
