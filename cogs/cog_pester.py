from discord.ext import commands
import logging

class PesterCog(commands.Cog):
    def __init__(self, bot, logger):
        self.bot = bot
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.handlers = logger.handlers
        self.logger.setLevel(logger.level)
        self.logger.propagate = False



def setup(bot):
    bot.add_cog(PesterCog(bot, bot.logger))