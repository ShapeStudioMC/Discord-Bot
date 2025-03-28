import os
import signal
from datetime import datetime
from pprint import pprint
from discord.ext import commands, tasks
import logging
import utils


class WebConnectorCog(commands.Cog):
    def __init__(self, bot, logger):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.handlers = logger.handlers
        self.logger.setLevel(logger.level)
        self.logger.propagate = False
        self.bot = bot

        self.logger.info("Attempting to hook signal handlers")
        try:
            self.bot.loop.add_signal_handler(signal.SIGINT, self.on_shutdown)
            self.bot.loop.add_signal_handler(signal.SIGTERM, self.on_shutdown)
        except NotImplementedError:
            self.logger.warning("Signal handlers not implemented on this platform! Trying atexit")
            import atexit
            atexit.register(self.on_shutdown)
        self.logger.debug("Signal handlers hooked")
        self.logger.info(f"Starting check jobs loop, interval: {str(utils.get_config('JOB_INTERVAL'))}")
        self.check_jobs.start()

        # Cache for users, to prevent unnecessary discord calls. (user_id: username + discriminator)
        self.cache = {}
        if os.path.exists("cache.json"):
            with open("cache.json", "r") as f:
                self.cache = utils.from_json(f.read())

        self.sync_cache.start()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.bot.wait_until_ready()
        if len(self.cache.keys()) == 0:
            await self.build_cache()
            self.logger.info(f"Built cache from discord!")
            self.logger.info(f"Cache: {self.cache}")
        else:
            self.logger.info("Cache loaded from file!")
        self.logger.info(f"Found {len(self.cache.keys())} guilds in cache.")
        self.logger.info(f"WebConnectorCog loaded")

    def on_shutdown(self):
        self.logger.info("Freezing cache!")
        with open("cache.json", "w") as f:
            f.write(utils.to_json(self.cache))
        self.logger.info("Shutting down WebConnectorCog")

    async def build_cache(self):
        for guild in utils.sort_guilds(self.bot):
            self.logger.info(f"Connected to {guild.name}")
            users = await guild.fetch_members().flatten()
            if guild.id not in self.cache:
                self.cache[guild.id] = {
                    "users": {},
                    "roles": {}
                }
            for user in users:
                self.cache[guild.id]["users"][user.id] = {
                    "username": user.name,
                    "discriminator": user.discriminator,
                    # list of role ids (preserve order)
                    "roles": [role.id for role in user.roles]
                }

            for role in guild.roles:
                self.cache[guild.id]["roles"][role.id] = {
                    "name": role.name
                }

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.roles != after.roles:  # If roles have changed
            self.logger.info(f"{before} roles changed from {before.roles} to {after.roles}")
            # update cache
            try:
                self.cache[after.guild.id]["users"][after.id]["roles"] = [role.id for role in after.roles]
            except KeyError:
                self.logger.warning(f"KeyError: {after.guild.id} not in cache, building cache")
                await self.build_cache()
                self.cache[after.guild.id]["users"][after.id]["roles"] = [role.id for role in after.roles]
        # if username changed
        if before.name != after.name:
            self.logger.info(f"{before} username changed from {before.name} to {after.name}")
            self.cache[after.guild.id]["users"][after.id]["username"] = after.name
        # if discriminator changed
        if before.discriminator != after.discriminator:
            self.logger.info(f"{before} discriminator changed from {before.discriminator} to {after.discriminator}")
            self.cache[after.guild.id]["users"][after.id]["discriminator"] = after.discriminator

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        print("guild updated")
        if before.roles != after.roles:
            self.logger.info(f"{before} roles changed from {before.roles} to {after.roles}")
            settings = await utils.get_settings(after)
            pprint(settings)

    @tasks.loop(seconds=int(utils.get_config("JOB_INTERVAL")))
    async def check_jobs(self):
        db = utils.db_connector()
        db.execute("SELECT * FROM jobs WHERE jobs.process_id = %s AND jobs.status = %s;",
                   (utils.get_config("JOB_BOT_NAME"), "pending"))
        db.commit()  # Ensure the SELECT statement is committed
        jobs = db.fetchall()
        jobs = sorted(jobs, key=lambda x: (x[4], x[5]))
        if len(jobs) > 0:
            await self.bot.wait_until_ready()
            for job in jobs:
                self.logger.info(f"Processing job id {job[0]}")
                status = await utils.process_job(utils.from_json(job[2]), self.bot, self.logger)
                if status:
                    utils.db_connector().execute("UPDATE jobs SET status = %s WHERE id = %s;", ("completed", job[0]))
                    utils.db_connector().commit()
                else:
                    self.logger.error(f"Job {job[0]} failed!")

    def role_convert(self, roleID: int):
        for guild in self.cache:
            if roleID in self.cache[guild]["roles"]:
                return self.cache[guild]["roles"][roleID]["name"]
        return

    @tasks.loop(minutes=5)
    async def sync_cache(self):
        await self.bot.wait_until_ready()
        await self.build_cache()
        for cacheGuildID in self.cache:
            for user in self.cache[cacheGuildID]["users"]:
                t_roles = []
                for role in self.cache[cacheGuildID]["users"][user]["roles"]:
                    t_roles.append(self.role_convert(role))
                if not t_roles:
                    t_roles = []
                utils.db_connector().execute("SELECT * FROM discord_user_roles WHERE userID = %s AND guildID = %s;",
                                             (user, cacheGuildID))
                db_roles = utils.db_connector().fetchall()
                if not db_roles:
                    utils.db_connector().execute("INSERT INTO discord_user_roles (userID, guildID, DiscordRoles, "
                                                 "LastUpdate) VALUES (%s, %s, %s, %s);",
                                                 (user, cacheGuildID, utils.to_json(t_roles), datetime.now()))
                    utils.db_connector().commit()
                else:
                    if db_roles[0][2] != t_roles:
                        utils.db_connector().execute("UPDATE discord_user_roles SET DiscordRoles = %s, LastUpdate "
                                                     "= %s WHERE userID = %s AND guildID = %s;",
                                                     (utils.to_json(t_roles), datetime.now(), user, cacheGuildID))
                        utils.db_connector().commit()
        self.logger.info(f"Cache synced at {datetime.now()}")


def setup(bot):
    bot.add_cog(WebConnectorCog(bot, logging.getLogger('main')))
