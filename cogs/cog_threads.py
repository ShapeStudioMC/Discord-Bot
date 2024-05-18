import logging

import discord
from discord import option
from discord.ext import commands, tasks
import utils as util
import aiosqlite


class NoteModal(discord.ui.Modal):
    def __init__(self, note, db_location, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.db_location = db_location
        self.add_item(discord.ui.InputText(label="Edit Note", style=discord.InputTextStyle.paragraph, value=note,
                                           placeholder="Enter your note here (Markdown supported)."))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        new_note = interaction.data["components"][0]["components"][0]["value"]
        async with aiosqlite.connect(self.db_location) as db:
            await db.execute("UPDATE threads SET note = ?, note_last_update = ? WHERE thread_id = ?",
                             (new_note, util.time_since_epoch(), interaction.channel.id))
            await db.commit()
        # update the note
        note = await util.get_note(interaction.channel)
        print(note)
        m = await interaction.channel.fetch_message(note[2])
        await m.edit(content=None, embed=await util.build_forum_embed(interaction.channel))
        await interaction.followup.send("Note updated!", ephemeral=True, delete_after=5)
        return True


class Threads(commands.Cog):
    def __init__(self, bot, logger):
        self.bot = bot
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.handlers = logger.handlers
        self.logger.setLevel(logger.level)
        self.logger.propagate = False

    forum = discord.SlashCommandGroup(name="forum", description="Commands for managing forum posts")

    async def button_edit_note_callback(self, interaction: discord.Interaction):
        note = await util.get_note(interaction.channel)
        modal = NoteModal(title=f"Edit note for {interaction.channel.name}", note=note[0] if note else "No note found",
                          db_location=self.bot.db_location)
        await interaction.response.send_modal(modal)

    @tasks.loop(minutes=5)
    async def update_notes(self):
        async with aiosqlite.connect(self.bot.db_location) as db:
            async with db.execute("SELECT thread_id, note_id FROM threads") as cursor:
                threads = await cursor.fetchall()
        view = discord.ui.View()
        button = discord.ui.Button(label="Edit Note", style=discord.ButtonStyle.primary)
        button.callback = self.button_edit_note_callback
        view.add_item(button)
        for thread in threads:
            t = self.bot.get_channel(thread[0])
            m = await t.fetch_message(thread[1])
            embed = await util.build_forum_embed(t)
            await m.edit(embed=embed, content=None, view=view)

    @commands.Cog.listener()
    async def on_ready(self):
        self.update_notes.start()

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        if thread.parent.id in await util.get_forum_channels(thread.guild):
            self.logger.info(f"New thread in forum: {thread.parent.name}, {thread.name}")
            m = await thread.send("Welcome to the thread! This message will be updated when I receive information from "
                                  "the database!")
            async with aiosqlite.connect(self.bot.db_location) as db:
                await db.execute("INSERT INTO threads (thread_id, channel_id, note, note_id, note_last_update) VALUES "
                                 "(?, ?, ?, ?, ?);", (thread.id, thread.parent.id, "Hello! This space can be used to "
                                                                                   "keep notes about the current "
                                                                                   "project in this thread. To edit "
                                                                                   "this note please use the `/forum "
                                                                                   "note` command.", m.id,
                                                      util.time_since_epoch()))
                await db.commit()

    @commands.Cog.listener()
    async def on_thread_delete(self, thread):
        if thread.parent.id in await util.get_forum_channels(thread.guild):
            self.logger.warning(f"Thread deleted: {thread.name}")
            async with aiosqlite.connect(self.bot.db_location) as db:
                await db.execute("DELETE FROM threads WHERE thread_id = ?", (thread.id,))
                await db.commit()

    @forum.command(name="setup", description="Set up a channel as a forum channel to track")
    @option(name="channel", description="The channel to set up", required=True, channel=True)
    async def setup_forum(self, ctx: discord.ApplicationContext, channel: discord.ForumChannel):
        """insert the channel into the database"""
        forum_channels = await util.get_forum_channels(ctx.guild)
        if channel.id in forum_channels:
            await ctx.respond("This channel is already set up as a forum channel", ephemeral=True)
            return
        forum_channels.append(channel.id)
        print(forum_channels)
        async with aiosqlite.connect(self.bot.db_location) as db:
            await db.execute("UPDATE guilds SET thread_channels = ? WHERE guild_id = ?",
                             (",".join(map(str, forum_channels)), ctx.guild.id))
            await db.commit()
        await ctx.respond(f"Channel {channel.name} has been set up as a forum channel", ephemeral=True)

    @forum.command(name="note", description="Modify the note for a forum thread")
    async def note(self, ctx: discord.ApplicationContext):
        try:
            if ctx.channel.parent.id not in await util.get_forum_channels(ctx.guild):
                await ctx.respond("This command can only be used in a forum post!", ephemeral=True, delete_after=5)
                return
        except AttributeError:
            await ctx.respond("This command can only be used in a forum post!", ephemeral=True, delete_after=5)
            return
        note = await util.get_note(ctx.channel)
        # Check if the user is the owner of the thread
        if (ctx.author != ctx.channel.owner or not ctx.author.guild_permissions.manage_messages or
                not await util.has_permission(ctx.author.id, "manage_threads", self.bot.db_location)):
            await ctx.respond("You do not have permission to edit this note!", ephemeral=True, delete_after=5)
            return
        modal = NoteModal(title=f"Edit note for {ctx.channel.parent.name}", note=note[0] if note else "No note found",
                          db_location=self.bot.db_location)
        await ctx.send_modal(modal)


def setup(bot):
    bot.add_cog(Threads(bot, bot.logger))
