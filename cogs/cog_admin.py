import logging
import os

import aiosqlite as sqlite
import discord
from discord import option
from discord.ext import commands
import utils


class admin_cog(commands.Cog):
    def __init__(self, bot, logger):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.handlers = logger.handlers
        self.logger.setLevel(logger.level)
        self.logger.propagate = False
        self.bot = bot

    # create slash command groups
    admin = discord.SlashCommandGroup(name="admin", description="Commands for managing the bot")
    forum = admin.create_subgroup(name="forum", description="Commands for managing forum posts")
    permissions = admin.create_subgroup(name="permissions", description="Commands for managing permissions")

    @admin.command(name="info", description="Get information about the bot")
    async def info(self, ctx: discord.ApplicationContext):
        embed = discord.Embed(title="Bot Information", description="A bot for managing forum posts")
        embed.add_field(name="Version", value=os.getenv("VERSION"))
        embed.add_field(name="Author", value="BEMZlabs")
        embed.add_field(name="Source", value="[GitHub](https://github.com/ShapedBuildingServer/Discord-Bot)")
        await ctx.respond(embed=embed, ephemeral=True)

    @permissions.command(name="show", description="Show a users permissions.")
    async def show(self, ctx: discord.ApplicationContext, member: discord.Member):
        if not utils.has_permission(ctx.author.id, "manage_local_permissions", self.bot.db_location):
            await ctx.respond("You do not have permission to manage local permissions", ephemeral=True)
            return
        else:
            user_id = member.id if member else ctx.author.id
            print(f"member: {member}, user_id: {user_id}")
            async with sqlite.connect(self.bot.db_location) as db:
                async with db.execute("SELECT permissions FROM users WHERE user_id = ?", (user_id,)) as cursor:
                    permissions = await cursor.fetchone()
                    if not permissions:
                        await db.execute("INSERT INTO users (user_id, permissions) VALUES (?, ?)", (member.id, ""))
                        await db.commit()
                        permissions = await cursor.fetchone()
            permissions = utils.convert_permission(permissions[0] if permissions else "")
            embed = discord.Embed(title="Permissions")
            for key, value in permissions.items():
                embed.add_field(name=key, value='✅' if value else '❌')
            embed.set_author(name=f"Permissions for {member.display_name}", icon_url=member.avatar.url)
            await ctx.respond(embed=embed, ephemeral=True)

    @permissions.command(name="modify", description="Invert a user's permission.")
    @option(name="permission", description="The permission you want to grant/revoke", required=True,
            choices=["manage_local_permissions", "manage_embeds", "manage_threads"])
    async def modify(self, ctx: discord.ApplicationContext, member: discord.Member, permission: str):
        if await utils.has_permission(ctx.author.id, "manage_local_permissions", self.bot.db_location):
            async with sqlite.connect(self.bot.db_location) as db:
                async with db.execute("SELECT permissions FROM users WHERE user_id = ?", (member.id,)) as cursor:
                    permissions = await cursor.fetchone()
                    if not permissions:
                        await db.execute("INSERT INTO users (user_id, permissions) VALUES (?, ?)", (member.id, ""))
                        await db.commit()
                        permissions = await cursor.fetchone()
            permissions = utils.convert_permission(permissions[0] if permissions else "")
            if permission in permissions:
                permissions[permission] = not permissions[permission]
                print_perm = 'True' if permissions[permission] else 'False'
                permissions = utils.convert_permission(permissions)
                async with sqlite.connect(self.bot.db_location) as db:
                    await db.execute("UPDATE users SET permissions = ? WHERE user_id = ?", (permissions, member.id))
                    await db.commit()
                await ctx.respond(f"Set {permission} for {member.display_name} to {print_perm}", ephemeral=True)
            else:
                await ctx.respond(f"Invalid permission: {permission}", ephemeral=True)
        else:
            await ctx.respond("You do not have permission to manage local permissions", ephemeral=True)

    @forum.command(name="remove", description="Remove a forum channel")
    async def remove(self, ctx: discord.ApplicationContext, channel: discord.ForumChannel):
        if not utils.has_permission(ctx.author.id, "manage_threads", self.bot.db_location):
            await ctx.respond("You do not have permission to manage threads", ephemeral=True)
            return
        forum_channels = await utils.get_forum_channels(ctx.guild)
        if ctx.channel.id not in forum_channels:
            await ctx.respond("This channel is not set up as a forum channel", ephemeral=True)
            return
        forum_channels.remove(ctx.channel.id)
        async with sqlite.connect(self.bot.db_location) as db:
            await db.execute("UPDATE guilds SET thread_channels = ? WHERE guild_id = ?",
                             (",".join([str(channel) for channel in forum_channels]), ctx.guild.id))
            await db.commit()
        await ctx.respond(f"Channel {channel.name} has been removed as a forum channel", ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info(f'Hello from {self.__class__.__name__}!')


def setup(bot):
    bot.add_cog(admin_cog(bot, bot.logger))
