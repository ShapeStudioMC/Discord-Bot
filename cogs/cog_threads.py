import json
import logging
import discord
from discord import option
from discord.ext import commands, tasks

import utils
import utils as util
import aiosqlite


class NoteModal(discord.ui.Modal):
    """
    A modal dialog for editing a note.

    Attributes:
        db_location (str): The location of the database.
    """

    def __init__(self, note, db_location, *args, **kwargs) -> None:
        """
        Initialize the NoteModal.

        Args:
            note (str): The initial note content.
            db_location (str): The location of the database.
        """
        super().__init__(*args, **kwargs)
        self.db_location = db_location
        self.add_item(discord.ui.InputText(label="Edit Note", style=discord.InputTextStyle.paragraph, value=note,
                                           placeholder="Enter your note here (Markdown supported)."))

    async def callback(self, interaction: discord.Interaction):
        """
        Handle the submission of the modal.

        Args:
            interaction (discord.Interaction): The interaction that triggered the modal.
        """
        await interaction.response.defer()
        new_note = interaction.data["components"][0]["components"][0]["value"]
        async with aiosqlite.connect(self.db_location) as db:
            await db.execute("UPDATE threads SET note = ?, note_last_update = ? WHERE thread_id = ?",
                             (new_note, util.time_since_epoch(), interaction.channel.id))
            await db.commit()
        # update the note
        note = await util.get_note(interaction.channel)
        m = await interaction.channel.fetch_message(note[2])
        await m.edit(content=None, embed=await util.build_forum_embed(interaction.channel))
        await interaction.followup.send("Note updated!", ephemeral=True, delete_after=5)
        return True


class DefaultNoteModal(NoteModal):
    """
    A modal dialog for editing the default note of a channel.

    Attributes:
        channel_id (int): The ID of the channel.
    """

    def __init__(self, note, db_location, channel_id, *args, **kwargs) -> None:
        """
        Initialize the DefaultNoteModal.

        Args:
            note (str): The initial note content.
            db_location (str): The location of the database.
            channel_id (int): The ID of the channel.
        """
        super().__init__(note=note, db_location=db_location, *args, **kwargs)
        self.channel_id = channel_id

    async def callback(self, interaction: discord.Interaction):
        """
        Handle the submission of the modal.

        Args:
            interaction (discord.Interaction): The interaction that triggered the modal.
        """
        await interaction.response.defer()
        new_note = interaction.data["components"][0]["components"][0]["value"]
        settings = await util.get_settings(interaction.guild)
        settings["defaultNote"][self.channel_id] = new_note
        async with aiosqlite.connect(self.db_location) as db:
            await db.execute("UPDATE guilds SET settings = ? WHERE guild_id = ?",
                             (json.dumps(settings), interaction.guild.id))
            await db.commit()
        em = await util.build_forum_embed(note=new_note)
        await interaction.followup.send("Default note has been modified!", ephemeral=True, delete_after=15, embed=em)
        return True


class JumpButton(discord.ui.View):
    def __init__(self, JumpURL):
        super().__init__()
        button = discord.ui.Button(label="Jump to Note", style=discord.ButtonStyle.url, url=JumpURL)
        self.add_item(button)


async def button_edit_note_callback(interaction: discord.Interaction):
    """
    Callback function for the "Edit Note" button.

    Args:
        interaction (discord.Interaction): The interaction that triggered the button.
    """
    note = await util.get_note(interaction.channel, replace_tags=False)
    modal = NoteModal(title=util.limit(f"Edit note for {interaction.channel.name}", 45),
                      note=note[0] if note else "No note found",
                      db_location=util.get_db_location())
    await interaction.response.send_modal(modal)


