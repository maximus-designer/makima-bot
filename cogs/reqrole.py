@commands.command()
    @commands.has_permissions(administrator=True)
    async def reset_all_roles(self, ctx):
        """Reset all mapped custom roles for the current server."""
        # Check if user has required role
        if not await self.check_required_role(ctx):
            return
        
        guild_id = str(ctx.guild.id)
        
        # Find all custom role mappings for this guild
        role_mappings = await self.role_mappings.find({"guild_id": guild_id}).to_list(length=None)
        
        if not role_mappings:
            await ctx.send(embed=discord.Embed(
                description="No custom role mappings found for this server.", 
                color=self.EMBED_COLOR
            ))
            return
        
        # Collect mapped role IDs
        mapped_role_ids = [mapping['role_id'] for mapping in role_mappings]
        
        # Remove mapped roles from all members
        removed_count = 0
        for member in ctx.guild.members:
            # Find roles to remove (only those mapped)
            roles_to_remove = [role for role in member.roles if role.id in mapped_role_ids]
            
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove)
                removed_count += 1
        
        # Log channel notification
        config = await self.guild_configs.find_one({"guild_id": guild_id})
        if config and 'log_channel_id' in config:
            log_channel = ctx.guild.get_channel(config['log_channel_id'])
            if log_channel:
                await log_channel.send(embed=discord.Embed(
                    description=f"{ctx.author.mention} reset all mapped roles for the server.", 
                    color=self.EMBED_COLOR
                ))
        
        # Send confirmation
        await ctx.send(embed=discord.Embed(
            description=f"Removed mapped roles from {removed_count} members.", 
            color=self.EMBED_COLOR
        ))
        
        # Log the action
        logger.info(f"Reset all mapped roles for guild {guild_id}")

    @commands.command()
    async def role(self, ctx):
        """Shows all available role management commands."""
        embed = discord.Embed(title="Role Management Commands", color=self.EMBED_COLOR)
        embed.add_field(name=".setreqrole [role]", value="Set the role required for assigning/removing roles.", inline=False)
        embed.add_field(name=".setrole [custom_name] [@role]", value="Map a custom name to a role.", inline=False)
        embed.add_field(name=".setlogchannel [channel]", value="Set the log channel for role actions.", inline=False)
        embed.add_field(name=".reset_all_roles", value="Remove all mapped roles from server members.", inline=False)
        embed.add_field(name=".[custom_name] [@user]", value="Assign/remove the mapped role to/from a user.", inline=False)
        embed.add_field(name=".set_role_limit [limit]", value="Set maximum number of custom roles per user.", inline=False)
        embed.set_footer(text="Role Management Bot")
        await ctx.send(embed=embed)
