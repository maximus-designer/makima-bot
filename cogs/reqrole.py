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

    # ... [previous methods remain the same] ...

    @commands.command()
    async def reset_role(self, ctx, custom_name: str = None):
        """Reset role mappings with interactive options."""
        if not ctx.author.guild_permissions.administrator:
            return await self.admin_only_command(ctx)
        
        config = self.get_server_config(ctx.guild.id)
        role_mappings = config.get('role_mappings', {})

        # If a specific custom_name is provided, reset only that mapping
        if custom_name:
            if custom_name in role_mappings:
                del config['role_mappings'][custom_name]
                self.save_configs(ctx.guild.id, config)
                
                embed = discord.Embed(
                    title=f"{self.emojis['warning']} Role Mapping Reset", 
                    description=f"Mapping for '{custom_name}' has been removed.", 
                    color=SUCCESS_COLOR
                )
                await ctx.send(embed=embed)
                
                await self.log_activity(
                    ctx.guild, 
                    "Role Mapping Removed", 
                    f"Mapping for '{custom_name}' deleted"
                )
                
                # Regenerate dynamic commands
                self.create_dynamic_role_commands()
                return

            # If specified custom_name doesn't exist
            embed = discord.Embed(
                title=f"{self.emojis['error']} Invalid Mapping", 
                description=f"No mapping found for '{custom_name}'.", 
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            return

        # Interactive reset for multiple mappings
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

    # ... [rest of the code remains the same] ...

async def setup(bot):
    await bot.add_cog(RoleManagement(bot))
