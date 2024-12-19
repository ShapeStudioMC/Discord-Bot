from discord.ext import commands
import logging

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
            self.logger.info(f"{before} roles changed from {before.roles} to {after.roles}") # Idk what, so just log atm

def setup(bot):
    bot.add_cog(WebConnectorCog(bot, logging.getLogger('main')))