from pprint import pprint

from discord.ext import commands
import logging
import utils

class WebConnectorCog(commands.Cog):
    def __init__(self, bot, logger):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.handlers = logger.handlers
        self.logger.setLevel(logger.level)
        self.logger.propagate = False
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.roles != after.roles: # If roles have changed
            self.logger.info(f"{before} roles changed from {before.roles} to {after.roles}")

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        print("guild updated")
        pprint(after.to_dict())
        if before.roles != after.roles:
            self.logger.info(f"{before} roles changed from {before.roles} to {after.roles}")
            # get guild settings
            settings = await utils.get_settings(after)
            pprint(settings)


def setup(bot):
    bot.add_cog(WebConnectorCog(bot, logging.getLogger('main')))