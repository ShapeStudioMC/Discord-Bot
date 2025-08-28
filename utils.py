import json
import logging
import os
import re
from logging import exception
from pprint import pprint
import time
import pymysql as sql
import discord
import datetime
import dotenv
import pymysql.err
import requests

# Load environment variables from .env
dotenv.load_dotenv()

# Default settings for the bot
DEFAULT_SETTINGS = {
    "defaultNote": {"default": os.getenv('DEFAULT_NOTE')},
    "discordTags": {},
    "lastRename": {}
}

# Tags used in the notes
TAGS = ["<DATE_OPENED>", "<LAST_UPDATED>", "<THREAD_NAME>", "<THREAD_POSTER_MENTION>", "<THREAD_POSTER_USERNAME>",
        "<EDIT_PERMISSIONS_LIST>", "<ASSIGNED_LIST>"]
CODE_BLOCK_CHAR = "`"

HEX_REGEX = r"^(?:[0-9a-fA-F]{3}){1,2}$"


class SQLManager:
    def __init__(self):
        """
        Initialize the SQLManager with a connection to the database.
        """
        self.connection = None
        self.cursor = None

    def __is_connected(self):
        """
        Check if the connection to the database is still open.
        """
        if self.connection is None:
            return False
        try:
            self.connection.ping(reconnect=True)
            return True
        except sql.OperationalError:
            return False

    def __connect(self):
        """
        Reconnect to the database if the connection is closed.
        """
        if not self.__is_connected():
            self.connection = sql.connect(
                host=os.getenv('DATABASE_HOST'),
                user=os.getenv('DATABASE_USER'),
                password=os.getenv('DATABASE_PASSWORD'),
                database=os.getenv('DATABASE_NAME')
            )
            self.cursor = self.connection.cursor()


    def __enter__(self):
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.connection.commit()
        self.cursor.close()
        self.connection.close()

    def execute(self, *args, **kwargs):
        if not self.__is_connected():
            self.__connect()
        self.wait_for_connection()

        try:
            self.cursor.execute(*args, **kwargs)
        except pymysql.err.ProgrammingError as e:
            # if the cursor is closed, reopen it
            pprint(e.args)
            if "Cursor closed" in e.args[1]:
                print("Cursor closed! Attempting to reopen cursor.")
                self.cursor = self.connection.cursor()
                self.cursor.execute(*args, **kwargs)
            else:
                raise e
        except Exception as e:
            raise e

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def commit(self):
        self.connection.commit()

    def close(self):
        self.cursor.close()
        self.connection.close()
        self.connection = None
        self.cursor = None

    def wait_for_connection(self):
        """
        Wait for the connection to the database to be established.
        This is useful for ensuring that the connection is open before executing any queries.
        """
        while not self.__is_connected():
            print("Waiting for database connection...")
            try:
                self.__connect()
            except Exception as e:
                print(f"Waiting for database connection: {e}")
                time.sleep(1)

# Create an instance of the SQLManager class to use for database connections
SQLManager = SQLManager()


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


async def has_permission(ctx: discord.ApplicationContext, permission: str) -> bool:
    """
    Check if a user has a specific permission

    :param ctx: The context of the command
    :param permission: The permission to check
    :return: True if the user has the permission, False otherwise
    """
    try:  # discord.ApplicationContext
        user_id = ctx.author.id
    except AttributeError:  # discord.Interaction
        user_id = ctx.user.id
    try:
        if ctx.channel:
            users = await get_thread_assigned_users(ctx.channel)
            if user_id in users:
                return True
    except AttributeError:
        pass
    if str(user_id) in os.getenv('BYPASS_PERMISSIONS'):
        return True

    SQLManager.execute(f"SELECT permissions FROM {table('users')} WHERE user_id = %s", (user_id,))
    permissions = SQLManager.fetchone()
    try:
        permissions = convert_permission(permissions[0])
    except TypeError:
        SQLManager.execute(f"INSERT INTO {table('users')} (user_id, permissions) VALUES (%s, %s)", (user_id, ""))
        SQLManager.commit()
        permissions = convert_permission("")
    return permissions[permission]


async def get_forum_channels(guild: discord.Guild):
    """
    Get all the forum channels in a guild

    :param guild: The guild to check
    :return: A list of forum channels' ids
    """
    forum_channels = []
    SQLManager.execute(f"SELECT thread_channels FROM {table('guilds')} WHERE guild_id = %s", (guild.id,))
    thread_channels = SQLManager.fetchone()
    if thread_channels:
        thread_channels = thread_channels[0]
        try:
            for channel in thread_channels.split(","):
                forum_channels.append(int(channel))
        except ValueError:
            pass
    else:
        SQLManager.execute(f"INSERT INTO {table('guilds')} (guild_id, settings, thread_channels) VALUES (%s, %s, %s)",
                           (guild.id, "", ""))
        SQLManager.commit()
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
    SQLManager.execute(f"SELECT note, note_last_update, note_id FROM {table('threads')} WHERE thread_id = %s",
                       (thread.id,))
    note = SQLManager.fetchone()
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


