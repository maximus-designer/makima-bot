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

    async def check_admin_permissions(self, ctx):
        """Check if the user is an administrator."""
        if not ctx.author.guild_permissions.administrator:
            embed = discord.Embed(
                title=f"{self.emojis['error']} Permission Denied", 
                description="You need to be an administrator to use this command.", 
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            return False
        return True

    @commands.command()
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        """Set the log channel for server activities."""
        if not await self.check_admin_permissions(ctx):
            return
        
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
    async def reqrole(self, ctx, role: discord.Role):
        """Set the required role for role management commands."""        
        if not await self.check_admin_permissions(ctx):
            return
        
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
    async def setrole(self, ctx, custom_name: str, role: discord.Role):
        """Map a custom role name to a role."""        
        if not await self.check_admin_permissions(ctx):
            return
        
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
    async def reset_roles(self, ctx):
        """Reset all role mappings for the server."""        
        if not await self.check_required_role(ctx):
            return

        config = self.get_server_config(ctx.guild.id)
        role_mappings = config['role_mappings']

        class ConfirmView(discord.ui.View):
            def __init__(self, ctx, cog):
                super().__init__()
                self.ctx = ctx
                self.cog = cog

            @discord.ui.button(label="Confirm Reset All", style=discord.ButtonStyle.red)
            async def confirm_all(self, interaction: discord.Interaction, button: discord.ui.Button):
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

        # Dropdown for resetting a specific role mapping
        if role_mappings:
            options = [discord.SelectOption(label=name) for name in role_mappings.keys()]
            select = discord.ui.Select(placeholder="Select a role mapping to reset", options=options)

            async def select_callback(interaction: discord.Interaction):
                selected_role = select.values[0]
                await self.reset_specific_role(interaction, selected_role)

            select.callback = select_callback
            view.add_item(select)
            await ctx.send(embed=embed, view=view)

    async def reset_specific_role(self, ctx, custom_name: str):
        """Reset a specific role mapping."""
        if not await self.check_admin_permissions(ctx):
            return
        
        config = self.get_server_config(ctx.guild.id)
        if custom_name not in config['role_mappings']:
            embed = discord.Embed(
                title=f"{self.emojis['error']} Mapping Not Found", 
                description=f"No mapping found for '{custom_name}'.", 
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            return

        class ConfirmView(discord.ui.View):
            def __init__(self, ctx, cog, custom_name):
                super().__init__()
                self.ctx = ctx
                self.cog = cog
                self.custom_name = custom_name

            @discord.ui.button(label="Confirm Reset", style=discord.ButtonStyle.red)
            async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
                config = self.cog.get_server_config(self.ctx.guild.id)
                del config['role_mappings'][self.custom_name]
                self.cog.save_configs(self.ctx.guild.id, config)
                
                # Remove the dynamic command
                self.cog.create_dynamic_role_commands()
                
                embed = discord.Embed(
                    title=f"{self.cog.emojis['warning']} Role Mapping Reset", 
                    description=f"Mapping for '{self.custom_name}' has been cleared.", 
                    color=SUCCESS_COLOR
                )
                await interaction.response.send_message(embed=embed)
                
                await self.cog.log_activity(self.ctx.guild, "Role Mapping Reset", f"Mapping for '{self.custom_name}' cleared")
                
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
            title=f"{self.emojis['warning']} Reset Role Mapping", 
            description=f"Are you sure you want to reset the mapping for '{custom_name}'?", 
            color=ERROR_COLOR
        )
        view = ConfirmView(ctx, self, custom_name)
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
                    roles = [ctx.guild.get_role(role_id) for role_id in role_ids]
                    if roles:
                        for role in roles:
                            if role:
                                await member.add_roles(role)
                                embed = discord.Embed(
                                    title=f"{self.emojis['success']} Role Assigned", 
                                    description=f"Assigned {role.mention} to {member.mention}.", 
                                    color=SUCCESS_COLOR
                                )
                                await ctx.send(embed=embed)
                    else:
                        embed = discord.Embed(
                            title=f"{self.emojis['error']} Invalid Mapping", 
                            description=f"No roles associated with '{custom_name}'", 
                            color=ERROR_COLOR
                        )
                        await ctx.send(embed=embed)

                dynamic_role_command.__name__ = custom_name
                self.bot.command()(dynamic_role_command)

def setup(bot):
    bot.add_cog(RoleManagement(bot))
