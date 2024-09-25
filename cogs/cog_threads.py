import asyncio
import datetime
import json
import logging
import re
from copy import copy
import discord
from discord import option
from discord.ext import commands, tasks
from discord.ext.pages import Paginator
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
        await interaction.followup.send("✔ `Note updated!`", ephemeral=True, delete_after=5)
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
        await interaction.followup.send("✔ `Default note has been modified!`", ephemeral=True, delete_after=15,
                                        embed=em)
        return True


class EditNoteButtonView(discord.ui.View):
    def __init__(self, permitted_users, db_location, bot=None, logger=None):
        super().__init__()
        self.bot = bot
        self.logger = logger
        self.permitted_users = permitted_users
        self.db_location = db_location

    @discord.ui.button(label="Edit Note", style=discord.ButtonStyle.primary, custom_id="button_edit_note")
    async def button_edit_note(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.permitted_users = await util.get_all_allowed_users(interaction.channel)
        if interaction.user.id not in self.permitted_users:
            await interaction.respond("❌ `You do not have permission to edit this note!`", ephemeral=True)
            return
        note = await util.get_note(interaction.channel, replace_tags=False)
        modal = NoteModal(title=util.limit(f"Edit note for {interaction.channel.name}", 45),
                          note=note[0] if note else "No note found",
                          db_location=util.get_db_location())
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Assign User", style=discord.ButtonStyle.primary, custom_id="button_assign_user")
    async def button_assign_user(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.permitted_users = await util.get_all_allowed_users(interaction.channel)
        if interaction.user.id not in self.permitted_users:
            await interaction.respond("❌ `You do not have permission to assign users to this thread!`", ephemeral=True)
            return
        guild_members = copy(interaction.guild.members)
        await interaction.respond("Assign a user to this thread", view=UserSelectAssignView(
            guild_members, self.db_location, interaction.followup,
            await utils.get_thread_assigned_users(interaction.channel), self.bot, self.logger), ephemeral=True)


class UserSelectAssignView(discord.ui.View):
    def __init__(self, users, db_location, followup, assigned, bot=None, logger=None):
        super().__init__()
        self.bot = bot
        self.logger = logger
        self.users = users
        self.db_location = db_location
        self.followup = followup
        select = discord.ui.Select(placeholder="Select a user to assign", options=self.build_assign_choices(assigned),
                                   min_values=1, max_values=len(self.build_assign_choices()))
        select.callback = self.select_assign_user
        self.add_item(select)

    def build_assign_choices(self, assigned=None):
        if assigned is None:
            assigned = []
        choices = []
        for user in self.users:
            # if user.id not already assigned
            if user.id not in assigned:
                choices.append(discord.SelectOption(label=user.name, value=str(user.id)))
            else:
                choices.append(discord.SelectOption(label=f"(Already Assigned) {user.name}", value=str(user.id)))
        return choices

    async def select_assign_user(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # get all assigned users selected by the user
        selected_users = interaction.data["values"]
        added = 0
        removed = 0
        assigned = await utils.get_thread_assigned_users(interaction.channel)
        for selected_user in selected_users:
            user = interaction.guild.get_member(int(selected_user))
            if user.id in assigned:
                assigned.remove(user.id)
                # dm the user that they have been removed
                if not await utils.safe_send(user,
                                             f"❌ `You have been unassigned from the \"{interaction.channel.name}\" thread by {interaction.user.name}`"):
                    self.logger.warning(f"Failed to send message to {user.name}")
                removed += 1
            else:
                assigned.append(user.id)
                if not await utils.safe_send(user, f"✔ `You have been assigned to the \"{interaction.channel.name}\" "
                                                   f"thread by {interaction.user.name}`\n[Click here to view the "
                                                   f"thread]({interaction.channel.jump_url})"):
                    self.logger.warning(f"Failed to send message to {user.name}")
                added += 1
        async with aiosqlite.connect(self.db_location) as db:
            await db.execute("UPDATE threads SET assigned_discord_ids = ? WHERE thread_id = ?",
                             (json.dumps(assigned), interaction.channel.id))
            await db.commit()
        await interaction.delete_original_response()
        if added == 0 and removed == 0:
            await interaction.followup.send("❌ `No changes made`", ephemeral=True)
        elif len(selected_users) == 1:
            await interaction.followup.send(
                f"✔ `{'Assigned' if added else 'Unassigned'} "
                f"{interaction.guild.get_member(int(selected_users[0])).name} {'to' if added else 'from'} the thread`",
                ephemeral=True)
        else:
            await interaction.followup.send(
                f"✔ `Assigned {added} user(s) and unassigned {removed} user(s) from the thread`",
                ephemeral=True)
        note = await util.get_note(interaction.channel)
        m = await interaction.channel.fetch_message(note[2])
        await m.edit(content=None, embed=await util.build_forum_embed(interaction.channel), view=EditNoteButtonView(
            await util.get_all_allowed_users(interaction.channel), self.db_location, self.bot, self.logger))
        return True


async def build_thread_choices(ctx: discord.AutocompleteContext):
    """
    Build the choices for the thread autocomplete. The autocomplete will show forum channel in the current guild.

    Args:
        ctx (discord.AutocompleteContext): The context of the command.

    Returns:
        list: The list of choices.
    """
    forum_channels = await util.get_forum_channels(ctx.interaction.guild)
    choices = []
    for channel_id in forum_channels:
        choices.append(ctx.interaction.guild.get_channel(channel_id))
    return choices


class ThreadsCog(commands.Cog):
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
        self.WARNING_COOLDOWN_MESSAGE = None

    forum = discord.SlashCommandGroup(name="forum", description="Commands for managing forum posts")
    assign = forum.create_subgroup(name="assign", description="Commands for assigning users to forum posts.")

    @tasks.loop(minutes=5)
    async def update_notes(self, channel=None):
        """
        Periodically update the notes for all threads.
        """
        await self.bot.wait_until_ready()
        async with aiosqlite.connect(self.bot.db_location) as db:
            if channel:
                async with db.execute("SELECT thread_id, note_id FROM threads WHERE channel_id = ?",
                                      (channel.id,)) as cursor:
                    threads = await cursor.fetchall()
            else:
                async with db.execute("SELECT thread_id, note_id FROM threads") as cursor:
                    threads = await cursor.fetchall()
        for thread in threads:
            t = self.bot.get_channel(thread[0])
            if not t:
                self.logger.warning(f"Thread {thread[0]} not found, deleting from database.")
                async with aiosqlite.connect(self.bot.db_location) as db:
                    await db.execute("DELETE FROM threads WHERE thread_id = ?", (thread[0],))
                    await db.commit()
                continue
            else:
                try:
                    m = await t.fetch_message(thread[1])
                except discord.errors.NotFound:
                    self.logger.warning(f"Note message {thread[1]} not found, deleting from database.")
                    async with aiosqlite.connect(self.bot.db_location) as db:
                        await db.execute("DELETE FROM threads WHERE thread_id = ?", (thread[0],))
                        await db.commit()
                    continue
                embed = await util.build_forum_embed(t)
                try:
                    if embed.description == m.embeds[0].description:
                        self.logger.info(f"Note for {t.name} is up to date, refreshing the buttons.")
                        await m.edit(view=EditNoteButtonView(
                            await util.get_all_allowed_users(t), self.bot.db_location, self.bot, self.logger))
                        continue
                except IndexError:
                    pass
                self.logger.info(f"Note {t.name} is out of date, updating.")
                await m.edit(embed=embed, content=None, view=EditNoteButtonView(
                    await util.get_all_allowed_users(t), self.bot.db_location, self.bot, self.logger))

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
        if message.author == self.bot.user:
            print("Ignoring bot message")
            return

        try:
            message.channel.parent.id  # Are we inside a thread?
        except AttributeError:
            return

        if message.channel.parent.id in await util.get_forum_channels(message.guild):
            self.logger.info(f"Trying to find note with an ID of {message.channel.id}")
            note = await util.get_note_message(message.channel)
            self.logger.info(f"Returned note: {note}")
            # The message’s creation time in UTC.
            if note is not None:
                note_sent = note.created_at.timestamp()
            else:
                note_sent = 0
            if note_sent < (datetime.datetime.utcnow() - datetime.timedelta(hours=24)).timestamp():
                new_note = await message.channel.send(embed=await util.build_forum_embed(message.channel),
                                                      view=EditNoteButtonView(
                                                          await util.get_all_allowed_users(message.channel),
                                                          self.bot.db_location, self.bot, self.logger))
                async with aiosqlite.connect(self.bot.db_location) as db:
                    await db.execute("UPDATE threads SET note_id = ?, note_last_update = ? WHERE thread_id = ?",
                                     (new_note.id, util.time_since_epoch(), message.channel.id))
                    await db.commit()

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        """
        Event listener for when a thread is updated.

        Args:
            before (discord.Thread): The thread before the update.
            after (discord.Thread): The thread after the update.
        """
        if after.parent.id in await util.get_forum_channels(after.guild):
            self.logger.info(f"Thread updated: {after.name}")
            if self.WARNING_COOLDOWN_MESSAGE is not None and (
                    after.name.replace("🔒 ", "").replace(" (Locked)", "") == before.name.replace("🔒 ", "").replace(
                    " (Locked)", "") or
                    after.name == before.name):
                await self.WARNING_COOLDOWN_MESSAGE.delete()
                self.WARNING_COOLDOWN_MESSAGE = None
            if before.locked and not after.locked:
                t = await utils.safe_unlock_thread(after, True)
                if t.upper() != "OK":
                    self.logger.warning(f"Failed to rename {after.name} (Rate limited {t.split(':')[1]})")
                    # create a task to rename the thread after the rate limit is lifted
                    try:
                        await self.rename_after_cooldown.start(after, after.name.replace("🔒 ", "")
                                                               .replace(" (Locked)", ""))
                    except RuntimeError:
                        self.logger.warning("Rate limit task already running.")
                # remove the locked tag from the thread if it is present
                for tag in after.applied_tags:
                    if re.match(utils.get_config("AUTO_LOCK_REGEX"), tag.name):
                        after.applied_tags.remove(tag)
                        self.logger.info(f"Tag {tag.name} removed due to thread unlocked.")
                await after.edit(applied_tags=after.applied_tags)
            if before.applied_tags != after.applied_tags:
                self.logger.info(f"Discord tags updated for {after.name}")
                # Modify the note to reflect the new discord tags applied to the post
                # if any tag that matches the regex os.getenv("AUTO_LOCK_REGEX") is applied, lock the thread
                if any([re.match(utils.get_config("AUTO_LOCK_REGEX"), tag.name) for tag in after.applied_tags]):
                    t = await utils.safe_lock_thread(after, True)
                    if t.upper() != "OK":
                        self.logger.warning(f"Failed to rename {after.name} (Rate limited {t.split(':')[1]})")
                        # create a task to rename the thread after the rate limit is lifted
                        try:
                            await self.rename_after_cooldown.start(after, after.name.replace("🔒 ", "")
                                                                   .replace(" (Locked)", ""))
                        except RuntimeError:
                            self.logger.warning("Rate limit task already running.")
                    self.logger.info(f"Thread {after.name} locked due to tag application.")
                else:
                    t = await utils.safe_unlock_thread(after, True)
                    if t.upper() != "OK":
                        self.logger.warning(f"Failed to rename {after.name} (Rate limited {t.split(':')[1]})")
                        # create a task to rename the thread after the rate limit is lifted
                        try:
                            await self.rename_after_cooldown.start(after, after.name.replace("🔒 ", "")
                                                                    .replace(" (Locked)", ""))
                        except RuntimeError:
                            self.logger.warning("Rate limit task already running.")
                    self.logger.info(f"Thread {after.name} unlocked due to tag removal.")

    @tasks.loop()
    async def rename_after_cooldown(self, thread: discord.Thread, name: str):
        """
        Rename a thread after the rate limit is lifted.

        Args:
            name (str): The new name for the thread.
            thread (discord.Thread): The thread to rename.
        """
        can_rename = await utils.can_rename(thread)
        # time since epoch when the rate limit will be lifted, as float
        future_timestamp = datetime.datetime.now() + datetime.timedelta(seconds=int(can_rename[1]))
        self.WARNING_COOLDOWN_MESSAGE = await thread.send(f"⚠️ `The thread will be renamed to {name} `"
                                                          f"{utils.to_discord_timestamp(future_timestamp.timestamp(), 'R')}` due "
                                                          f"to a rate limit`")
        # start a loop to break when the rate limit is lifted
        while not can_rename[0]:
            can_rename = await utils.can_rename(thread)
            self.logger.info(f"Rate limited! {can_rename[1]} seconds left.")
            if can_rename[0]:
                break
            await asyncio.sleep(can_rename[1] if can_rename[1] < 60 else 60)
        await self.WARNING_COOLDOWN_MESSAGE.edit(content=f"✔ `The thread will be renamed to {name} soon due to a rate "
                                                         f"limit`")
        await thread.edit(name=name)
        return

    @forum.command(name="setup", description="Set up a channel as a forum channel to track")
    @option(name="channel", description="The channel to set up", required=True, channel=True,
            autocomplete=build_thread_choices)
    async def setup_forum(self, ctx: discord.ApplicationContext, channel: discord.ForumChannel):
        """
        Set up a channel as a forum channel to track.

        Args:
            ctx (discord.ApplicationContext): The context of the command.
            channel (discord.ForumChannel): The channel to set up.
        """
        if not await util.has_permission(ctx, "manage_threads", self.bot.db_location) or \
                not ctx.author.guild_permissions.manage_channels:
            await ctx.respond("❌ `You do not have permission to manage threads`", ephemeral=True)
            return
        forum_channels = await util.get_forum_channels(ctx.guild)
        if channel.id in forum_channels:
            await ctx.respond("❌ `This channel is already set up as a forum channel`", ephemeral=True)
            return
        forum_channels.append(channel.id)
        async with aiosqlite.connect(self.bot.db_location) as db:
            await db.execute("UPDATE guilds SET thread_channels = ? WHERE guild_id = ?",
                             (",".join(map(str, forum_channels)), ctx.guild.id))
            await db.commit()
        await ctx.respond(f"✔ `Channel {channel.name} has been set up as a forum channel!`", ephemeral=True)

    @forum.command(name="note", description="Modify the note for a forum thread")
    async def note(self, ctx: discord.ApplicationContext):
        """
        Modify the note for a forum thread.

        Args:
            ctx (discord.ApplicationContext): The context of the command.
        """
        try:
            if ctx.channel.parent.id not in await util.get_forum_channels(ctx.guild):
                await ctx.respond("❌ `This command can only be used in a forum post!`", ephemeral=True, delete_after=5)
                return
        except AttributeError:
            await ctx.respond("❌ `This command can only be used in a forum post!`", ephemeral=True, delete_after=5)
            return
        note = await util.get_note(ctx.channel, replace_tags=False)
        if ctx.author.id != ctx.channel.owner_id and not await util.has_permission(ctx,
                                                                                   "manage_threads",
                                                                                   self.bot.db_location):
            await ctx.respond("❌ `You do not have permission to edit this note!`", ephemeral=True, delete_after=5)
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
        if not await util.has_permission(ctx, "manage_threads", self.bot.db_location) or \
                not ctx.author.guild_permissions.manage_channels:
            await ctx.respond("❌ `You do not have permission to manage threads`", ephemeral=True)
            return

        settings = await util.get_settings(ctx.guild)
        try:
            defaultNote = settings["defaultNote"][channel.id]
        except KeyError:
            defaultNote = settings["defaultNote"]["default"]
        modal = DefaultNoteModal(title=util.limit(f"Edit default note for {channel.name}", 45),
                                 note=defaultNote, db_location=self.bot.db_location, channel_id=channel.id)
        await ctx.send_modal(modal)

    @forum.command(name="refresh", description="Refresh the note for all forum threads")
    @option(name="channel", description="The channel to refresh notes for", required=False, channel=True,
            autocomplete=build_thread_choices)
    async def update(self, ctx: discord.ApplicationContext, channel: discord.ForumChannel = None):
        """
        Update the note for all forum threads.

        Args:
            ctx (discord.ApplicationContext): The context of the command.
            channel (discord.ForumChannel): The channel to refresh notes for. If None, refresh all notes.
        """
        await ctx.defer()
        await self.update_notes(channel)
        await ctx.respond("✔ `Notes refreshed!`", ephemeral=True, delete_after=5)

    @forum.command(name="close", description="Close a forum thread")
    async def close(self, ctx: discord.ApplicationContext):
        """
        Close a forum thread.

        Args:
            ctx (discord.ApplicationContext): The context of the command.
        """
        if ctx.channel.parent.id not in await util.get_forum_channels(ctx.guild):
            await ctx.respond("❌ `This command can only be used in a forum post!`", ephemeral=True, delete_after=5)
            return
        if ctx.author.id != ctx.channel.owner_id and (not await util.has_permission(ctx,
                                                                                    "manage_threads",
                                                                                    self.bot.db_location) or
                                                      not ctx.author.guild_permissions.manage_channels):
            await ctx.respond("❌ `You do not have permission to close this thread!`", ephemeral=True, delete_after=5)
            return
        await ctx.respond("✔ `Thread closed!`", ephemeral=True, delete_after=5)
        await ctx.channel.edit(locked=True, name=f"🔒 {ctx.channel.name} (Closed)")

    ######
    # Assign Commands

    @assign.command(name="add", description="Assign a user to a forum thread")
    @option(name="user", description="The user to assign", required=True)
    @option(name="thread", description="The thread to assign the user to", required=True)
    async def assign_add(self, ctx: discord.ApplicationContext, user: discord.Member, thread: discord.Thread):
        """
        Assign a user to a forum thread.

        Args:
            ctx (discord.ApplicationContext): The context of the command.
            user (discord.Member): The user to assign.
            thread (discord.Thread): The thread to assign the user to.
        """
        if ctx.author.id != thread.owner_id and not await util.has_permission(ctx, "manage_threads",
                                                                              self.bot.db_location):
            await ctx.respond("❌ `You do not have permission to assign users to threads!`", ephemeral=True,
                              delete_after=5)
            return
        assigned = await utils.get_thread_assigned_users(thread)
        if user.id in assigned:
            await ctx.respond(f"❌ `User {user.name} is already assigned to this thread`", ephemeral=True)
            return
        assigned.append(user.id)
        async with aiosqlite.connect(self.bot.db_location) as db:
            await db.execute("UPDATE threads SET assigned_discord_ids = ? WHERE thread_id = ?",
                             (json.dumps(assigned), thread.id))
            await db.commit()
        await ctx.respond(f"✔ `User {user.name} has been assigned to thread {thread.name}`", ephemeral=True)

    @assign.command(name="remove", description="Remove a user from a forum thread")
    @option(name="user", description="The user to remove", required=True)
    @option(name="thread", description="The thread to remove the user from", required=True)
    async def assign_remove(self, ctx: discord.ApplicationContext, user: discord.Member, thread: discord.Thread):
        """
        Remove a user from a forum thread.

        Args:
            ctx (discord.ApplicationContext): The context of the command.
            user (discord.Member): The user to remove.
            thread (discord.Thread): The thread to remove the user from.
        """
        if ctx.author.id != ctx.channel.owner_id and not await util.has_permission(ctx, "manage_threads",
                                                                                   self.bot.db_location):
            await ctx.respond("❌ `You do not have permission to assign users to threads!`", ephemeral=True,
                              delete_after=5)
            return
        async with aiosqlite.connect(self.bot.db_location) as db:
            async with db.execute("SELECT assigned_discord_ids FROM threads WHERE thread_id = ?",
                                  (thread.id,)) as cursor:
                assigned = await cursor.fetchone()
            if not assigned:
                await ctx.respond("❌ `No users assigned to this thread`", ephemeral=True)
                return
            assigned = json.loads(assigned[0])
            if user.id not in assigned:
                await ctx.respond(f"❌ `User {user.name} is not assigned to this thread`", ephemeral=True)
                return
            assigned.remove(user.id)
            await db.execute("UPDATE threads SET assigned_discord_ids = ? WHERE thread_id = ?",
                             (json.dumps(assigned), thread.id))
            await db.commit()
        await ctx.respond(f"✔ `User {user.name} has been removed from thread {thread.name}`", ephemeral=True)

    @assign.command(name="list", description="List all users assigned to a forum thread")
    @option(name="thread", description="The thread to list users for", required=True)
    async def assign_list(self, ctx: discord.ApplicationContext, thread: discord.Thread):
        """
        List all users assigned to a forum thread.

        Args:
            ctx (discord.ApplicationContext): The context of the command.
            thread (discord.Thread): The thread to list users for.
        """
        if ctx.author.id != thread.owner_id and not await util.has_permission(ctx, "manage_threads",
                                                                              self.bot.db_location):
            await ctx.respond("❌ `You do not have permission to assign users to threads!`", ephemeral=True,
                              delete_after=5)
            return
        assigned = await utils.get_thread_assigned_users(thread)
        users = [ctx.guild.get_member(user) for user in assigned]
        users = [{"name": user.name, "value": f"Mention: {user.mention}"} for user in users if user]
        limit = 10
        embed_data = {
            "title": f"Assigned users to thread {thread.name}",
            "description": f"There are {len(users)} user(s) to show ({limit} per page)."
        }
        pages = utils.paginator(items=users, embed_data=embed_data, per_page=limit)
        try:
            page_iterator = Paginator(pages=pages, loop_pages=True)
        except TypeError:
            await ctx.respond("❌ `No users assigned to this thread.`", ephemeral=True)
            return
        await page_iterator.respond(ctx.interaction)


def setup(bot):
    """
    Set up the Threads cog.

    Args:
        bot (commands.Bot): The bot instance.
    """
    bot.add_cog(ThreadsCog(bot, bot.logger))
