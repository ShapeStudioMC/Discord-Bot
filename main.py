# VERSION: 0.0.1
# THIS IS FOR UPDATE CHECKING, DO NOT REMOVE

import time
import discord
import dotenv
import os
import logging
from discord.ext import commands
import sqlite3
import utils

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

# Your existing logger setup
logger = logging.getLogger('main')
logger.setLevel(logging.DEBUG)  # Set logger level
logger.propagate = False

# Create a FileHandler
file_handler = logging.FileHandler('debug.log')
file_handler.setLevel(logging.DEBUG)  # Set handler level

# Create a StreamHandler for STDOUT
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)  # Set handler level

# Create a Formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Set the Formatter for the handlers
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

# Add the handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

discord_logger.addHandler(file_handler)
discord_logger.addHandler(stream_handler)

dotenv.load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default().all()
# bot = commands.AutoShardedBot(intents=intents, debug_guilds=[867773426773262346, 1242097337837289472,
# 410980591476015104])
bot = commands.AutoShardedBot(intents=intents, debug_guilds=[867773426773262346, 1242097337837289472])
bot.logger = logger
bot.db_location = os.getenv('DATABASE_LOCATION')
for filename in os.listdir('./cogs'):
    if filename.endswith('.py') and filename.startswith('cog_'):
        bot.load_extension(f'cogs.{filename[:-3]}')
        logger.info(f'Loaded {filename[:-3]}')


@bot.event
async def on_ready():
    logger.info(f"{bot.user} has connected to Discord ({len(bot.guilds)} guilds)!")


@bot.slash_command(name="shard", description="Get the shard ID and info for the current guild")
async def shard(ctx: discord.ApplicationContext):
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
