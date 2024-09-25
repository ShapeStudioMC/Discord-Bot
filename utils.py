import json
import os
import re
from imp import get_tag
from typing import Any, Dict, Coroutine

import aiosqlite as sqlite
import discord
import datetime
import dotenv
import requests

# Load environment variables from .env
dotenv.load_dotenv()

# Default settings for the bot
DEFAULT_SETTINGS = {
    "defaultNote": {"default": os.getenv('MASTER_NOTE')},
    "discordTags": {},
    "lastRename": {}
}

# Tags used in the notes
TAGS = ["<DATE_OPENED>", "<LAST_UPDATED>", "<THREAD_NAME>", "<THREAD_POSTER_MENTION>", "<THREAD_POSTER_USERNAME>",
        "<EDIT_PERMISSIONS_LIST>", "<ASSIGNED_LIST>"]
CODE_BLOCK_CHAR = "`"

HEX_REGEX = r"^(?:[0-9a-fA-F]{3}){1,2}$"


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


async def has_permission(ctx: discord.ApplicationContext, permission: str, database_location: str) -> bool:
    """
    Check if a user has a specific permission

    :param database_location: The location of the database
    :param ctx: The context of the command
    :param permission: The permission to check
    :return: True if the user has the permission, False otherwise
    """
    try: # discord.ApplicationContext
        user_id = ctx.author.id
    except AttributeError: # discord.Interaction
        user_id = ctx.user.id
    print(f"User ID: {user_id}")
    try:
        if ctx.channel:
            users = await get_thread_assigned_users(ctx.channel)
            if user_id in users:
                return True
    except AttributeError:
        pass
    if str(user_id) in os.getenv('BYPASS_PERMISSIONS'):
        return True

    async with sqlite.connect(database_location) as db:
        async with db.execute("SELECT permissions FROM users WHERE user_id = ?", (user_id,)) as cursor:
            permissions = await cursor.fetchone()
    try:
        permissions = convert_permission(permissions[0])
    except TypeError:
        async with sqlite.connect(database_location) as db:
            await db.execute("INSERT INTO users (user_id, permissions) VALUES (?, ?)", (user_id, ""))
            await db.commit()
            permissions = convert_permission("")
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


async def get_note(thread: discord.Thread, replace_tags: bool = True):
    """
    Get the note for a thread

    :param replace_tags: Replace tags in the note
    :param thread: The thread to get the note for
    :return: The note for the thread
    """
    async with sqlite.connect(os.getenv('DATABASE_LOCATION')) as db:
        async with db.execute("SELECT note, note_last_update, note_id FROM threads WHERE thread_id = ?",
                              (thread.id,)) as cursor:
            note = await cursor.fetchone()
    if note:
        if replace_tags:
            text = await render_text(note[0], thread)
            return text, note[1], note[2]
        else:
            return note[0], note[1], note[2]
    else:
        return None


def to_discord_timestamp(timestamp: int | float, type: str = "f"):
    """
    Convert a timestamp to a discord timestamp

    :param timestamp: The timestamp to convert
    :param type: The type of timestamp to convert to
    :return: The discord timestamp
    """
    return f"<t:{round(timestamp)}:{type}>"


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
    try:
        embed = discord.Embed(title="📝 Notes", description=note[0], color=discord.Color.blue())
    except TypeError:
        embed = discord.Embed(title="📝 Notes",
                              description="An error occurred while trying to get the note. Please check the database.",
                              color=discord.Color.red())
    try:
        embed.add_field(name=f"Assigned to",
                        value=f"{', '.join([f'<@{user}>' for user in await get_thread_assigned_users(thread)]) if await get_thread_assigned_users(thread) else 'No one has been assigned.'}",
                        inline=True)
    except TypeError:
        embed.add_field(name=f"Assigned to", value="No one has been assigned.", inline=True)
    embed.add_field(name=f"Created",
                    value=f"by {thread.owner.mention} at {to_discord_timestamp(thread.created_at.timestamp())}")
    try:
        embed.add_field(name=f"Last updated",
                        value=f"{to_discord_timestamp(note[1]) if note[1] is not None else 'an unknown time'}")
    except TypeError:
        embed.add_field(name=f"Last updated",
                        value=f"Last updated at an unknown time. Please check the database.")
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


