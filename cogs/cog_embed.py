import json as cjson
import logging
import re
import discord
from discord import option
from discord.ext import commands
import sqlite3
import aiosqlite
import utils
from cogs.cog_threads import NoteModal


class EditEmbedModal(NoteModal):
    """
    A modal for editing an embed.

    Attributes:
        embed (str): The embed data.
        embed_name (str): The name of the embed.
        db_location (str): The location of the database.
    """
    def __init__(self, embed, embed_name, db_location, *args, **kwargs) -> None:
        """
        Initialize the EditEmbedModal.

        Args:
            embed (str): The embed data.
            embed_name (str): The name of the embed.
            db_location (str): The location of the database.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.
        """
        super().__init__(note=embed, db_location=db_location, *args, **kwargs)
        self.embed_name = embed_name

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        new_embed = interaction.data["components"][0]["components"][0]["value"]
        async with aiosqlite.connect(self.db_location) as db:
            await db.execute("UPDATE embeds SET data = ? WHERE name = ?",
                             (new_embed, self.embed_name))
            await db.commit()
        await interaction.followup.send("Embed updated!", ephemeral=True, delete_after=5)
        return True


class embed_cog(commands.Cog):
    """
    A cog for managing embeds.

    Attributes:
        bot (commands.Bot): The bot instance.
        logger (logging.Logger): The logger instance.
    """
    def __init__(self, bot, logger):
        """
        Initialize the embed_cog.

        Args:
            bot (commands.Bot): The bot instance.
            logger (logging.Logger): The logger instance.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.handlers = logger.handlers
        self.logger.setLevel(logger.level)
        self.logger.propagate = False
        self.bot = bot

    # create slash command group
    embed = discord.SlashCommandGroup(name="embed", description="Commands for managing embeds")
    name_regex = r"/^[\w\-\s]+$/"

    @embed.command(name="create", description="Create an embed")
    @option(name="json", description="The JSON for the embed", required=True)
    @option(name="name", description="The name of the embed", required=True)
    async def create(self, ctx: discord.ApplicationContext, json: str, name: str):
        """
        Create a new embed.

        Args:
            ctx (discord.ApplicationContext): The application context.
            json (str): The JSON data for the embed.
            name (str): The name of the embed.
        """
        async def process_yes_callback(interaction: discord.Interaction):
            """
            Handle the callback when the "Yes" button is pressed.

            Args:
                interaction (discord.Interaction): The interaction object.
            """
            if interaction.user.id == ctx.author.id and await utils.has_permission(ctx.author.id, "manage_embeds",
                                                                                   self.bot.db_location):
                await interaction.response.defer()
                async with aiosqlite.connect(self.bot.db_location) as db:
                    data = interaction.message.embeds
                    json_embeds = []
                    for embed in data[:-1]:
                        json_embeds.append(embed.to_dict())
                    await db.execute("INSERT INTO embeds (data, guild_id, name) VALUES (?, ?, ?)",
                                     (cjson.dumps(json_embeds), ctx.guild.id, name))
                    await db.commit()
                await interaction.delete_original_response()
                await ctx.respond("Embed saved successfully", ephemeral=True)
                return True

        async def process_no_callback(interaction: discord.Interaction):
            """
            Handle the callback when the "No" button is pressed.

            Args:
                interaction (discord.Interaction): The interaction object.
            """
            if interaction.user.id == ctx.author.id:
                await interaction.message.delete()
                await ctx.respond("Embed not saved", ephemeral=True, delete_after=5)

        if await utils.has_permission(ctx.author.id, "manage_embeds", self.bot.db_location):
            if re.match(self.name_regex, name):
                await ctx.respond("Invalid name. Name must contain only letters, numbers, spaces, and hyphens.",
                                  ephemeral=True)
                return
            if json:
                try:
                    embed_json = cjson.loads(json)
                except cjson.JSONDecodeError:
                    await ctx.respond("Invalid JSON. Please use a [discord embed generator]("
                                      "https://message.style/app/editor) or a [JSON validator](https://jsonlint.com/)",
                                      ephemeral=True)
                    return
                embeds = []
                for embed in embed_json["embeds"]:
                    embeds.append(discord.Embed.from_dict(embed))
                embeds.append(discord.Embed(title="Embeds", description=f"Above are the embeds you provided. Would you "
                                                                        f"like to save them under the name **{name}**?"))
                view = discord.ui.View()
                yes_button = discord.ui.Button(style=discord.ButtonStyle.success, label="Yes")
                no_button = discord.ui.Button(style=discord.ButtonStyle.danger, label="No")
                yes_button.callback = process_yes_callback
                no_button.callback = process_no_callback
                view.add_item(yes_button)
                view.add_item(no_button)
                await ctx.respond(embeds=embeds, view=view, ephemeral=True)
            else:
                await ctx.respond("No JSON provided. Please use a [discord embed generator]("
                                  "https://message.style/app/editor).", ephemeral=True)
        else:
            await ctx.respond("You do not have permission to manage embeds", ephemeral=True)

    def build_embed_choices(self, guild_id: int):
        """
        Build a list of embed choices for a given guild.

        Args:
            guild_id (int): The ID of the guild.

        Returns:
            list: A list of embed names.
        """
        with sqlite3.connect(self.bot.db_location) as db:
            cursor = db.cursor()
            cursor.execute("SELECT name FROM embeds WHERE guild_id = ?", (guild_id,))
            embeds = cursor.fetchall()
        choices = []
        for embed in embeds:
            choices.append(embed[0])
        print(choices)
        return choices

    @embed.command(name="show", description="Show an embed")
    @option(name="name", description="The name of the embed", required=True)
    async def show(self, ctx: discord.ApplicationContext, name: str = None):
        """
        Show an embed.

        Args:
            ctx (discord.ApplicationContext): The application context.
            name (str, optional): The name of the embed. Defaults to None.
        """
        async def show_callback(interaction: discord.Interaction):
            """
            Handle the callback when an embed is selected to be shown.

            Args:
                interaction (discord.Interaction): The interaction object.
            """
            await interaction.response.defer()
            if interaction.user.id == ctx.author.id:
                name = interaction.data["values"][0]
                async with aiosqlite.connect(self.bot.db_location) as db:
                    async with db.execute("SELECT data FROM embeds WHERE name = ? AND guild_id = ?",
                                          (name, ctx.guild.id)) as cursor:
                        data = await cursor.fetchone()
                data = cjson.loads(data[0])
                embeds = []
                for embed in data:
                    embeds.append(discord.Embed.from_dict(embed))
                await ctx.respond(embeds=embeds, ephemeral=False)
                await interaction.delete_original_response()
                return True

        if name == "" or name is None:
            view = discord.ui.View()
            avalible_embeds = self.build_embed_choices(ctx.guild.id)
            options = []
            for embed in avalible_embeds:
                option = discord.SelectOption(label=embed, value=embed)
                options.append(option)
            select = discord.ui.Select(select_type=discord.ComponentType.string_select, placeholder="Select an embed",
                                       options=options)
            select.callback = show_callback
            view.add_item(select)
            embed = discord.Embed(title="No embed provided!")
            await ctx.respond(embed=embed, view=view, ephemeral=True)
            return
        elif not re.match(self.name_regex, name):
            async with aiosqlite.connect(self.bot.db_location) as db:
                async with db.execute("SELECT data FROM embeds WHERE name = ? AND guild_id = ?",
                                      (name, ctx.guild.id)) as cursor:
                    data = await cursor.fetchone()
            if data:
                data = cjson.loads(data[0])
                embeds = []
                for embed in data:
                    embeds.append(discord.Embed.from_dict(embed))
                await ctx.respond(embeds=embeds, ephemeral=False)
            else:
                await ctx.respond(f"Embed with a name of {name} was not found", ephemeral=True)

    @embed.command(name="delete", description="Delete an embed")
    @option(name="name", description="The name of the embed", required=False)
    async def delete(self, ctx: discord.ApplicationContext, name: str = None):
        """
        Delete an embed.

        Args:
            ctx (discord.ApplicationContext): The application context.
            name (str, optional): The name of the embed. Defaults to None.
        """
        async def delete_callback(interaction: discord.Interaction):
            """
            Handle the callback when an embed is selected to be deleted.

            Args:
                interaction (discord.Interaction): The interaction object.
            """
            await interaction.response.defer()
            if interaction.user.id == ctx.author.id:
                name = interaction.data["values"][0]
                async with aiosqlite.connect(self.bot.db_location) as db:
                    await db.execute("DELETE FROM embeds WHERE name = ? AND guild_id = ?", (name, ctx.guild.id))
                    await db.commit()
                await interaction.delete_original_response()
                await ctx.respond(f"Embed with the name of {name} has been deleted.", ephemeral=True)
                return True

        if await utils.has_permission(ctx.author.id, "manage_embeds", self.bot.db_location):
            if name is None or name == "":
                view = discord.ui.View()
                avalible_embeds = self.build_embed_choices(ctx.guild.id)
                options = []
                for embed in avalible_embeds:
                    option = discord.SelectOption(label=embed, value=embed)
                    options.append(option)
                select = discord.ui.Select(select_type=discord.ComponentType.string_select,
                                           placeholder="Select an embed",
                                           options=options)
                select.callback = delete_callback
                view.add_item(select)
                embed = discord.Embed(title="No embed provided!")
                await ctx.respond(embed=embed, view=view, ephemeral=True)
                return
            elif (name != "" and name is not None) and not re.match(self.name_regex, name):
                async with aiosqlite.connect(self.bot.db_location) as db:
                    async with db.execute("SELECT data FROM embeds WHERE name = ? AND guild_id = ?",
                                          (name, ctx.guild.id)) as cursor:
                        data = await cursor.fetchone()
                if data:
                    async with aiosqlite.connect(self.bot.db_location) as db:
                        await db.execute("DELETE FROM embeds WHERE name = ? AND guild_id = ?", (name, ctx.guild.id))
                        await db.commit()
                    await ctx.respond(f"Embed with the name of {name} has been deleted.", ephemeral=True)
                    return True
            await ctx.respond(f"Could not find embed with the name of {name}.", ephemeral=True)

    @embed.command(name="edit", description="Edit an embed")
    @option(name="name", description="The name of the embed", required=False)
    async def edit(self, ctx: discord.ApplicationContext, name: str):
        """
        Edit an embed.

        Args:
            ctx (discord.ApplicationContext): The application context.
            name (str): The name of the embed.
        """
        async def edit_callback(interaction: discord.Interaction):
            """
            Handle the callback when an embed is selected to be edited.
            Args:
                interaction (discord.Interaction): The interaction object.
            """
            # await interaction.response.defer()
            if interaction.user.id == ctx.author.id:
                name = interaction.data["values"][0]
                async with aiosqlite.connect(self.bot.db_location) as db:
                    async with db.execute("SELECT data FROM embeds WHERE name = ? AND guild_id = ?",
                                          (name, ctx.guild.id)) as cursor:
                        data = await cursor.fetchone()
                modal = EditEmbedModal(embed=data[0], embed_name=name, db_location=self.bot.db_location,
                                       title=f"Edit embed for {utils.limit(name, 45)}")
                await interaction.response.send_modal(modal)
                return True

        if await utils.has_permission(ctx.author.id, "manage_embeds", self.bot.db_location):
            if name is None or name == "":
                view = discord.ui.View()
                avalible_embeds = self.build_embed_choices(ctx.guild.id)
                options = []
                for embed in avalible_embeds:
                    option = discord.SelectOption(label=embed, value=embed)
                    options.append(option)
                select = discord.ui.Select(select_type=discord.ComponentType.string_select,
                                           placeholder="Select an embed",
                                           options=options)
                select.callback = edit_callback
                view.add_item(select)
                embed = discord.Embed(title="No embed provided!")
                await ctx.respond(embed=embed, view=view, ephemeral=True)
                return
            elif (name != "" and name is not None) and not re.match(self.name_regex, name):
                async with aiosqlite.connect(self.bot.db_location) as db:
                    async with db.execute("SELECT data FROM embeds WHERE name = ? AND guild_id = ?",
                                          (name, ctx.guild.id)) as cursor:
                        data = await cursor.fetchone()
                if data:
                    modal = EditEmbedModal(embed=data[0], embed_name=name, db_location=self.bot.db_location)
                    await ctx.respond(modal=modal, ephemeral=True)
                    return True
            await ctx.respond(f"Could not find embed with the name of {name}.", ephemeral=True)
        else:
            await ctx.respond("You do not have permission to manage embeds", ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info(f'Hello from {self.__class__.__name__}!')


def setup(bot):
    """
    Set up the embed_cog. bot.logger should have been set previously in main.py.
    Args:
        bot (commands.Bot): The bot instance.
        """
    bot.add_cog(embed_cog(bot, bot.logger))
