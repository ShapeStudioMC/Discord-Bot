# VERSION: 0.0.1
# THIS IS FOR UPDATE CHECKING, DO NOT REMOVE

"""
Main module for the Discord bot.

This file sets up logging, loads environment variables, initializes the bot,
loads extensions (cogs), and defines some bot commands and events.

Written by BEMZlabs for ShapeStudio (@ShapeStudioMC)

Copyright 2024 BEMZlabs for ShapeStudio

This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public 
Licence as published by the Free Software Foundation; either version 2 of the Licence, or (at your option) any later 
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied 
warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public Licence for more details.

You should have received a copy of the GNU General Public Licence along with this program; if not, see 
<https://www.gnu.org/licenses/>.
"""

import time
import discord
import dotenv
import os
import logging
from discord.ext import commands
import sqlite3
import utils

# Check if debug.log exists and clear it if it exceeds 1MiB
if os.path.exists("debug.log"):
    print(
        f"debug.log exists, size: {os.path.getsize('debug.log')} bytes > 1MiB? "
        f"{os.path.getsize('debug.log') > 1048576}")
    if os.path.getsize("debug.log") > 1048576:
        open("debug.log", "w").close()
        print("Cleared debug.log")

# Set up discord's built-in logging
discord_logger = logging.getLogger('discord')
discord_logger.setLevel(logging.DEBUG)  # or INFO
discord_logger.propagate = False

# Set up the main logger
logger = logging.getLogger('main')
logger.setLevel(logging.DEBUG)  # Set logger level
logger.propagate = False

# Create a FileHandler for logging to a file
file_handler = logging.FileHandler('debug.log')
file_handler.setLevel(logging.DEBUG)  # Set handler level

# Create a StreamHandler for logging to STDOUT
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)  # Set handler level

# Create a Formatter for log messages
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Set the Formatter for the handlers
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

# Add the handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

# Add the handlers to the discord logger
discord_logger.addHandler(file_handler)
discord_logger.addHandler(stream_handler)

# Load environment variables from .env file
dotenv.load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Set up bot intents
intents = discord.Intents.default().all()
bot = commands.AutoShardedBot(intents=intents)
bot.logger = logger
bot.db_location = os.getenv('DATABASE_LOCATION')

# Load all cogs (extensions) from the cogs directory
for filename in os.listdir('./cogs'):
    if filename.endswith('.py') and filename.startswith('cog_'):
        bot.load_extension(f'cogs.{filename[:-3]}')
        logger.info(f'Loaded {filename[:-3]}')


@bot.event
async def on_ready():
    logger.info(f"{bot.user} has connected to Discord ({len(bot.guilds)} guilds)!")


@bot.slash_command(name="shard", description="Get the shard ID and info for the current guild")
async def shard(ctx: discord.ApplicationContext):
    """
    Slash command to get shard information for the current guild.

    Args:
        ctx (discord.ApplicationContext): The context of the command.

    Returns:
        None
    """
    shard: discord.ShardInfo = bot.get_shard(ctx.guild.shard_id)
    shard_count: int = shard.shard_count
    shard_ping: float = round(shard.latency * 1000, 1)
    num_servers = len([guild for guild in bot.guilds if guild.shard_id == ctx.guild.shard_id])
    em = discord.Embed(title=f"Shard Info", description=f"Shard ID: {ctx.guild.shard_id}")
    em.add_field(name="Shard Count", value=f"{shard_count}")
    em.add_field(name="Shard Ping", value=f"{shard_ping}ms")
    em.add_field(name="Servers", value=f"{num_servers}")
    em.add_field(name="Total Servers", value=f"{len(bot.guilds)}")
    await ctx.respond(embed=em)


if __name__ == "__main__":
    logging.info("Update Check")
    update = utils.check_update(logging)
    if update is not False:
        logging.warning(f"Update available! Local version: {update['local']}, Remote version: {update['remote']}")
        time.sleep(10)

    logging.info("Sanity check on the database")
    conn = sqlite3.connect(bot.db_location)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS embeds (embed_id INTEGER PRIMARY KEY NOT NULL,"
              "data TEXT NOT NULL, guild_id INT NOT NULL, name TEXT NOT NULL);")
    c.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY NOT NULL,"
              "permissions TEXT);")
    c.execute("CREATE TABLE IF NOT EXISTS guilds (guild_id INTEGER PRIMARY KEY NOT NULL,"
              "settings TEXT, thread_channels TEXT);")
    c.execute("CREATE TABLE IF NOT EXISTS threads (thread_id INTEGER PRIMARY KEY NOT NULL,"
              "channel_id INT NOT NULL, note TEXT, note_id INTEGER, note_last_update INTEGER);")
    conn.commit()
    conn.close()
    logging.info("Starting bot")
    bot.run(TOKEN, reconnect=True)
