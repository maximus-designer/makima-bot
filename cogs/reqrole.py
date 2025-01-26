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

    async def handle_admin_only_error(self, ctx):
        """Send enhanced warning for non-admins trying to use admin commands."""
        embed = discord.Embed(
            title=f"{self.emojis['error']} Access Denied",
            description=(
                "This command is restricted to server administrators. "
                "If you believe this is a mistake, please contact the server admin."
            ),
            color=ERROR_COLOR
        )
        await ctx.send(embed=embed)

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

    @setlogchannel.error
    async def setlogchannel_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await self.handle_admin_only_error(ctx)

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

    @reqrole.error
    async def reqrole_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await self.handle_admin_only_error(ctx)

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

    @setrole.error
    async def setrole_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await self.handle_admin_only_error(ctx)

    # Other commands remain unchanged with similar error handlers for admin-only commands

    def create_dynamic_role_commands(self):
        """Dynamically create role commands for each server."""
        # Implementation remains unchanged

    @commands.Cog.listener()
    async def on_ready(self):
        """Create dynamic role commands when bot is ready."""
        self.create_dynamic_role_commands()
        logger.info(f'Dynamic role commands created for servers.')

async def setup(bot):
    await bot.add_cog(RoleManagement(bot))
