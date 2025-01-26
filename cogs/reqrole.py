import discord
import logging
import os
import json
from discord.ext import commands

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Color palette
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

    async def check_admin_permission(self, ctx):
        """Check if user has administrator permissions."""
        if not ctx.author.guild_permissions.administrator:
            embed = discord.Embed(
                title=f"{self.emojis['error']} Admin Permission Required", 
                description="You must be a server administrator to use this command.", 
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            await self.log_activity(
                ctx.guild, 
                "Unauthorized Admin Command", 
                f"{ctx.author.name} attempted to use an admin-only command"
            )
            return False
        return True

    async def check_reqrole_permission(self, ctx):
        """Check if user has the required role for role management."""
        config = self.get_server_config(ctx.guild.id)
        reqrole_id = config.get('reqrole_id')
        
        if not reqrole_id:
            return True  # No required role set, allow access
        
        reqrole = ctx.guild.get_role(reqrole_id)
        if not reqrole:
            # Required role no longer exists
            embed = discord.Embed(
                title=f"{self.emojis['error']} Role Configuration Error", 
                description="The required role has been deleted. Please reconfigure.", 
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            return False
        
        if reqrole not in ctx.author.roles and not ctx.author.guild_permissions.administrator:
            embed = discord.Embed(
                title=f"{self.emojis['error']} Role Permission Required", 
                description=f"You must have the {reqrole.name} role to manage roles.", 
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            await self.log_activity(
                ctx.guild, 
                "Unauthorized Role Command", 
                f"{ctx.author.name} attempted to use a role management command without the required role"
            )
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
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        """Set the log channel for server activities."""
        if not await self.check_admin_permission(ctx):
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
        if not await self.check_admin_permission(ctx):
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
        if not await self.check_admin_permission(ctx):
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
    async def reset_role(self, ctx):
        """Reset role mappings with interactive options."""
        if not await self.check_admin_permission(ctx):
            return
        
        config = self.get_server_config(ctx.guild.id)
        role_mappings = config.get('role_mappings', {})

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

            @discord.ui.select(placeholder="Select Role Mapping to Reset")
            async def select_menu(self, interaction: discord.Interaction, select: discord.ui.Select):
                selected = select.values[0]
                
                if selected == "_reset_all":
                    # Reset all mappings
                    config = self.cog.get_server_config(self.ctx.guild.id)
                    config['role_mappings'] = {}
                    self.cog.save_configs(self.ctx.guild.id, config)
                    
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
                    config = self.cog.get_server_config(self.ctx.guild.id)
                    del config['role_mappings'][selected]
                    self.cog.save_configs(self.ctx.guild.id, config)
                    
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
                    # Check reqrole permission for role commands
                    if not await self.check_reqrole_permission(ctx):
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
        """Show role management commands."""
        config = self.get_server_config(ctx.guild.id)
        
        embed = discord.Embed(title=f"{self.emojis['info']} Role Management", color=INFO_COLOR)
        embed.add_field(name="Admin Commands:", value=(
            "`.setlogchannel [@channel]` - Set log channel\n"
            "`.reqrole [@role]` - Set required role for role management\n"
            "`.setrole [name] [@role]` - Map a custom role name\n"
            "`.reset_role` - Reset role mappings"
        ), inline=False)
        
        if config['role_mappings']:
            roles_list = "\n".join(f"- `.{name} [@user]`" for name in config['role_mappings'].keys())
            embed.add_field(name="Role Assignment Commands:", value=roles_list, inline=False)
        
        embed.add_field(name="Permissions:", value=(
            "• Admin commands require server administrator\n"
            "• Role commands require the specified req role\n"
            "• All actions are logged in the configured log channel"
        ), inline=False)
        
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_ready(self):
        """Create dynamic role commands when bot is ready."""
        self.create_dynamic_role_commands()
        logger.info(f'Dynamic role commands created for servers.')

class RoleBot(commands.Bot):
    async def setup_hook(self):
        """Setup hook to load the RoleManagement cog."""
        await self.add_cog(RoleManagement(self))
        print("Role Management Bot is ready!")

def main():
    # Set up intents
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    
    # Create bot instance
    bot = RoleBot(
        command_prefix='.',  # Configurable prefix
        intents=intents,
        help_command=None  # Disable default help
    )

    # Bot token - REPLACE WITH YOUR ACTUAL TOKEN
    TOKEN = 'YOUR_DISCORD_BOT_TOKEN'

    # Run the bot
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Bot startup error: {e}")

if __name__ == "__main__":
    main()
