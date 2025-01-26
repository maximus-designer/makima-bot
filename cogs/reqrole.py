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
            'log': '📋',
            'admin': '👑'
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
                'admin_only_roles': []  # New field to track admin-only roles
            }
            self.save_configs(guild_id, config)
        return config

    async def check_role_modification_permission(self, ctx, role):
        """Check if the role can be modified by non-admins."""
        config = self.get_server_config(ctx.guild.id)
        admin_only_roles = config.get('admin_only_roles', [])

        # Always allow administrators
        if ctx.author.guild_permissions.administrator:
            return True

        # Check if the role is in admin-only list
        if role.id in admin_only_roles:
            embed = discord.Embed(
                title=f"{self.emojis['admin']} Admin Protection", 
                description=f"🔒 This role can only be managed by server administrators. {self.emojis['warning']}", 
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            return False

        return True

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def protect_role(self, ctx, role: discord.Role):
        """Mark a role as admin-only."""
        config = self.get_server_config(ctx.guild.id)
        admin_only_roles = config.get('admin_only_roles', [])
        
        if role.id not in admin_only_roles:
            admin_only_roles.append(role.id)
            config['admin_only_roles'] = admin_only_roles
            self.save_configs(ctx.guild.id, config)
            
            embed = discord.Embed(
                title=f"{self.emojis['admin']} Role Protection", 
                description=f"{role.mention} is now protected and can only be managed by administrators.", 
                color=SUCCESS_COLOR
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title=f"{self.emojis['warning']} Already Protected", 
                description=f"{role.mention} is already an admin-only role.", 
                color=WARNING_COLOR
            )
            await ctx.send(embed=embed)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def unprotect_role(self, ctx, role: discord.Role):
        """Remove admin-only protection from a role."""
        config = self.get_server_config(ctx.guild.id)
        admin_only_roles = config.get('admin_only_roles', [])
        
        if role.id in admin_only_roles:
            admin_only_roles.remove(role.id)
            config['admin_only_roles'] = admin_only_roles
            self.save_configs(ctx.guild.id, config)
            
            embed = discord.Embed(
                title=f"{self.emojis['success']} Role Unprotected", 
                description=f"{role.mention} can now be managed by users with the required role.", 
                color=SUCCESS_COLOR
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title=f"{self.emojis['warning']} Not Protected", 
                description=f"{role.mention} is not an admin-only role.", 
                color=INFO_COLOR
            )
            await ctx.send(embed=embed)

    # (Rest of the previous code remains the same, with minor modifications to existing methods)
    
    def create_dynamic_role_commands(self):
        """Dynamically create role commands for each server."""
        # Remove existing dynamic commands
        for guild_id_file in os.listdir(self.config_dir):
            guild_id = guild_id_file.split('.')[0]
            config = self.load_configs(guild_id)
            for custom_name in config.get('role_mappings', {}).keys():
                if custom_name in self.bot.all_commands:
                    del self.bot.all_commands[custom_name]

        # Create new dynamic commands
        for guild_id_file in os.listdir(self.config_dir):
            guild_id = guild_id_file.split('.')[0]
            config = self.load_configs(guild_id)
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

                    # Check admin protection for each role
                    for role in roles:
                        if not await self.check_role_modification_permission(ctx, role):
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
        embed.add_field(name=".setlogchannel [@channel]", value="Set log channel for bot activities", inline=False)
        embed.add_field(name=".reqrole [@role]", value="Set required role for role management", inline=False)
        embed.add_field(name=".setrole [name] [@role]", value="Map a custom role name", inline=False)
        embed.add_field(name=".reset_roles", value="Reset all role mappings", inline=False)
        embed.add_field(name=".reset_specific_role [name]", value="Reset a specific role mapping", inline=False)
        embed.add_field(name=".protect_role [@role]", value="Mark a role as admin-only", inline=False)
        embed.add_field(name=".unprotect_role [@role]", value="Remove admin-only protection from a role", inline=False)
        
        if config['role_mappings']:
            roles_list = "\n".join(f"- .{name} [@user]" for name in config['role_mappings'].keys())
            embed.add_field(name="Available Role Commands", value=roles_list, inline=False)
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(RoleManagement(bot))
