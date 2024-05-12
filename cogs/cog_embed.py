import json as cjson
import logging
import discord
from discord import option
from discord.ext import commands

import utils


class embed_cog(commands.Cog):
    def __init__(self, bot, logger):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.handlers = logger.handlers
        self.logger.setLevel(logger.level)
        self.logger.propagate = False
        self.bot = bot

    # create slash command group
    embed = discord.SlashCommandGroup(name="embed", description="Commands for managing embeds")

    @embed.command(name="create", description="Create an embed")
    @option("json", "The JSON string representing the embed")
    async def create(self, ctx: discord.ApplicationContext, json: str = None):
        if utils.has_permission(ctx.author.id, "manage_embeds", self.bot.db_location):
            if json:
                try:
                    embed_json = cjson.loads(json)
                    embed = discord.Embed.from_dict(embed_json["embeds"][0])
                    await ctx.respond(embed=embed, ephemeral=True)
                    # todo: save this and allow for referencing to it later on in the show command
                except cjson.JSONDecodeError:
                    await ctx.respond("Invalid JSON", ephemeral=True)
            else:
                # todo: add an interactive discord.view builder
                await ctx.respond("No JSON provided", ephemeral=True)
        else:
            await ctx.respond("You do not have permission to manage embeds", ephemeral=True)

    @embed.command(name="show", description="Show an embed")
    async def show(self, ctx: discord.ApplicationContext, embed_id: int):
        # todo: implement this
        await ctx.respond(f"Not implemented yet. Embed ID: {embed_id}", ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info(f'Hello from {self.__class__.__name__}!')


def setup(bot):
    bot.add_cog(embed_cog(bot, bot.logger))