async def get_settings(guild: discord.Guild, logger: logging.Logger = None):
    """
    Get the settings for a guild

    :param guild: The guild to get the settings for
    :return: The settings for the guild
    """
    SQLManager.execute(f"SELECT settings FROM {table('guilds')} WHERE guild_id = %s", (guild.id,))
    settings = SQLManager.fetchone()
    if settings is None:
        SQLManager.execute(f"INSERT INTO {table('guilds')} (guild_id, settings, thread_channels) VALUES (%s, %s, %s)",
                           (guild.id, json.dumps(DEFAULT_SETTINGS), ""))
        SQLManager.commit()
    # attempt to load the json.
    try:
        obj_settings = json.loads(settings[0])
    except json.JSONDecodeError:
        logger.warning("Corrupt settings found for guild, creating new settings.")
        SQLManager.execute(f"UPDATE {table('guilds')} SET settings = %s WHERE guild_id = %s",
                           (json.dumps(DEFAULT_SETTINGS), guild.id))
        SQLManager.commit()
        return DEFAULT_SETTINGS
    return obj_settings if settings[0] != "" or settings[0] is None else DEFAULT_SETTINGS


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
    SQLManager.execute(f"SELECT note_id FROM {table('threads')} WHERE thread_id = %s", (thread.id,))
    note_message_id = SQLManager.fetchone()
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
    SQLManager.execute(f"SELECT assigned_discord_ids FROM {table('threads')} WHERE thread_id = %s", (thread.id,))
    assigned_users = SQLManager.fetchone()
    if assigned_users:
        try:
            return json.loads(assigned_users[0])
        except TypeError:
            SQLManager.execute(f"UPDATE {table('threads')} SET assigned_discord_ids = %s WHERE thread_id = %s",
                               (json.dumps([]), thread.id))
            SQLManager.commit()
            return []
    return []


async def store_thread_assigned_users(thread: discord.Thread, assigned_users: list):
    """
    Store the assigned users for a thread

    :param thread: The thread to store the assigned users for
    :param assigned_users: The users to store
    """
    SQLManager.execute(f"UPDATE {table('threads')} SET assigned_discord_ids = %s WHERE thread_id = %s",
                       (json.dumps(assigned_users), thread.id))
    SQLManager.commit()
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
    if user.bot:
        return True
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
        SQLManager.execute(f"UPDATE {table('guilds')} SET settings = %s WHERE guild_id = %s",
                           (json.dumps(settings), thread.guild.id))
        SQLManager.commit()
    if rename:
        await thread.edit(name=f"🔒 {thread.name} (Locked)", locked=True, archived=True)
        settings["lastRename"][str(thread.id)] = time_since_epoch()
        SQLManager.execute(f"UPDATE {table('guilds')} SET settings = %s WHERE guild_id = %s",
                           (json.dumps(settings), thread.guild.id))
        SQLManager.commit()
        return out
    else:
        await thread.edit(locked=True, archived=True)
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
        SQLManager.execute(f"UPDATE {table('guilds')} SET settings = %s WHERE guild_id = %s",
                           (json.dumps(settings), thread.guild.id))
        SQLManager.commit()
    if rename:
        await thread.edit(name=thread.name.replace("🔒 ", "").replace(" (Locked)", ""), locked=False, archived=False)
        settings["lastRename"][str(thread.id)] = time_since_epoch()
        SQLManager.execute(f"UPDATE {table('guilds')} SET settings = %s WHERE guild_id = %s",
                           (json.dumps(settings), thread.guild.id))
        SQLManager.commit()
        return out
    else:
        await thread.edit(locked=False, archived=False)
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
            return False, 300 - (time_since_epoch() - int(settings["lastRename"][str(thread.id)]))
    return True, -1


# with db_connector() as db:
def db_connector():
    """
    Get a database connection

    :return: A database connection
    """
    return SQLManager


def table(t: str):
    """
    Get the table name for a certain type

    :param t: The type of table to get
    :return: The table name
    """
    t = t.lower()
    if t == "users":
        return os.getenv("USERS_TABLE") if os.getenv("USERS_TABLE") else "users"
    elif t == "guilds":
        return os.getenv("GUILDS_TABLE") if os.getenv("GUILDS_TABLE") else "guilds"
    elif t == "threads":
        return os.getenv("THREADS_TABLE") if os.getenv("THREADS_TABLE") else "threads"
    elif t == "embeds":
        return os.getenv("EMBEDS_TABLE") if os.getenv("EMBEDS_TABLE") else "embeds"
    else:
        raise ValueError("Invalid type")


def to_json(data: dict | list):
    """
    Convert a dictionary to JSON

    :param data: The dictionary to convert
    :return: The JSON representation of the dictionary
    """
    return json.dumps(data)


