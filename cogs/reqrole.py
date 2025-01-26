import discord
import logging
import os
from discord.ext import commands
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EMBED_COLOR = 0x2f2136

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
        guild_id = str(guild_id)  # Ensure string key
        if guild_id not in self.server_configs:
            self.server_configs[guild_id] = {
                'role_mappings': {},
                'reqrole_id': None,
                'log_channel_id': None,
                'role_assignment_limit': 5
            }
            self.save_configs()
        return self.server_configs[guild_id]

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setrole(self, ctx, custom_name: str, role: discord.Role):
        """Map a custom role name to a role."""
        config = self.get_server_config(ctx.guild.id)
        
        if custom_name not in config['role_mappings']:
            config['role_mappings'][custom_name] = []
        
        if role.id not in config['role_mappings'][custom_name]:
            config['role_mappings'][custom_name].append(role.id)
        
        self.save_configs()
        await ctx.send(f"Mapped '{custom_name}' to {role.name}")

    @commands.command()
    async def assignrole(self, ctx, custom_name: str, member: discord.Member = None):
        """Assign or remove a role."""
        member = member or ctx.author
        config = self.get_server_config(ctx.guild.id)
        
        # Role mapping validation
        if custom_name not in config['role_mappings']:
            await ctx.send(f"No role mapped to '{custom_name}'")
            return

        # Get roles to modify
        role_ids = config['role_mappings'][custom_name]
        roles_to_modify = [ctx.guild.get_role(role_id) for role_id in role_ids if ctx.guild.get_role(role_id)]

        if not roles_to_modify:
            await ctx.send("No valid roles found for this mapping")
            return

        # Modify roles
        roles_added = []
        roles_removed = []
        for role in roles_to_modify:
            if role in member.roles:
                await member.remove_roles(role)
                roles_removed.append(role)
            else:
                await member.add_roles(role)
                roles_added.append(role)

        # Feedback
        if roles_added:
            await ctx.send(f"Added: {', '.join(r.name for r in roles_added)}")
        if roles_removed:
            await ctx.send(f"Removed: {', '.join(r.name for r in roles_removed)}")

    @commands.command()
    async def rolehelp(self, ctx):
        """Show role management commands."""
        config = self.get_server_config(ctx.guild.id)
        
        embed = discord.Embed(title="Role Management", color=EMBED_COLOR)
        embed.add_field(name=".setrole [name] [@role]", value="Map a custom role name", inline=False)
        embed.add_field(name=".assignrole [name] [@user]", value="Assign/remove mapped role", inline=False)
        
        if config['role_mappings']:
            roles_list = "\n".join(f"- {name}" for name in config['role_mappings'].keys())
            embed.add_field(name="Available Mappings", value=roles_list, inline=False)
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(RoleManagement(bot))
