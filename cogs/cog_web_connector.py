import os
import signal
from datetime import datetime
from pprint import pprint
from discord.ext import commands, tasks
import logging
import utils
import time


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
        self.cache_expiry_seconds = 3600  # 1 hour expiry, adjust as needed
        self.cache_timestamp = None
        if os.path.exists("cache.json"):
            with open("cache.json", "r") as f:
                cache_data = utils.from_json(f.read())
                if isinstance(cache_data, dict) and "_timestamp" in cache_data:
                    self.cache = cache_data.get("data", {})
                    self.cache_timestamp = cache_data["_timestamp"]
                else:
                    self.cache = cache_data
                    self.cache_timestamp = None

        self.sync_cache.start()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.bot.wait_until_ready()
        await self.ensure_fresh_cache()
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
        self.save_cache()
        self.logger.info("Shutting down WebConnectorCog")

    def load_cache(self):
        """Load cache from file, handling expiry and structure."""
        self.cache = {}
        self.cache_timestamp = None
        if os.path.exists("cache.json"):
            with open("cache.json", "r") as f:
                try:
                    cache_data = utils.from_json(f.read())
                    if isinstance(cache_data, dict) and "_timestamp" in cache_data and "data" in cache_data:
                        self.cache = cache_data["data"]
                        self.cache_timestamp = cache_data["_timestamp"]
                    else:
                        self.cache = cache_data
                        self.cache_timestamp = None
                except Exception as e:
                    self.logger.error(f"Failed to load cache: {e}")
                    self.cache = {}
                    self.cache_timestamp = None

    def save_cache(self):
        """Save cache to file with timestamp."""
        cache_data = {"_timestamp": time.time(), "data": self.cache}
        with open("cache.json", "w") as f:
            f.write(utils.to_json(cache_data))

    def is_cache_expired(self):
        if self.cache_timestamp is None:
            return True
        return (time.time() - self.cache_timestamp) > self.cache_expiry_seconds

    async def build_cache(self):
        """Rebuild the cache from scratch, only for guilds the bot is currently in."""
        self.cache = {}
        for guild in self.bot.guilds:
            self.logger.info(f"Connected to {guild.name}")
            users = await guild.fetch_members().flatten()
            self.cache[guild.id] = {
                "users": {},
                "roles": {}
            }
            for user in users:
                self.cache[guild.id]["users"][user.id] = {
                    "username": user.name,
                    "discriminator": user.discriminator,
                    "roles": [role.id for role in user.roles]
                }
            for role in guild.roles:
                self.cache[guild.id]["roles"][role.id] = {
                    "name": role.name
                }
        self.save_cache()

    async def ensure_fresh_cache(self):
        self.load_cache()
        # Remove any guilds from cache that the bot is not in
        valid_guild_ids = {guild.id for guild in self.bot.guilds}
        removed = [gid for gid in list(self.cache.keys()) if gid not in valid_guild_ids]
        for gid in removed:
            del self.cache[gid]
        if self.is_cache_expired() or removed:
            self.logger.info("Cache expired, missing, or contained stale guilds. Rebuilding cache from Discord.")
            await self.build_cache()

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
            self.sync_user_roles_to_db(after.guild.id, after.id)
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
        db.execute(f"SELECT * FROM {os.getenv('JOBS_TABLE')} WHERE {os.getenv('JOBS_TABLE')}.process_id = %s AND {os.getenv('JOBS_TABLE')}.status = %s;",
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
                    utils.db_connector().execute(f"UPDATE {os.getenv('JOBS_TABLE')} SET status = %s WHERE id = %s;", ("completed", job[0]))
                    utils.db_connector().commit()
                else:
                    self.logger.error(f"Job {job[0]} failed!")

    def role_convert(self, roleID: int):
        for guild in self.cache:
            if roleID in self.cache[guild]["roles"]:
                return self.cache[guild]["roles"][roleID]["name"]
        return

    @tasks.loop(minutes=1)
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
                utils.db_connector().execute(f"SELECT * FROM `{os.getenv('ROLE_TABLE')}` WHERE userID = %s AND guildID = %s;",
                                             (user, cacheGuildID))
                db_roles = utils.db_connector().fetchall()
                if not db_roles:
                    utils.db_connector().execute(f"INSERT INTO `{os.getenv('ROLE_TABLE')}` (userID, guildID, DiscordRoles, "
                                                 f"LastUpdate) VALUES (%s, %s, %s, %s);",
                                                 (user, cacheGuildID, utils.to_json(t_roles), datetime.now()))
                    utils.db_connector().commit()
                else:
                    if db_roles[0][2] != t_roles:
                        utils.db_connector().execute(f"UPDATE `{os.getenv('ROLE_TABLE')}` SET DiscordRoles = %s, LastUpdate "
                                                     f"= %s WHERE userID = %s AND guildID = %s;",
                                                     (utils.to_json(t_roles), datetime.now(), user, cacheGuildID))
                        utils.db_connector().commit()
        self.logger.info(f"Cache synced at {datetime.now()}")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        guild_id = role.guild.id
        if guild_id not in self.cache:
            await self.build_cache()
        self.cache[guild_id]["roles"][role.id] = {"name": role.name}
        self.logger.info(f"Role created: {role.name} (ID: {role.id}) in guild {guild_id}. Cache updated.")
        self.save_cache()
        # Sync all users in this guild to DB since a new role may affect them
        for user_id in self.cache[role.guild.id]["users"]:
            self.sync_user_roles_to_db(role.guild.id, user_id)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        guild_id = after.guild.id
        if guild_id not in self.cache:
            await self.build_cache()
        self.cache[guild_id]["roles"][after.id] = {"name": after.name}
        self.logger.info(f"Role updated: {before.name} -> {after.name} (ID: {after.id}) in guild {guild_id}. Cache updated.")
        self.save_cache()
        # Sync all users in this guild to DB since a role name may have changed
        for user_id in self.cache[after.guild.id]["users"]:
            self.sync_user_roles_to_db(after.guild.id, user_id)

    def sync_user_roles_to_db(self, guild_id, user_id):
        t_roles = []
        for role in self.cache[guild_id]["users"][user_id]["roles"]:
            t_roles.append(self.role_convert(role))
        if not t_roles:
            t_roles = []
        utils.db_connector().execute(f"SELECT * FROM `{os.getenv('ROLE_TABLE')}` WHERE userID = %s AND guildID = %s;",
                                     (user_id, guild_id))
        db_roles = utils.db_connector().fetchall()
        if not db_roles:
            utils.db_connector().execute(f"INSERT INTO `{os.getenv('ROLE_TABLE')}` (userID, guildID, DiscordRoles, LastUpdate) VALUES (%s, %s, %s, %s);",
                                         (user_id, guild_id, utils.to_json(t_roles), datetime.now()))
            utils.db_connector().commit()
        else:
            if db_roles[0][2] != t_roles:
                utils.db_connector().execute(f"UPDATE `{os.getenv('ROLE_TABLE')}` SET DiscordRoles = %s, LastUpdate = %s WHERE userID = %s AND guildID = %s;",
                                             (utils.to_json(t_roles), datetime.now(), user_id, guild_id))
                utils.db_connector().commit()

    def send_username_change_job(self, guild_id, user_id, old_username, new_username):
        """
        Send a job to the webapp (or jobs table) when a username changes.
        """
        import time
        import utils
        job = {
            "endpoint": "username-changed",
            "data": {
                "guild_id": guild_id,
                "user_id": user_id,
                "old_username": old_username,
                "new_username": new_username,
                "timestamp": int(time.time())
            }
        }
        db = utils.db_connector()
        db.execute(f"INSERT INTO {os.getenv('JOBS_TABLE')} (process_id, payload, status, priority, time_added) VALUES (%s, %s, %s, %s, %s);",
                   (utils.get_config("JOB_BOT_NAME"), utils.to_json(job), "pending", 0, datetime.now()))
        db.commit()
        self.logger.info(f"Queued username change job for user {user_id} in guild {guild_id}: {old_username} -> {new_username}")


def setup(bot):
    bot.add_cog(WebConnectorCog(bot, logging.getLogger('main')))