def limit(string: str, limit: int):
    """
    Limit the length of a string

    :param string: The string to limit
    :param limit: The limit of the string
    :return: The limited string
    """
    if len(string) > limit:
        return string[:limit - 3] + "..."
    return string


def get_db_location():
    """
    Get the database location from environment variables

    :return: The database location
    """
    return os.getenv('DATABASE_LOCATION')


async def render_text(text: str, thread: discord.Thread):
    """
    Render text with database variables, tags should only be replaced when they are outside of code blocks.

    :param thread: The thread to render the text for
    :param text: The text to render
    :return: The rendered text
    """
    text_ar = list(text)
    inside_code_block = False

    ###################################
    # If it ain't broke, don't fix it #
    ###################################

    for i, char in enumerate(text_ar):
        if char == CODE_BLOCK_CHAR:
            inside_code_block = not inside_code_block
        if not inside_code_block:
            if "".join(text_ar[i:i + len(TAGS[0])]) == TAGS[0]:  # Date opened
                text_ar[i:i + len(TAGS[0])] = str(to_discord_timestamp(thread.created_at.timestamp()))
            elif "".join(text_ar[i:i + len(TAGS[1])]) == TAGS[1]:  # LAST_UPDATED
                note = await get_note(thread, False)
                text_ar[i:i + len(TAGS[1])] = str(to_discord_timestamp(note[1]))
            elif "".join(text_ar[i:i + len(TAGS[2])]) == TAGS[2]:  # THREAD_NAME
                text_ar[i:i + len(TAGS[2])] = thread.name
            elif "".join(text_ar[i:i + len(TAGS[3])]) == TAGS[3]:  # THREAD_POSTER_MENTION
                text_ar[i:i + len(TAGS[3])] = thread.owner.mention
            elif "".join(text_ar[i:i + len(TAGS[4])]) == TAGS[4]:  # THREAD_POSTER_USERNAME
                text_ar[i:i + len(TAGS[4])] = thread.owner.display_name
            elif "".join(text_ar[i:i + len(TAGS[5])]) == TAGS[5]:  # EDIT_PERMISSIONS_LIST
                assigned_users = await get_all_allowed_users(thread)
                assigned_users = [f"<@{user}>" for user in assigned_users] if assigned_users else [
                    "No one can edit this note."]
                text_ar[i:i + len(TAGS[5])] = ", ".join(assigned_users)
            elif "".join(text_ar[i:i + len(TAGS[6])]) == TAGS[6]:  # ASSIGNED_LIST
                assigned_users = await get_thread_assigned_users(thread)
                assigned_users = [f"<@{user}>" for user in assigned_users] if assigned_users else [
                    "No one has been assigned."]
                text_ar[i:i + len(TAGS[6])] = ", ".join(assigned_users)
    return "".join(text_ar)


def check_update(logger=None):
    """
    Check if the bot needs to update

    :param logger: Optional logger to log messages
    :return: True if the bot needs to update, False otherwise
    """
    with open("main.py") as f:
        first_line = f.readline()
        local_version = int("".join(filter(str.isdigit, first_line)))
    url = os.getenv('RAW_REPO_URL') + f"/main.py" if os.getenv('RAW_REPO_URL')[-1] != "/" else os.getenv(
        'RAW_REPO_URL') + "main.py"
    response = requests.get(url)
    if response.status_code == 200:
        if "import" in response.text.split("\n")[0]:
            if logger:
                logger.error("UTILS: Failed to check for updates: The first line of the remote file contains an import "
                             "statement.")
            else:
                print(f"UTILS: Failed to check for updates: The first line of the remote file does not contain the "
                      f"version number.")
            return False
        try:
            remote_version = int("".join(filter(str.isdigit, response.text.split("\n")[0])))
        except ValueError:
            if logger:
                logger.error("UTILS: Failed to parse remote version! (ValueError)")
            else:
                print("UTILS: Failed to parse remote version! (ValueError)")
            return False
        if remote_version > local_version:
            return {"remote": remote_version, "local": local_version}
        if remote_version < local_version:
            if logger:
                logger.warning(f"UTILS: Local version is ahead of remote version: Local: {local_version}, "
                               f"Remote: {remote_version}")
            else:
                print(f"UTILS: Local version is ahead of remote version: Local: {local_version}, Remote: "
                      f"{remote_version}")
    else:
        if logger:
            logger.error(f"UTILS: Failed to check for updates: {response.status_code}")
        else:
            print(f"UTILS: Failed to check for updates: {response.status_code}")
    return False


