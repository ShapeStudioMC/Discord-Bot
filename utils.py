import json
import os
import aiosqlite as sqlite
import discord
import datetime
import dotenv
import requests

DEFAULT_SETTINGS = {
    "defaultNote": {"default": "Hello! This space can be used to keep notes about the current project in this "
                               "thread. To edit this note please use the `/forum note` command. If you would like to"
                               "change what this message says by default please use the `/forum default_note` command."}
}
TAGS = ["<DATE_OPENED>", "<LAST_UPDATED>", "<THREAD_NAME>", "<THREAD_OWNER_MENTION>", "<THREAD_OWNER_USERNAME>"]
CODE_BLOCK_CHAR = "`"

dotenv.load_dotenv()


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


def to_discord_timestamp(timestamp: int | float):
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
    return os.getenv('DATABASE_LOCATION')


async def render_text(text: str, thread: discord.Thread):
    """
    Render text with database variables, tags should only be replaced when they are outside of code blocks.
    :param thread: The thread to render the text for
    :param text: The text to render
    :param database_connection: The database connection to use
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
            if "".join(text_ar[i:i + len(TAGS[0])]) == TAGS[0]:
                # Date opened should be when the thread was created
                text_ar[i:i + len(TAGS[0])] = str(to_discord_timestamp(thread.created_at.timestamp()))
            elif "".join(text_ar[i:i + len(TAGS[1])]) == TAGS[1]:
                note = await get_note(thread, False)
                text_ar[i:i + len(TAGS[1])] = str(to_discord_timestamp(note[1]))
            elif "".join(text_ar[i:i + len(TAGS[2])]) == TAGS[2]:
                text_ar[i:i + len(TAGS[2])] = thread.name
            elif "".join(text_ar[i:i + len(TAGS[3])]) == TAGS[3]:
                text_ar[i:i + len(TAGS[3])] = thread.owner.mention
            elif "".join(text_ar[i:i + len(TAGS[4])]) == TAGS[4]:
                text_ar[i:i + len(TAGS[4])] = thread.owner.display_name
    return "".join(text_ar)


def check_update(logger=None):
    """
    Check if the bot needs to update
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
    with open("main.py") as f:
        first_line = f.readline()
        return int("".join(filter(str.isdigit, first_line)))
