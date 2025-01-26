import discord
import logging
import os
import json
from discord.ext import commands

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EMBED_COLOR = 0x2f2136
SUCCESS_COLOR = 0x2ecc71
ERROR_COLOR = 0xe74c3c
INFO_COLOR = 0x3498db

class RoleManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = 'server_roles.json'
        self.server_configs = self.load_configs()

    def load_configs(self):
        """Load server configurations from JSON."""
        try:
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def save_configs(self):
        """Save server configurations to JSON."""
        with open(self.config_file, 'w') as f:
            json.dump(self.server_configs, f, indent=4)

    def get_server_config(self, guild_id):
        """Get or create server configuration."""
        guild_id = str(guild_id)
        if guild_id not in self.server_configs:
            self.server_configs[guild_id] = {
                'role_mappings': {},
                'reqrole_id': None,
                'log_channel_id': None,
                'role_assignment_limit': 5
            }
            self.save_configs()
        return self.server_configs[guild_id]

    async def check_required_role(self, ctx):
        """Check if user has the required role for commands."""
        config = self.get_server_config(ctx.guild.id)
        reqrole_id = config.get('reqrole_id')
        
        if not reqrole_id:
            return True
        
        reqrole = ctx.guild.get_role(reqrole_id)
        if not reqrole:
            embed = discord.Embed(
                title="Configuration Error", 
                description="Required role is no longer valid.", 
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            return False
        
        if reqrole not in ctx.author.roles:
            embed = discord.Embed(
                title="Permission Denied", 
                description=f"You need the {reqrole.mention} role to use this command.", 
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            return False
        
        return True

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def reqrole(self, ctx, role: discord.Role):
        """Set the required role for role management commands."""
        config = self.get_server_config(ctx.guild.id)
        config['reqrole_id'] = role.id
        self.save_configs()
        
        embed = discord.Embed(
            title="Required Role Set", 
            description=f"Only members with {role.mention} can now manage roles.", 
            color=SUCCESS_COLOR
        )
        await ctx.send(embed=embed)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setrole(self, ctx, custom_name: str, role: discord.Role):
        """Map a custom role name to a role."""
        if not await self.check_required_role(ctx):
            return
        
        config = self.get_server_config(ctx.guild.id)
        
        if custom_name not in config['role_mappings']:
            config['role_mappings'][custom_name] = []
        
        if role.id not in config['role_mappings'][custom_name]:
            config['role_mappings'][custom_name].append(role.id)
        
        self.save_configs()
        
        embed = discord.Embed(
            title="Role Mapping Added", 
            description=f"Mapped '{custom_name}' to {role.mention}", 
            color=SUCCESS_COLOR
        )
        await ctx.send(embed=embed)
        
        # Regenerate dynamic commands
        self.create_dynamic_role_commands()

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
                self.cog.save_configs()
                
                # Remove all dynamic commands
                for cmd_name in list(self.cog.bot.all_commands.keys()):
                    if cmd_name in config['role_mappings']:
                        del self.cog.bot.all_commands[cmd_name]
                
                embed = discord.Embed(
                    title="Role Mappings Reset", 
                    description="All role mappings have been cleared.", 
                    color=SUCCESS_COLOR
                )
                await interaction.response.send_message(embed=embed)
                self.stop()

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
            async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                embed = discord.Embed(
                    title="Reset Cancelled", 
                    description="Role mapping reset was cancelled.", 
                    color=ERROR_COLOR
                )
                await interaction.response.send_message(embed=embed)
                self.stop()

        embed = discord.Embed(
            title="Reset Role Mappings", 
            description="Are you sure you want to reset all role mappings for this server?", 
            color=ERROR_COLOR
        )
        view = ConfirmView(ctx, self)
        await ctx.send(embed=embed, view=view)

    def create_dynamic_role_commands(self):
        """Dynamically create role commands for each server."""
        # Remove existing dynamic commands
        for guild_id, config in self.server_configs.items():
            for custom_name in config.get('role_mappings', {}).keys():
                if custom_name in self.bot.all_commands:
                    del self.bot.all_commands[custom_name]

        # Create new dynamic commands
        for guild_id, config in self.server_configs.items():
            for custom_name in config.get('role_mappings', {}).keys():
                async def dynamic_role_command(ctx, member: discord.Member = None, custom_name=custom_name):
                    # Check required role
                    if not await self.check_required_role(ctx):
                        return
                    
                    server_config = self.get_server_config(ctx.guild.id)
                    member = member or ctx.author
                    role_ids = server_config['role_mappings'].get(custom_name, [])
                    
                    if not role_ids:
                        embed = discord.Embed(
                            title="Role Error", 
                            description=f"No roles mapped to '{custom_name}'", 
                            color=ERROR_COLOR
                        )
                        await ctx.send(embed=embed)
                        return

                    roles = [ctx.guild.get_role(role_id) for role_id in role_ids if ctx.guild.get_role(role_id)]
                    
                    if not roles:
                        embed = discord.Embed(
                            title="Role Error", 
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
                            title="Roles Added", 
                            description=f"Added: {', '.join(r.name for r in roles_added)}", 
                            color=SUCCESS_COLOR
                        )
                        await ctx.send(embed=embed)
                    
                    if roles_removed:
                        embed = discord.Embed(
                            title="Roles Removed", 
                            description=f"Removed: {', '.join(r.name for r in roles_removed)}", 
                            color=ERROR_COLOR
                        )
                        await ctx.send(embed=embed)

                # Dynamically create the command
                command = commands.command(name=custom_name)(dynamic_role_command)
                self.bot.add_command(command)

    @commands.Cog.listener()
    async def on_ready(self):
        """Create dynamic role commands when bot is ready."""
        self.create_dynamic_role_commands()
        logger.info(f'Dynamic role commands created for {len(self.server_configs)} servers')

    @commands.command()
    async def rolehelp(self, ctx):
        """Show role management commands."""
        config = self.get_server_config(ctx.guild.id)
        
        embed = discord.Embed(title="Role Management", color=INFO_COLOR)
        embed.add_field(name=".reqrole [@role]", value="Set required role for role management", inline=False)
        embed.add_field(name=".setrole [name] [@role]", value="Map a custom role name", inline=False)
        embed.add_field(name=".reset_roles", value="Reset all role mappings", inline=False)
        
        if config['role_mappings']:
            roles_list = "\n".join(f"- .{name} [@user]" for name in config['role_mappings'].keys())
            embed.add_field(name="Available Role Commands", value=roles_list, inline=False)
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(RoleManagement(bot))
