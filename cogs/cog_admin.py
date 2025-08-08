import logging
import os
import pymysql as sql
import discord
from discord import option
from discord.ext import commands
import utils


class AdminCog(commands.Cog):
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
        update = utils.check_update(self.logger)
        if update is not False:
            embed.add_field(name="Version", value=f"{utils.get_version()}\n**Version `{update['remote']}` is "
                                                  f"available!**")
        else:
            embed.add_field(name="Version", value=utils.get_version())
        embed.add_field(name="Author", value="BEMZlabs")
        embed.add_field(name="Source", value="[GitHub](https://github.com/ShapedBuildingServer/Discord-Bot)")
        embed.add_field(name="License", value="MIT")
        embed.add_field(name="Git commit hashes", value="", inline=False)
        git_commit_hash = utils.get_git_commit_hash()
        if git_commit_hash != {}:
            for key, value in git_commit_hash.items():
                embed.add_field(name=key, value=f"`{value}`")
        await ctx.respond(embed=embed, ephemeral=True)

    @permissions.command(name="show", description="Show a users permissions.")
    async def show(self, ctx: discord.ApplicationContext, member: discord.Member):
        if not await utils.has_permission(ctx, "manage_local_permissions"):
            await ctx.respond("❌ `You do not have permission to show local permissions`", ephemeral=True)
            return
        else:
            user_id = member.id if member else ctx.author.id
            utils.db_connector().execute(f"SELECT permissions FROM {utils.table('users')} WHERE user_id = %s", (user_id,))
            permissions = utils.db_connector().fetchone()
            if not permissions:
                utils.db_connector().execute(f"INSERT INTO {utils.table('users')} (user_id, permissions) VALUES (%s, %s)", (member.id, ""))
                utils.db_connector().commit()
                permissions = utils.db_connector().fetchone()
            permissions = utils.convert_permission(permissions[0] if permissions else "")
            embed = discord.Embed(title="Permissions")
            for key, value in permissions.items():
                embed.add_field(name=key, value='✅' if value else '❌')
            if str(member.id) in os.getenv("BYPASS_PERMISSIONS"):
                embed.add_field(name="This user is a bot admin", value="They have all permissions")
            embed.set_author(name=f"Permissions for {member.display_name}", icon_url=member.avatar.url)
            await ctx.respond(embed=embed, ephemeral=True)

    @permissions.command(name="modify", description="Invert a user's permission.")
    @option(name="permission", description="The permission you want to grant/revoke", required=True,
            choices=["manage_local_permissions", "manage_embeds", "manage_threads"])
    async def modify(self, ctx: discord.ApplicationContext, member: discord.Member, permission: str):
        if await utils.has_permission(ctx, "manage_local_permissions"):
            utils.db_connector().execute(f"SELECT permissions FROM {utils.table('users')} WHERE user_id = %s", (member.id,))
            permissions = utils.db_connector().fetchone()
            if not permissions:
                utils.db_connector().execute(f"INSERT INTO {utils.table('users')} (user_id, permissions) VALUES (%s, %s)", (member.id, ""))
                utils.db_connector().commit()
                permissions = utils.db_connector().fetchone()
            permissions = utils.convert_permission(permissions[0] if permissions else "")
            if permission in permissions:
                permissions[permission] = not permissions[permission]
                print_perm = 'True' if permissions[permission] else 'False'
                permissions = utils.convert_permission(permissions)
                utils.db_connector().execute(f"UPDATE {utils.table('users')} SET permissions = %s WHERE user_id = %s", (permissions, member.id))
                utils.db_connector().commit()
                await ctx.respond(f"✔ `Set {permission} for {member.display_name} to {print_perm}`", ephemeral=True)
            else:
                await ctx.respond(f"❌ `Invalid permission: {permission}`", ephemeral=True)
        else:
            await ctx.respond("❌ `You do not have permission to manage local permissions`", ephemeral=True)

    @forum.command(name="remove", description="Remove a forum channel")
    async def remove(self, ctx: discord.ApplicationContext, channel: discord.ForumChannel):
        if not await utils.has_permission(ctx, "manage_threads"):
            await ctx.respond("❌ `You do not have permission to manage threads`", ephemeral=True)
            return
        forum_channels = await utils.get_forum_channels(ctx.guild)
        if ctx.channel.id not in forum_channels:
            await ctx.respond("❌ `This channel is not set up as a forum channel`", ephemeral=True)
            return
        forum_channels.remove(ctx.channel.id)
        utils.db_connector().execute(f"UPDATE {utils.table('guilds')} SET thread_channels = %s WHERE guild_id = %s",
                                     (",".join([str(channel) for channel in forum_channels]), ctx.guild.id))
        utils.db_connector().commit()
        await ctx.respond(f"✔ `Channel {channel.name} has been removed as a forum channel`", ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info(f'Hello from {self.__class__.__name__}!')


def setup(bot):
    bot.add_cog(AdminCog(bot, bot.logger))