def get_version():
    """
    Get the version of the bot from the first line of main.py

    :return: The version of the bot
    """
    with open("main.py") as f:
        first_line = f.readline()
        return int("".join(filter(str.isdigit, first_line)))


async def get_note_message(thread: discord.Thread):
    """
    Get the note message for a thread, returning the message

    :param ctx: The context of the command
    :param thread: The thread to get the note message for
    :return: discord.Message
    """
    # call the database to find the note message ID
    async with sqlite.connect(os.getenv('DATABASE_LOCATION')) as db:
        async with db.execute("SELECT note_id FROM threads WHERE thread_id = ?", (thread.id,)) as cursor:
            note_message_id = await cursor.fetchone()
    if note_message_id:
        note_message_id = note_message_id[0]
        note_message = await thread.fetch_message(note_message_id)
        return note_message
    else:
        return None


async def convert_embed_to_JSON(embed: discord.Embed):
    """
    Convert an embed to JSON

    :param embed: The embed to convert
    :return str: The JSON representation of the embed
    """
    return str(json.dumps(embed.to_dict()))


def is_color(color: str | discord.Color):
    """
    Check if a color is a valid discord.Color

    :param color: The color to check
    :return: True if the color is valid, False otherwise
    """
    if isinstance(color, discord.Color):
        return color
    try:
        return discord.Color(value=int(color, 16))
    except ValueError | TypeError:
        pass
    if re.match(HEX_REGEX, color):
        return discord.Color(value=int(color, 16))
    return False


async def get_thread_assigned_users(thread: discord.Thread):
    """
    Get the users assigned to a thread

    :param thread: The thread to get the assigned users for
    :return list: The assigned users
    """
    async with sqlite.connect(os.getenv('DATABASE_LOCATION')) as db:
        async with db.execute("SELECT assigned_discord_ids FROM threads WHERE thread_id = ?", (thread.id,)) as cursor:
            assigned_users = await cursor.fetchone()
    if assigned_users:
        try:
            return json.loads(assigned_users[0])
        except TypeError:
            async with sqlite.connect(os.getenv('DATABASE_LOCATION')) as db:
                await db.execute("UPDATE threads SET assigned_discord_ids = ? WHERE thread_id = ?",
                                 (json.dumps([]), thread.id))
                await db.commit()
            return []
    return []


async def store_thread_assigned_users(thread: discord.Thread, assigned_users: list):
    """
    Store the assigned users for a thread

    :param thread: The thread to store the assigned users for
    :param assigned_users: The users to store
    """
    async with sqlite.connect(os.getenv('DATABASE_LOCATION')) as db:
        await db.execute("UPDATE threads SET assigned_discord_ids = ? WHERE thread_id = ?",
                         (json.dumps(assigned_users), thread.id))
        await db.commit()
    return


def paginator(items, embed_data, per_page=10, hard_limit=100, author: discord.User = None):
    """This function builds a complete list of embeds for the paginator.
    Args:
        items (list): The list of items to paginate.
        embed_data (dict): The data for the embeds.
        author (discord.User): The author of the embeds.
        per_page (int): The amount of items per page.
        hard_limit (int): The hard limit of pages.
    Returns:
        list: A list of embeds for the paginator.
    """
    pages = []
    # Split the list into chunks of 10
    chunks = [items[i:i + per_page] for i in range(0, len(items), per_page)]
    # Check if the amount of chunks is larger than the hard limit
    if len(chunks) > hard_limit:
        # If it is, then we will just return the first 100 pages
        chunks = chunks[:hard_limit]
    # Loop through the chunks
    index = 1
    for chunk in chunks:
        # Create a new embed
        embed = discord.Embed(**embed_data)
        embed.title = embed_data['title']
        embed.description = embed_data['description']
        embed.set_footer(text=f"Page {index}/{len(chunks)}")
        # set Description
        if author:
            embed.set_author(name=author.name, icon_url=author.avatar.url, url=author.jump_url)
        # Add the items to the embed
        for item in chunk:
            embed.add_field(name=f"{index}. {item['name']}",
                            value=f"{item['value']}",
                            inline=False)
            index += 1
        # Add the embed to the pages
        pages.append(embed)
    return pages