class Threads(commands.Cog):
    """
    A cog for managing forum threads and notes.

    Attributes:
        bot (commands.Bot): The bot instance.
        logger (logging.Logger): The logger instance.
    """

    def __init__(self, bot, logger):
        """
        Initialize the Threads cog.

        Args:
            bot (commands.Bot): The bot instance.
            logger (logging.Logger): The logger instance.
        """
        self.bot = bot
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.handlers = logger.handlers
        self.logger.setLevel(logger.level)
        self.logger.propagate = False

    forum = discord.SlashCommandGroup(name="forum", description="Commands for managing forum posts")

    @tasks.loop(minutes=5)
    async def update_notes(self):
        """
        Periodically update the notes for all threads.
        """
        await self.bot.wait_until_ready()
        async with aiosqlite.connect(self.bot.db_location) as db:
            async with db.execute("SELECT thread_id, note_id FROM threads") as cursor:
                threads = await cursor.fetchall()
        view = discord.ui.View()
        button = discord.ui.Button(label="Edit Note", style=discord.ButtonStyle.primary)
        button.callback = button_edit_note_callback
        view.add_item(button)
        for thread in threads:
            t = self.bot.get_channel(thread[0])
            if not t:
                self.logger.warning(f"Thread {thread[0]} not found, deleting from database.")
                async with aiosqlite.connect(self.bot.db_location) as db:
                    await db.execute("DELETE FROM threads WHERE thread_id = ?", (thread[0],))
                    await db.commit()
                continue
            else:
                m = await t.fetch_message(thread[1])
                embed = await util.build_forum_embed(t)
                try:
                    if embed.description == m.embeds[0].description:
                        self.logger.info(f"Note for {t.name} is up to date, refreshing the button.")
                        await m.edit(view=view)
                        continue
                except IndexError:
                    pass
                self.logger.info(f"Note {t.name} is out of date, updating.")
                await m.edit(embed=embed, content=None, view=view)

    @commands.Cog.listener()
    async def on_ready(self):
        self.update_notes.start()

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        """
        Event listener for when a new thread is created.

        Args:
            thread (discord.Thread): The created thread.
        """
        if thread.parent.id in await util.get_forum_channels(thread.guild):
            self.logger.info(f"New thread in forum: {thread.parent.name}, {thread.name}")
            m = await thread.send("Welcome to the thread! This message will be updated when I receive information from "
                                  "the database!")
            settings = await util.get_settings(thread.guild)
            try:
                defaultNote = settings["defaultNote"][str(thread.parent.id)]
            except KeyError:
                defaultNote = settings["defaultNote"]["default"]
            async with aiosqlite.connect(self.bot.db_location) as db:
                await db.execute("INSERT INTO threads (thread_id, channel_id, note, note_id, note_last_update) VALUES "
                                 "(?, ?, ?, ?, ?);", (thread.id, thread.parent.id, defaultNote, m.id,
                                                      util.time_since_epoch()))
                await db.commit()
            await self.update_notes()

    @commands.Cog.listener()
    async def on_thread_delete(self, thread):
        """
        Event listener for when a thread is deleted.

        Args:
            thread (discord.Thread): The deleted thread.
        """
        if thread.parent.id in await util.get_forum_channels(thread.guild):
            self.logger.warning(f"Thread deleted: {thread.name}")
            async with aiosqlite.connect(self.bot.db_location) as db:
                await db.execute("DELETE FROM threads WHERE thread_id = ?", (thread.id,))
                await db.commit()
            await self.update_notes()

    @commands.Cog.listener()
    async def on_message(self, message):
        """
        Event listener for when a message is sent.

        Args:
            message (discord.Message): The message that was sent.
        """
        try:
            message.channel.parent.id # Are we inside a thread?
        except AttributeError:
            return

        if message.channel.parent.id in await util.get_forum_channels(message.guild):
            note = await util.get_note_message(message.channel)
            deleted = False
            c = 0
            messages = 0
            found_bot = False
            for m in await message.channel.history(limit=20).flatten():
                if m.author.id == self.bot.user.id:
                    found_bot = True
                    if c == 0:
                        break
                    if m.id != note.id:
                        await m.delete()
                    deleted = True
                else:
                    messages += 1
                c += 1
            if (deleted or not found_bot) and messages > 10:
                await message.channel.send("Jump to note", view=JumpButton(note.jump_url))

    @forum.command(name="setup", description="Set up a channel as a forum channel to track")
    @option(name="channel", description="The channel to set up", required=True, channel=True)
    async def setup_forum(self, ctx: discord.ApplicationContext, channel: discord.ForumChannel):
        """
        Set up a channel as a forum channel to track.

        Args:
            ctx (discord.ApplicationContext): The context of the command.
            channel (discord.ForumChannel): The channel to set up.
        """
        if not await util.has_permission(ctx.author.id, "manage_threads", self.bot.db_location) or \
                not ctx.author.guild_permissions.manage_channels:
            await ctx.respond("You do not have permission to manage threads", ephemeral=True)
            return
        forum_channels = await util.get_forum_channels(ctx.guild)
        if channel.id in forum_channels:
            await ctx.respond("This channel is already set up as a forum channel", ephemeral=True)
            return
        forum_channels.append(channel.id)
        async with aiosqlite.connect(self.bot.db_location) as db:
            await db.execute("UPDATE guilds SET thread_channels = ? WHERE guild_id = ?",
                             (",".join(map(str, forum_channels)), ctx.guild.id))
            await db.commit()
        await ctx.respond(f"Channel {channel.name} has been set up as a forum channel", ephemeral=True)

    @forum.command(name="note", description="Modify the note for a forum thread")
    async def note(self, ctx: discord.ApplicationContext):
        """
        Modify the note for a forum thread.

        Args:
            ctx (discord.ApplicationContext): The context of the command.
        """
        try:
            if ctx.channel.parent.id not in await util.get_forum_channels(ctx.guild):
                await ctx.respond("This command can only be used in a forum post!", ephemeral=True, delete_after=5)
                return
        except AttributeError:
            await ctx.respond("This command can only be used in a forum post!", ephemeral=True, delete_after=5)
            return
        note = await util.get_note(ctx.channel, replace_tags=False)
        # Check if the user is the owner of the thread or has permissions
        if ctx.author.id != ctx.channel.owner_id and not await util.has_permission(ctx.author.id,
                                                                                   "manage_threads",
                                                                                   self.bot.db_location):
            await ctx.respond("You do not have permission to edit this note!", ephemeral=True, delete_after=5)
            return
        modal = NoteModal(title=f"Edit note for {ctx.channel.parent.name}", note=note[0] if note else "No note found",
                          db_location=self.bot.db_location)
        await ctx.send_modal(modal)

    @forum.command(name="default_note", description="Change the default note for a forum channel")
    async def default_note(self, ctx: discord.ApplicationContext, channel: discord.ForumChannel):
        """
        Change the default note for a forum channel.

        Args:
            ctx (discord.ApplicationContext): The context of the command.
            channel (discord.ForumChannel): The channel to change the default note for.
        """
        settings = await util.get_settings(ctx.guild)
        try:
            defaultNote = settings["defaultNote"][channel.id]
        except KeyError:
            defaultNote = settings["defaultNote"]["default"]
        modal = DefaultNoteModal(title=util.limit(f"Edit default note for {channel.name}", 45),
                                 note=defaultNote, db_location=self.bot.db_location, channel_id=channel.id)
        await ctx.send_modal(modal)

    @forum.command(name="update", description="Update the note for all forum threads")
    async def update(self, ctx: discord.ApplicationContext):
        """
        Update the note for all forum threads.

        Args:
            ctx (discord.ApplicationContext): The context of the command.
        """
        await ctx.defer()
        await self.update_notes()
        await ctx.respond("Notes updated!", ephemeral=True, delete_after=5)

    @forum.command(name="close", description="Close a forum thread")
    async def close(self, ctx: discord.ApplicationContext):
        """
        Close a forum thread.

        Args:
            ctx (discord.ApplicationContext): The context of the command.
        """
        if ctx.channel.parent.id not in await util.get_forum_channels(ctx.guild):
            await ctx.respond("This command can only be used in a forum post!", ephemeral=True, delete_after=5)
            return
        if ctx.author.id != ctx.channel.owner_id and (not await util.has_permission(ctx.author.id,
                                                                                    "manage_threads",
                                                                                    self.bot.db_location) or
                                                      not ctx.author.guild_permissions.manage_channels):
            await ctx.respond("You do not have permission to close this thread!", ephemeral=True, delete_after=5)
            return
        await ctx.respond("Thread closed!", ephemeral=True, delete_after=5)
        await ctx.channel.edit(archived=True, locked=True,
                               name=f"🔒 {ctx.channel.name} (Closed)",
                               reason=f"Closed by {ctx.author.name}")


def setup(bot):
    """
    Set up the Threads cog.

    Args:
        bot (commands.Bot): The bot instance.
    """
    bot.add_cog(Threads(bot, bot.logger))
