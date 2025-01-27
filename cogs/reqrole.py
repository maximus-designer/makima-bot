import discord
import logging
import os
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MONGO_URL = os.getenv('MONGO_URL')
DB_NAME = os.getenv('DB_NAME', 'discord_bot')

COLORS = {
    'embed': 0x2f2136,
    'success': 0x2ecc71,
    'error': 0xe74c3c,
    'info': 0x3498db,
    'warning': 0xf39c12
}

class RoleManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
        self.emojis = {'success': '<:sukoon_tick:1322894604898664478>', 'error': '<:sukoon_cross:1322894630684983307>', 'info': '<:sukoon_info:1323251063910043659>', 'warning': '<a:sukoon_reddot:1322894157794119732>', 'roles': '<a:sukoon_butterfly:1323990263609298967>', 'log': '<a:sukoon_loadingg:1331341543390314656>'}

    async def get_config(self, guild_id):
        config = await self.db.guild_configs.find_one({'_id': guild_id})
        return config or {
            '_id': guild_id,
            'role_mappings': {},
            'reqrole_id': None,
            'log_channel_id': None,
            'role_assignment_limit': 5,
            'admin_only_commands': True
        }

    async def save_config(self, guild_id, config):
        await self.db.guild_configs.replace_one({'_id': guild_id}, config, upsert=True)

    async def log_activity(self, guild, action, details):
        config = await self.get_config(guild.id)
        if log_channel := guild.get_channel(config.get('log_channel_id')):
            try:
                embed = discord.Embed(title=f"{self.emojis['log']} Activity Log",
                                    description=f"**Action:** {action}\n**Details:** {details}",
                                    color=COLORS['info'])
                await log_channel.send(embed=embed)
            except Exception as e:
                logger.error(f"Logging error: {e}")

    async def check_role_permission(self, ctx):
        config = await self.get_config(ctx.guild.id)
        if ctx.author.guild_permissions.administrator:
            return True, None
        if req_role_id := config.get('reqrole_id'):
            if req_role := ctx.guild.get_role(req_role_id):
                return (True, None) if req_role in ctx.author.roles else (
                    False, (f"{self.emojis['error']} Permission Denied", 
                           f"You must have the {req_role.mention} role to manage roles."))
        return False, (f"{self.emojis['error']} Role Management Disabled", 
                      "Role management has not been configured for this server.")

    async def admin_only_command(self, ctx):
        embed = discord.Embed(title=f"{self.emojis['error']} Permission Denied",
                            description="You must be a server administrator to use this command.",
                            color=COLORS['error'])
        await ctx.send(embed=embed)
        await self.log_activity(ctx.guild, "Unauthorized Command", 
                              f"{ctx.author.name} attempted to use an admin-only command")

    @commands.command()
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        if not ctx.author.guild_permissions.administrator:
            return await self.admin_only_command(ctx)
        config = await self.get_config(ctx.guild.id)
        config['log_channel_id'] = channel.id
        await self.save_config(ctx.guild.id, config)
        embed = discord.Embed(title=f"{self.emojis['success']} Log Channel Set",
                            description=f"Logging activities to {channel.mention}",
                            color=COLORS['success'])
        await ctx.send(embed=embed)
        await self.log_activity(ctx.guild, "Log Channel Setup", f"Log channel set to {channel.name}")

    @commands.command()
    async def reqrole(self, ctx, role: discord.Role):
        if not ctx.author.guild_permissions.administrator:
            return await self.admin_only_command(ctx)
        config = await self.get_config(ctx.guild.id)
        config['reqrole_id'] = role.id
        await self.save_config(ctx.guild.id, config)
        embed = discord.Embed(title=f"{self.emojis['roles']} Required Role Set",
                            description=f"Only members with {role.mention} can now manage roles.",
                            color=COLORS['success'])
        await ctx.send(embed=embed)
        await self.log_activity(ctx.guild, "Required Role Updated", f"New required role: {role.name}")

    @commands.command()
    async def setrole(self, ctx, custom_name: str, role: discord.Role):
        if not ctx.author.guild_permissions.administrator:
            return await self.admin_only_command(ctx)
        config = await self.get_config(ctx.guild.id)
        if custom_name not in config['role_mappings']:
            config['role_mappings'][custom_name] = []
        if role.id not in config['role_mappings'][custom_name]:
            config['role_mappings'][custom_name].append(role.id)
        await self.save_config(ctx.guild.id, config)
        embed = discord.Embed(title=f"{self.emojis['success']} Role Mapping Added",
                            description=f"Mapped '{custom_name}' to {role.mention}",
                            color=COLORS['success'])
        await ctx.send(embed=embed)
        self.create_dynamic_role_commands()
        await self.log_activity(ctx.guild, "Role Mapping", f"Mapped '{custom_name}' to {role.name}")

    @commands.command()
    async def reset_role(self, ctx):
        if not ctx.author.guild_permissions.administrator:
            return await self.admin_only_command(ctx)
        config = await self.get_config(ctx.guild.id)
        role_mappings = config.get('role_mappings', {})

        class ResetRoleView(discord.ui.View):
            def __init__(self, ctx, cog, role_mappings):
                super().__init__()
                self.ctx = ctx
                self.cog = cog
                self.role_mappings = role_mappings
                self.select_menu.options = [discord.SelectOption(label=name, description=f"Reset mapping for '{name}'")
                                          for name in role_mappings.keys()]
                self.select_menu.options.append(discord.SelectOption(label="Reset All Mappings",
                                                                   description="Reset ALL role mappings",
                                                                   value="_reset_all"))

            @discord.ui.select(placeholder="Select Role Mapping to Reset")
            async def select_menu(self, interaction: discord.Interaction, select: discord.ui.Select):
                selected = select.values[0]
                config = await self.cog.get_config(self.ctx.guild.id)
                if selected == "_reset_all":
                    config['role_mappings'] = {}
                    desc = "All role mappings have been cleared."
                else:
                    del config['role_mappings'][selected]
                    desc = f"Mapping for '{selected}' has been removed."
                await self.cog.save_config(self.ctx.guild.id, config)
                embed = discord.Embed(title=f"{self.cog.emojis['warning']} Role Mapping Reset",
                                    description=desc, color=COLORS['success'])
                await interaction.response.send_message(embed=embed)
                await self.cog.log_activity(self.ctx.guild, "Role Mapping Reset", desc)
                self.cog.create_dynamic_role_commands()
                self.stop()

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
            async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                embed = discord.Embed(title=f"{self.cog.emojis['error']} Reset Cancelled",
                                    description="Role mapping reset was cancelled.",
                                    color=COLORS['error'])
                await interaction.response.send_message(embed=embed)
                self.stop()

        if not role_mappings:
            embed = discord.Embed(title=f"{self.emojis['info']} No Mappings",
                                description="There are no role mappings to reset.",
                                color=COLORS['info'])
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(title=f"{self.emojis['warning']} Reset Role Mappings",
                            description="Select a role mapping to reset or choose to reset all mappings.",
                            color=COLORS['warning'])
        view = ResetRoleView(ctx, self, role_mappings)
        await ctx.send(embed=embed, view=view)

    def create_dynamic_role_commands(self):
        async def dynamic_role_command(ctx, member: discord.Member, custom_name=None):
            if ctx.author == member:
                embed = discord.Embed(title=f"{self.emojis['error']} Role Assignment Error",
                                    description="You cannot assign roles to yourself.",
                                    color=COLORS['error'])
                return await ctx.send(embed=embed)

            is_allowed, error_info = await self.check_role_permission(ctx)
            if not is_allowed:
                if error_info:
                    embed = discord.Embed(title=error_info[0], description=error_info[1],
                                        color=COLORS['error'])
                    return await ctx.send(embed=embed)

            config = await self.get_config(ctx.guild.id)
            role_ids = config['role_mappings'].get(custom_name, [])
            roles = [r for r in (ctx.guild.get_role(rid) for rid in role_ids) if r]

            if not roles:
                embed = discord.Embed(title=f"{self.emojis['error']} Role Error",
                                    description=f"No valid roles mapped to '{custom_name}'",
                                    color=COLORS['error'])
                return await ctx.send(embed=embed)

            roles_added = []
            roles_removed = []
            for role in roles:
                if role in member.roles:
                    await member.remove_roles(role)
                    roles_removed.append(role)
                else:
                    await member.add_roles(role)
                    roles_added.append(role)

            for role_list, action, color in [(roles_added, "Added", 'success'),
                                           (roles_removed, "Removed", 'error')]:
                if role_list:
                    embed = discord.Embed(
                        title=f"{self.emojis['success' if action == 'Added' else 'warning']} Roles {action}",
                        description=f"{action} to {member.name}: {', '.join(r.name for r in role_list)}",
                        color=COLORS[color])
                    await ctx.send(embed=embed)
                    await self.log_activity(ctx.guild, f"Role {action}",
                                          f"{ctx.author.name} {action.lower()} roles for {member.name}: {', '.join(r.name for r in role_list)}")

        for guild_id in await self.db.guild_configs.distinct('_id'):
            config = await self.get_config(guild_id)
            for custom_name in config.get('role_mappings', {}):
                if custom_name in self.bot.all_commands:
                    self.bot.remove_command(custom_name)
                command = commands.command(name=custom_name)(dynamic_role_command)
                command.cog = self
                self.bot.add_command(command)

    @commands.Cog.listener()
    async def on_ready(self):
        self.create_dynamic_role_commands()
        logger.info('Dynamic role commands created for servers.')

    @commands.command()
    async def rolehelp(self, ctx):
        config = await self.get_config(ctx.guild.id)
        embed = discord.Embed(title=f"{self.emojis['info']} Role Management", color=COLORS['info'])
        embed.add_field(name=".setlogchannel [@channel]", value="Set log channel for bot activities", inline=False)
        embed.add_field(name=".reqrole [@role]", value="Set required role for role management", inline=False)
        embed.add_field(name=".setrole [name] [@role]", value="Map a custom role name", inline=False)
        embed.add_field(name=".reset_role", value="Reset role mappings", inline=False)
        if config['role_mappings']:
            roles_list = "\n".join(f"- .{name} [@user]" for name in config['role_mappings'].keys())
            embed.add_field(name="Available Role Commands", value=roles_list, inline=False)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(RoleManagement(bot))