async def get_all_allowed_users(thread: discord.Thread):
    """
    Get all the users allowed to edit a thread's note

    :param ctx: The context of the command
    :param thread: The thread to get the allowed users for
    :return: The allowed users
    """
    allowed_users = [thread.owner.id]  # add the thread owner
    allowed_users += [int(user) for user in os.getenv("BYPASS_PERMISSIONS").split(",")]  # add all bypass permissions
    allowed_users += await get_thread_assigned_users(thread)  # get all users assigned to the thread
    return list(dict.fromkeys(allowed_users))  # remove duplicates


def get_current_date():
    """
    Get the current date

    :return tuple: The current date in the format (year, month, day, hour, minute, second)
    """
    return datetime.datetime.now().timetuple()[:6]


def months():
    return ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
            "November", "December"]


async def safe_send(user: discord.User | discord.Member, message: str):
    """
    Send a message to a user safely

    :param user: The user to send the message to
    :param message: The message to send
    """
    try:
        await user.send(message)
        return True
    except discord.errors.Forbidden:
        return False


def get_config(key: str) -> str:
    """
    Get an environment variable

    :param key: The key of the environment variable
    :return: The value of the environment variable as a string
    """
    return str(os.getenv(key))


async def safe_lock_thread(thread: discord.Thread, rename: bool = False):
    """
    Lock a thread

    :param thread: The thread to lock
    :param rename: Whether to rename the thread
    """
    settings = await get_settings(thread.guild)
    out = "OK"
    # check if thread was last renamed more than 5 minutes ago
    if str(thread.id) in settings["lastRename"]:
        if time_since_epoch() - int(settings["lastRename"][str(thread.id)]) < 300:
            out = f"cooldown:{time_since_epoch() - settings['lastRename'][str(thread.id)]}"
            rename = False
    else:
        settings["lastRename"][str(thread.id)] = time_since_epoch()
        async with sqlite.connect(get_db_location()) as db:
            await db.execute("UPDATE guilds SET settings = ? WHERE guild_id = ?",
                             (json.dumps(settings), thread.guild.id))
            await db.commit()
    if rename:
        await thread.edit(name=f"🔒 {thread.name} (Locked)", locked=True)
        settings["lastRename"][str(thread.id)] = time_since_epoch()
        async with sqlite.connect(get_db_location()) as db:
            await db.execute("UPDATE guilds SET settings = ? WHERE guild_id = ?",
                             (json.dumps(settings), thread.guild.id))
            await db.commit()
        return out
    else:
        await thread.edit(locked=True)
        return out


async def safe_unlock_thread(thread: discord.Thread, rename: bool = False):
    """
    Unlock a thread

    :param thread: The thread to unlock
    :param rename: Whether to rename the thread
    :return: The outcome of the operation, either "OK" or "cooldown:<time>"
    """
    settings = await get_settings(thread.guild)
    out = "OK"
    # check if thread was last renamed more than 5 minutes ago
    if str(thread.id) in settings["lastRename"].keys():
        if time_since_epoch() - int(settings["lastRename"][str(thread.id)]) < 300:
                out = f"cooldown:{time_since_epoch() - settings['lastRename'][str(thread.id)]}"
                rename = False
    else:
        settings["lastRename"][str(thread.id)] = time_since_epoch()
        async with sqlite.connect(get_db_location()) as db:
            await db.execute("UPDATE guilds SET settings = ? WHERE guild_id = ?",
                             (json.dumps(settings), thread.guild.id))
            await db.commit()
    if rename:
        await thread.edit(name=thread.name.replace("🔒 ", "").replace(" (Locked)", ""), locked=False)
        settings["lastRename"][str(thread.id)] = time_since_epoch()
        async with sqlite.connect(get_db_location()) as db:
            await db.execute("UPDATE guilds SET settings = ? WHERE guild_id = ?",
                             (json.dumps(settings), thread.guild.id))
            await db.commit()
        return out
    else:
        await thread.edit(locked=False)
        return out


async def can_rename(thread):
    """
    Check if a thread can be renamed based on the cooldown.

    :param thread: The thread to check
    :return tuple: A tuple containing a boolean value and when the thread can be renamed again
    """
    settings = await get_settings(thread.guild)
    if str(thread.id) in settings["lastRename"]:
        if time_since_epoch() - int(settings["lastRename"][str(thread.id)]) < 300:
            # return False and when the time when the thread can be renamed again
            return False, 300 - (time_since_epoch() - int(settings["lastRename"][str(thread.id)]))
    return True, -1

