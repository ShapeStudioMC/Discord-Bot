# VERSION: 0.0.5
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
from pprint import pprint
import discord
import dotenv
import os
import logging
from discord.ext import commands
import sqlite3
import pymysql as sql
import utils

# ✔ ❌
# Check if debug.log exists and clear it if it exceeds 1MiB
if os.path.exists("debug.log"):
    print(
        f"debug.log exists, size: {os.path.getsize('debug.log')} bytes > 1MiB? "
        f"{os.path.getsize('debug.log') > 1048576}")
    if os.path.getsize("debug.log") > 1048576:
        os.remove("debug.log")
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

# Get the bot token from the environment
TOKEN = os.getenv('DISCORD_TOKEN')

# Set up bot intents
intents = discord.Intents.default().all()
bot = commands.AutoShardedBot(intents=intents, debug_guilds=[1242097337837289472,])
bot.logger = logger
bot.db_location = os.getenv('DATABASE_LOCATION')

# Load all cogs (extensions) from the cogs directory
for filename in os.listdir('./cogs'):
    if filename.endswith('.py') and filename.startswith('cog_'):
        bot.load_extension(f'cogs.{filename[:-3]}')
        logger.info(f'Loaded {filename[:-3]}')


def process_migration(mysql_files: str) -> list:
    out = ""
    for line in mysql_files.split(";"):
        if "sqlite_" in line:
            continue
        if "BEGIN TRANSACTION" in line:
            continue
        if "(" in line:
            t = line.strip().split("(", 1)
            out += t[0].replace('"', '`', 2)+" ("+t[1]+";\n"
        elif "VALUES" in line:
            t = line.strip().split("VALUES", 1)
            out += t[0].replace('"', '`', 2)+"VALUES "+t[1]+";\n"
        elif "DELETE FROM" in line:
            out += line.strip().replace('"', '`', 2)+";\n"
        else:
            if line.strip() == "":
                continue
            out += line.strip()+";\n"
    out = [" ".join(x.split())+";" for x in out.split(";\n") if x.strip() != ""]
    for i in range(len(out)):
        cmd = out[i]
        if " guild_id INT" in cmd:
            cmd = cmd.replace("guild_id INT", "guild_id BIGINT").replace("EGER", "")
        if " user_id INT" in cmd:
            cmd = cmd.replace("user_id INT", "user_id BIGINT").replace("EGER", "")
        if "AUTOINCREMENT" in cmd or "autoincrement" in cmd:
            cmd = cmd.replace("AUTOINCREMENT", "AUTO_INCREMENT").replace("autoincrement", "AUTO_INCREMENT")
        if out[i] != cmd:
            out[i] = cmd
    return out

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
    # Attempt to connect to the MySQL database
    try:
        database = sql.connect(
            host=os.getenv('DATABASE_HOST'),
            user=os.getenv('DATABASE_USER'),
            password=os.getenv('DATABASE_PASSWORD'),
            database=os.getenv('DATABASE_NAME')
        )
    except sql.Error as e:
        logger.error(f"Error connecting to database: {e}")
        raise e
    logger.info("Connected to MySQL database")


    if database.open and os.getenv("DATABASE_LOCATION") is not None:
        logging.warning("SQLite database present and MySQL database connected, attempting to migrate!")
        print(
            "\n\n! ! !\n\nWe are connected to MySQL database, but a SQLite database is also present!\nExit now to "
            "stop automatic migration to MySQL\n\n! ! !\n\n")
        time.sleep(10)
        logging.info("Creating sqlite dump")
        with sqlite3.connect(os.getenv("DATABASE_LOCATION")) as con:
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [table for table in cur.fetchall() if not table[0].startswith("sqlite_")]
        with sqlite3.connect(os.getenv("DATABASE_LOCATION")) as con:
            with open('dump.sql', 'w') as f:
                for line in con.iterdump():
                    f.write('%s\n' % line)
                    print(line)
        print("\nPlease check the dump.sql file to ensure it is correct.\nWait 15 seconds!")
        time.sleep(15)
        logging.info("Sending dump to MySQL database")
        with open('dump.sql', 'r') as f:
            lines = f.readlines()
        lines = process_migration("".join(lines))
        with database.cursor() as cur:
            command = ""
            success = 0
            error = 0
            for line in lines:
                command += line
                if ";" in line and not command.count("'") % 2:
                    logger.debug(f"Executing: {command}")
                    try:
                        cur.execute(command)
                    except sql.Error as e:
                        logging.error(f"Error executing command: {e}")
                        logging.error(f"Command: {command}")
                        error += 1
                    else:
                        success += 1
                    command = ""
        database.commit()
        logging.info(f"Migration complete! {success/(success+error)*100}% success rate!")
        logging.info("Dump sent")
        os.environ.pop("DATABASE_LOCATION")
        with open('.env', "r") as f:
            lines = f.readlines()
        with open('.env', "w") as f:
            for line in lines:
                if "DATABASE_LOCATION" in line:
                    continue
                f.write(line)
        logging.info("Removed DATABASE_LOCATION from .env")
        logging.info("Migration complete")
    logging.info("Update Check")
    update = utils.check_update(logging)
    if update is not False:
        logging.warning(f"Update available! Local version: {update['local']}, Remote version: {update['remote']}")
        time.sleep(10)
    else:
        logger.info(f"You are up to date! Version: {utils.get_version()}")
    logging.info("Sanity check on the database")
    with database.cursor() as c:
        c.execute(f"CREATE TABLE IF NOT EXISTS `{os.getenv('EMBEDS_TABLE')}` ( embed_id INT not null primary key, data TEXT not null,"
                  f" guild_id BIGINT not null, name TEXT not null unique, settings TEXT );")
        c.execute(f"CREATE TABLE IF NOT EXISTS `{os.getenv('USERS_TABLE')}` "
                  f"( user_id BIGINT not null primary key AUTO_INCREMENT, permissions TEXT );")
        c.execute(f"CREATE TABLE IF NOT EXISTS `{os.getenv('GUILDS_TABLE')}` "
                  f"( guild_id BIGINT not null primary key, settings TEXT, thread_channels TEXT );")
        c.execute(f"CREATE TABLE IF NOT EXISTS `{os.getenv('THREADS_TABLE')}` "
                  f"(thread_id BIGINT PRIMARY KEY NOT NULL,channel_id BIGINT NOT NULL, note TEXT, note_id BIGINT, "
                  f"note_last_update BIGINT, assigned_discord_ids TEXT);")
        database.commit()
    database.close()
    logging.info("Starting bot")
    bot.run(TOKEN, reconnect=True)
