import json
import os
import aiosqlite as sqlite
import discord
import datetime

DEFAULT_SETTINGS = {"defaultNote": "Hello! This space can be used to keep notes about the current project in this "
                                   "thread. To edit this note please use the `/forum note` command."}


def convert_permission(permissions: str | dict) -> dict | str:
    """
    Convert a string of permissions to a dictionary of permissions with the key being the permission name and the value
    being the permission value.
    :param permissions: Either a string or dictionary of permissions
    :return: The opposite type of permissions is returned.
    """
    if isinstance(permissions, str):
        perm_dict = {
            "manage_local_permissions": False,
            "manage_embeds": False,
            "manage_threads": False
        }
        print(f"permissions: {permissions}")
        if permissions == "" or permissions is None:
            return perm_dict
        if "MNG_PERM" in permissions:
            perm_dict["manage_local_permissions"] = True
        if "MNG_EMB" in permissions:
            perm_dict["manage_embeds"] = True
        if "MNG_THR" in permissions:
            perm_dict["manage_threads"] = True
        return perm_dict
    elif isinstance(permissions, dict):
        perm_string = ""
        if permissions["manage_local_permissions"]:
            perm_string += "MNG_PERM"
        if permissions["manage_embeds"]:
            perm_string += "MNG_EMB"
        if permissions["manage_threads"]:
            perm_string += "MNG_THR"
        return perm_string
    else:
        raise TypeError("Permissions must be a string or a dictionary")


async def has_permission(user_id: int, permission: str, database_location: str) -> bool:
    """
    Check if a user has a specific permission
    :param database_location: The location of the database
    :param user_id: The user ID to check
    :param permission: The permission to check
    :return: True if the user has the permission, False otherwise
    """
    async with sqlite.connect(database_location) as db:
        async with db.execute("SELECT permissions FROM users WHERE user_id = ?", (user_id,)) as cursor:
            permissions = await cursor.fetchone()
    permissions = convert_permission(permissions[0])
    return permissions[permission]


async def get_forum_channels(guild: discord.Guild):
    """
    Get all the forum channels in a guild
    :param guild: The guild to check
    :return: A list of forum channels' ids
    """
    forum_channels = []
    async with sqlite.connect(os.getenv('DATABASE_LOCATION')) as db:
        async with db.execute("SELECT thread_channels FROM guilds WHERE guild_id = ?", (guild.id,)) as cursor:
            thread_channels = await cursor.fetchone()
    if thread_channels:
        thread_channels = thread_channels[0]
        try:
            for channel in thread_channels.split(","):
                forum_channels.append(int(channel))
        except ValueError:
            # there are no channels in the database
            pass
    else:
        async with sqlite.connect(os.getenv('DATABASE_LOCATION')) as db:
            await db.execute("INSERT INTO guilds (guild_id, settings, thread_channels) VALUES (?, ?, ?)",
                             (guild.id, "", ""))
            await db.commit()
    return forum_channels


def time_since_epoch():
    """
    Get the time since epoch
    :return: The time since epoch
    """
    return datetime.datetime.now().timestamp()


async def get_note(thread: discord.Thread):
    """
    Get the note for a thread
    :param thread: The thread to get the note for
    :return: The note for the thread
    """
    async with sqlite.connect(os.getenv('DATABASE_LOCATION')) as db:
        async with db.execute("SELECT note, note_last_update, note_id FROM threads WHERE thread_id = ?",
                              (thread.id,)) as cursor:
            note = await cursor.fetchone()
    if note:
        return note[0], note[1], note[2]
    else:
        return None


def to_discord_timestamp(timestamp: int):
    """
    Convert a timestamp to a discord timestamp
    :param timestamp: The timestamp to convert
    :return: The discord timestamp
    """
    return f"<t:{round(timestamp)}:f>"


async def build_forum_embed(thread: discord.Thread = None, note: str = None):
    """
    Build an embed for a forum post
    :param note: The note to use for the embed
    :param thread: The thread to build the embed for if note is None
    :return: The embed
    """
    # get note information from the database
    if note is None and thread is not None:
        note = await get_note(thread)
    elif thread is None:
        note = (note, time_since_epoch(), None)
    else:
        raise ValueError("You must provide either a thread or a note")
    embed = discord.Embed(title="📝 Notes", description=note[0], color=0x17e670)
    try:
        embed.add_field(name=f"Last updated",
                        value=f"{to_discord_timestamp(note[1]) if note[1] is not None else 'an unknown time'}")
    except TypeError:
        embed.set_footer(text="Last updated at an unknown time. Please check the database.")
    return embed


def is_forum_post(ctx, thread: discord.Thread):
    """
    Check if a thread is a forum post
    :param ctx: The context of the command
    :param thread: The thread to check
    :return: True if the thread is a forum post, False otherwise
    """
    forum_channels = get_forum_channels(ctx.guild)
    return thread.id in forum_channels


async def get_settings(guild: discord.Guild):
    """
    Get the settings for a guild
    :param guild: The guild to get the settings for
    :return: The settings for the guild
    """
    async with sqlite.connect(os.getenv('DATABASE_LOCATION')) as db:
        async with db.execute("SELECT settings FROM guilds WHERE guild_id = ?", (guild.id,)) as cursor:
            settings = await cursor.fetchone()
            if settings is None:
                await db.execute("INSERT INTO guilds (guild_id, settings, thread_channels) VALUES (?, ?, ?)",
                                 (guild.id, json.dumps(DEFAULT_SETTINGS), ""))
                await db.commit()
            return json.loads(settings[0]) if settings[0] != "" or settings[0] is None else DEFAULT_SETTINGS