def from_json(data: str):
    """
    Convert a JSON string to a dictionary

    :param data: The JSON string to convert
    :return: The dictionary representation of the JSON string
    """
    return json.loads(data)


def convert_to_dict(cls: object):
    """
    Convert an object to a dictionary

    :param cls: The object to convert
    :return: The dictionary representation of the object
    """
    return cls.__dict__


def get_bot_info(bot: discord.bot):
    """
    Return dictionary of bot information

    :param bot: The bot to get information for
    :return: Dictionary of bot information
    """
    return {
        "user": bot.user,
        "guilds": len(bot.guilds),
        "shards": bot.shard_count,
        "shard_id": bot.shard_id,
        "shard_info": bot.get_shard(bot.shard_id)
    }


def sort_guilds(bot: discord.bot):
    """
    Sort the guilds by date of joining, with the oldest guilds first. If DEFAULT_GUILD is set, it will be first.

    :param bot: The bot to sort the guilds for
    :return: The sorted guilds
    """
    guilds = bot.guilds
    guilds.sort(key=lambda x: x.me.joined_at)
    if os.getenv("DEFAULT_GUILD"):
        guilds.insert(0, bot.get_guild(int(os.getenv("DEFAULT_GUILD"))))
    guilds = list(dict.fromkeys(guilds))
    return guilds


async def process_job(job: dict, bot: discord.bot, logger):
    """
    Main subrutine for processing jobs

    :param job: The job to process
    :param bot: The bot to use
    :return bool: True if the job was processed successfully, False otherwise
    """
    logger.debug(f"Start processing job: {job}")
    try:
        if job["endpoint"] == "update-user-roles":
            guilds = sort_guilds(bot)
            user = job["data"]["discord_username"]
            new_roles = job["data"]["new_roles"]
            for guild in guilds:
                member = guild.get_member_named(user)
                if member:
                    # Remove all roles except @everyone
                    roles_to_remove = [role for role in member.roles if role.name != "@everyone"]
                    if roles_to_remove:
                        await member.remove_roles(*roles_to_remove, reason="Received job - update roles (remove old roles)")
                        logger.info(f"Removed old roles from {member.name} in {guild.name}")
                    # Add new roles
                    added_roles = []
                    for role_name in new_roles:
                        role = discord.utils.get(guild.roles, name=role_name)
                        if role:
                            await member.add_roles(role, reason=f"Received job - update roles")
                            logger.info(f"Added role {role.name} to {member.name} in {guild.name}")
                            added_roles.append(role.name)
                        else:
                            logger.warning(f"Role {role_name} not found in {guild.name}")
                    # Notify webapp
                    notify_roles_updated(member.id, added_roles)
                    return True
                else:
                    logger.warning(f"User {user} not found in {guild.name}")
        if job["endpoint"] == "NEXT_JOB":
            ...
    except Exception as e:
        logger.error(f"Error processing job: {e}")
        return False
    finally:
        logger.debug(f"Finished processing job")


def notify_username_changed(discord_id, old_username, new_username):
    """
    Notify the webapp that a username has changed.
    """
    url = "https://shapestudio.net/api/username-changed"
    payload = {
        "discord_id": discord_id,
        "old_username": old_username,
        "new_username": new_username
    }
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
    except Exception as e:
        logging.error(f"Failed to notify username change: {e}")


def notify_roles_updated(discord_id, new_roles):
    """
    Notify the webapp that a user's roles have been updated.
    """
    url = "https://shapestudio.net/api/update-user-roles"
    payload = {
        "discord_id": discord_id,
        "new_roles": new_roles
    }
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
    except Exception as e:
        logging.error(f"Failed to notify roles update: {e}")


def send_bot_channel_message(guild, message, bot):
    """
    Send a message in the bot channel of the given guild.
    """
    # Try to find a channel named 'bot' or 'bot-commands', fallback to system_channel
    channel = discord.utils.get(guild.text_channels, name="bot")
    if not channel:
        channel = discord.utils.get(guild.text_channels, name="bot-commands")
    if not channel:
        channel = guild.system_channel
    if channel:
        return bot.loop.create_task(channel.send(message))
    else:
        logging.warning(f"No bot channel found in guild {guild.name}")
        return None


def is_debug():
    """
    Check if the bot is running in debug mode

    :return: True if the bot is running in debug mode, False otherwise
    """
    return os.getenv("DEBUG", "false").lower() == "true"


def get_git_commit_hash():
    """
    Get the current git commit hash
    :return dictionary: The commit hash, with the key as the branch name
    """
    branches = {}
    git_heads_path = os.path.join(".git", "refs", "heads")
    if not os.path.exists(git_heads_path):
        return branches
    for branch in os.listdir(git_heads_path):
        with open(os.path.join(git_heads_path, branch)) as f:
            branches[branch] = f.read().strip()
    return branches

