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
        self.config_dir = "server_configs"
        os.makedirs(self.config_dir, exist_ok=True)
        self.emojis = {
            "success": "✅",
            "error": "❌",
            "info": "ℹ️",
            "warning": "⚠️",
            "roles": "🛡️",
            "log": "📋",
        }

    def get_config_path(self, guild_id):
        return os.path.join(self.config_dir, f"{guild_id}.json")

    def load_configs(self, guild_id):
        """Load server configurations from JSON."""
        config_path = self.get_config_path(guild_id)
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def save_configs(self, guild_id, config):
        """Save server configurations to JSON."""
        config_path = self.get_config_path(guild_id)
        with open(config_path, "w") as f:
            json.dump(config, f, indent=4)

    def get_server_config(self, guild_id):
        """Get or create server configuration."""
        config = self.load_configs(guild_id)
        if not config:
            config = {
                "role_mappings": {},
                "reqrole_id": None,
                "log_channel_id": None,
                "role_assignment_limit": 100,
                "admin_only_commands": True,
            }
            self.save_configs(guild_id, config)
        return config

    async def log_activity(self, guild, action, details):
        """Log activities to the designated log channel."""
        config = self.get_server_config(guild.id)
        log_channel_id = config.get("log_channel_id")

        if log_channel_id:
            try:
                log_channel = guild.get_channel(log_channel_id)
                if log_channel:
                    embed = discord.Embed(
                        title=f"{self.emojis['log']} Activity Log",
                        description=f"**Action:** {action}\n**Details:** {details}",
                        color=INFO_COLOR,
                    )
                    await log_channel.send(embed=embed)
            except Exception as e:
                logger.error(f"Logging error: {e}")

    async def check_required_role(self, ctx):
        """Check if user has the required role or is an administrator."""
        config = self.get_server_config(ctx.guild.id)
        reqrole_id = config.get("reqrole_id")

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
                color=ERROR_COLOR,
            )
            await ctx.send(embed=embed)
            return False

        if reqrole not in ctx.author.roles:
            embed = discord.Embed(
                title=f"{self.emojis['error']} Permission Denied",
                description=f"You need the {reqrole.mention} role to use this command.",
                color=ERROR_COLOR,
            )
            await ctx.send(embed=embed)
            return False

        return True

    @commands.command()
    async def reset_roles(self, ctx):
        """Reset all role mappings for the server."""
        if not ctx.author.guild_permissions.administrator:
            embed = discord.Embed(
                title=f"{self.emojis['error']} Permission Denied",
                description="You must be an administrator to use this command.",
                color=ERROR_COLOR,
            )
            await ctx.send(embed=embed)
            return

        config = self.get_server_config(ctx.guild.id)
        config["role_mappings"] = {}
        self.save_configs(ctx.guild.id, config)

        embed = discord.Embed(
            title=f"{self.emojis['warning']} Role Mappings Reset",
            description="All role mappings have been cleared.",
            color=WARNING_COLOR,
        )
        await ctx.send(embed=embed)

        await self.log_activity(ctx.guild, "Role Mappings Reset", "All mappings cleared.")

    @commands.command()
    async def reset_role(self, ctx, role_name: str):
        """Reset a specific role mapping by name."""
        if not ctx.author.guild_permissions.administrator:
            embed = discord.Embed(
                title=f"{self.emojis['error']} Permission Denied",
                description="You must be an administrator to use this command.",
                color=ERROR_COLOR,
            )
            await ctx.send(embed=embed)
            return

        config = self.get_server_config(ctx.guild.id)

        if role_name not in config["role_mappings"]:
            embed = discord.Embed(
                title=f"{self.emojis['error']} Role Not Found",
                description=f"No mapping exists for `{role_name}`.",
                color=ERROR_COLOR,
            )
            await ctx.send(embed=embed)
            return

        del config["role_mappings"][role_name]
        self.save_configs(ctx.guild.id, config)

        embed = discord.Embed(
            title=f"{self.emojis['success']} Role Mapping Removed",
            description=f"The mapping for `{role_name}` has been removed.",
            color=SUCCESS_COLOR,
        )
        await ctx.send(embed=embed)

        await self.log_activity(
            ctx.guild, "Role Mapping Removed", f"Mapping for `{role_name}` removed."
        )

    @commands.command()
    async def rolehelp(self, ctx):
        """Show role management commands."""
        config = self.get_server_config(ctx.guild.id)

        embed = discord.Embed(
            title=f"{self.emojis['info']} Role Management",
            color=INFO_COLOR,
        )
        embed.add_field(
            name=".setlogchannel [@channel]",
            value="Set log channel for bot activities",
            inline=False,
        )
        embed.add_field(
            name=".reqrole [@role]",
            value="Set required role for role management",
            inline=False,
        )
        embed.add_field(
            name=".reset_roles", value="Reset all role mappings", inline=False
        )
        embed.add_field(
            name=".reset_role [role_name]",
            value="Reset mapping for a specific role",
            inline=False,
        )

        if config["role_mappings"]:
            roles_list = "\n".join(
                f"- .{name} [@user]"
                for name in config["role_mappings"].keys()
            )
            embed.add_field(
                name="Available Role Commands", value=roles_list, inline=False
            )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(RoleManagement(bot))
