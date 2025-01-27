import discord
import logging
import os
import json
import pymongo
from discord.ext import commands
from dotenv import load_dotenv
import os

load_dotenv()  # To load environment variables from .env file

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enhanced color palette
EMBED_COLOR = 0x2f2136
SUCCESS_COLOR = 0x2ecc71
ERROR_COLOR = 0xe74c3c
INFO_COLOR = 0x3498db
WARNING_COLOR = 0xf39c12

# MongoDB setup
MONGO_URL = os.getenv("MONGO_URL")  # Add your MongoDB URL in the .env file
client = pymongo.MongoClient(MONGO_URL)
db = client['role_management_bot']

class RoleManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.emojis = {
            'success': '<:sukoon_tick:1322894604898664478>',
            'error': '<:sukoon_cross:1322894630684983307>',
            'info': '<:sukoon_info:1323251063910043659>',
            'warning': '<a:sukoon_reddot:1322894157794119732>',
            'roles': '<a:sukoon_butterfly:1323990263609298967>',
            'log': '<a:Sukoon_loading:1324070160931356703>'
        }

    def get_server_config(self, guild_id):
        """Get or create server configuration in MongoDB."""
        config = db.server_configs.find_one({"guild_id": guild_id})
        if not config:
            # Default configuration
            config = {
                'guild_id': guild_id,
                'role_mappings': {},
                'reqrole_id': None,
                'log_channel_id': None,
                'role_assignment_limit': 5,
                'admin_only_commands': True
            }
            db.server_configs.insert_one(config)
        return config

    def save_configs(self, guild_id, config):
        """Save server configurations to MongoDB."""
        db.server_configs.update_one(
            {"guild_id": guild_id}, 
            {"$set": config}, 
            upsert=True
        )

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

    async def check_role_permission(self, ctx):
        """
        Check if the user has permission to assign roles.
        Returns a tuple (is_allowed, error_message)
        """
        config = self.get_server_config(ctx.guild.id)
        req_role_id = config.get('reqrole_id')

        # Admin check
        if ctx.author.guild_permissions.administrator:
            return True, None

        # Required role check
        if req_role_id:
            req_role = ctx.guild.get_role(req_role_id)
            if req_role in ctx.author.roles:
                return True, None
            return False, (
                f"{self.emojis['error']} Permission Denied", 
                f"You must have the {req_role.mention} role to manage roles."
            )

        # No specific requirements set
        return False, (
            f"{self.emojis['error']} Role Management Disabled", 
            "Role management has not been configured for this server."
        )

    async def admin_only_command(self, ctx):
        """Handle unauthorized admin command attempts."""
        embed = discord.Embed(
            title=f"{self.emojis['error']} Permission Denied", 
            description="You must be a server administrator to use this command.", 
            color=ERROR_COLOR
        )
        await ctx.send(embed=embed)
        
        # Log unauthorized access attempt
        await self.log_activity(
            ctx.guild, 
            "Unauthorized Command", 
            f"{ctx.author.name} attempted to use an admin-only command"
        )

    @commands.command()
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        """Set the log channel for server activities."""
        if not ctx.author.guild_permissions.administrator:
            return await self.admin_only_command(ctx)
        
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
        if not ctx.author.guild_permissions.administrator:
            return await self.admin_only_command(ctx)
        
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
        if not ctx.author.guild_permissions.administrator:
            return await self.admin_only_command(ctx)
        
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
        if not ctx.author.guild_permissions.administrator:
            return await self.admin_only_command(ctx)
        
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
        for guild_id in db.server_configs.find():
            config = self.get_server_config(guild_id['guild_id'])
            for custom_name in config.get('role_mappings', {}).keys():
                if custom_name in self.bot.all_commands:
                    del self.bot.all_commands[custom_name]

        # Create new dynamic commands
        for guild_id in db.server_configs.find():
            config = self.get_server_config(guild_id['guild_id'])
            for custom_name in config.get('role_mappings', {}).keys():
                async def dynamic_role_command(ctx, member: discord.Member, custom_name=custom_name):
                    # Check if the user is trying to assign role to themselves
                    if ctx.author == member:
                        embed = discord.Embed(
                            title=f"{self.emojis['error']} Role Assignment Error", 
                            description="You cannot assign roles to yourself.", 
                            color=ERROR_COLOR
                        )
                        await ctx.send(embed=embed)
                        return

                    # Permission check
                    is_allowed, error_info = await self.check_role_permission(ctx)
                    if not is_allowed:
                        title, description = error_info
                        embed = discord.Embed(
                            title=title, 
                            description=description, 
                            color=ERROR_COLOR
                        )
                        await ctx.send(embed=embed)
                        return
                    
                    # Role assignment logic here
                    config = self.get_server_config(ctx.guild.id)
                    roles_to_add = config['role_mappings'].get(custom_name)
                    
                    if roles_to_add:
                        # Apply roles to the member
                        for role_id in roles_to_add:
                            role = ctx.guild.get_role(role_id)
                            if role:
                                await member.add_roles(role)
                                
                        embed = discord.Embed(
                            title=f"{self.emojis['success']} Roles Assigned", 
                            description=f"Assigned roles '{custom_name}' to {member.mention}", 
                            color=SUCCESS_COLOR
                        )
                        await ctx.send(embed=embed)
                    else:
                        embed = discord.Embed(
                            title=f"{self.emojis['error']} No Roles Mapped", 
                            description=f"No roles found for '{custom_name}'.", 
                            color=ERROR_COLOR
                        )
                        await ctx.send(embed=embed)

                # Add the dynamic role command
                dynamic_role_command.__name__ = custom_name
                self.bot.add_command(commands.Command(dynamic_role_command))

def setup(bot):
    bot.add_cog(RoleManagement(bot))
