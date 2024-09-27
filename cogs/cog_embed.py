import io
import json as cjson
import logging
import os
import re
from discord.ext import tasks
import discord
from discord import option
from discord.ext import commands
import sqlite3
import aiosqlite
import utils
from cogs.cog_threads import NoteModal

"""
a boolean variable setting an edit button or not (so having an option implemented to have the edit button for easier usage)
a variable bar where you can choose between "none", "daily" or "everytime";
 - "daily" meaning that the same message will be reposted every 24 hours, deleting the last one meaning there will be just one message at all times
 - "everytime" meaning message will be reposting when the message gets edited edited, it will also delete the last one message that was edited, this will there will be just one message at all times
/embed namechange
/embed name list
/embed edit (modal)
"""


class EditEmbedModal(NoteModal):
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
        super().__init__(title=embed_name, note=embed, db_location=db_location, *args, **kwargs)
        self.embed_name = embed_name

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        new_embed = interaction.data["components"][0]["components"][0]["value"]
        async with aiosqlite.connect(self.db_location) as db:
            await db.execute("UPDATE embeds SET data = ? WHERE name = ?",
                             (new_embed, self.embed_name))
            await db.commit()
        await interaction.followup.send("✔ `Embed updated!`", ephemeral=True, delete_after=5)
        return True


class DisplayExampleEmbedView(discord.ui.View):
    def __init__(self, db_location, user_id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_location = db_location
        self.original_user_id = user_id

    @discord.ui.button(style=discord.ButtonStyle.success, label="Yes")
    async def button_yes_callback(self, button: discord.ui.Button, interaction: discord.Interaction):
        """
        Handle the callback when the "Yes" button is pressed.

        Args:
            button (discord.ui.Button): The button object.
            interaction (discord.Interaction): The interaction object.
        """
        if interaction.user.id == self.original_user_id and await utils.has_permission(interaction, "manage_embeds",
                                                                                       self.db_location):
            await interaction.response.defer()
            async with aiosqlite.connect(self.db_location) as db:
                data = interaction.message.embeds
                json_embeds = []
                for embed in data[:-1]:
                    json_embeds.append(embed.to_dict())
                try:
                    await db.execute("INSERT INTO embeds (data, guild_id, name) VALUES (?, ?, ?)",
                                     (cjson.dumps(json_embeds), interaction.guild.id,
                                      data[-1].description.split("**")[1]))
                except sqlite3.IntegrityError:
                    await interaction.response.send_message("❌ `Embed with that name already exists`", ephemeral=True)
                    return
                await db.commit()
            await interaction.delete_original_response()
            await interaction.followup.send("✔ `Embed saved successfully`", ephemeral=True)
            return True
        elif interaction.user.id == self.original_user_id:
            await interaction.response.send_message("❌ `You do not have permission to respond (Not command author)`",
                                                    ephemeral=True)
        else:
            await interaction.response.send_message("❌ 1You do not have permission to create embeds (Missing "
                                                    "'manage_embeds' permission)`", ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.danger, label="No")
    async def button_no_callback(self, button: discord.ui.Button, interaction: discord.Interaction):
        """
        Handle the callback when the "No" button is pressed.

        Args:
            interaction (discord.Interaction): The interaction object.
        """
        if interaction.user.id == self.original_user_id:
            await interaction.message.delete()
            await interaction.respond("❌ `Embed not saved`", ephemeral=True, delete_after=5)
        else:
            await interaction.respond("❌ `You do not have permission to respond (Not command author)`", ephemeral=True)


async def build_embed_choices(ctx: discord.AutocompleteContext):
    """
    Build a list of embed choices for a given guild.

    Args:
        ctx (discord.AutocompleteContext): The context of the command.

    Returns:
        list: A list of embed names.
    """
    with sqlite3.connect(os.getenv('DATABASE_LOCATION')) as db:
        cursor = db.cursor()
        cursor.execute("SELECT name FROM embeds WHERE guild_id = ?;", (ctx.interaction.guild.id,))
        embeds = cursor.fetchall()
    choices = []
    for embed in embeds:
        choices.append(embed[0])
    return choices


class EmbedCog(commands.Cog):
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
        self.embed_names = []

    # create slash command group
    embed = discord.SlashCommandGroup(name="embed", description="Commands for managing embeds")
    name_regex = r"/^[\w\-\s]+$/"

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info(f'Hello from {self.__class__.__name}!')
        self.embed_names = self.build_embed_choices()
        self.update_embeds_list.start()

    @tasks.loop(seconds=60)
    async def update_embeds_list(self):
        """
        Update the list of embeds every 60 seconds.
        """
        await self.bot.wait_until_ready()
        self.embed_names = self.build_embed_choices()

    @embed.command(name="import", description="Import an embed from JSON")
    @option(name="json", description="The JSON for the embed", required=True)
    @option(name="name", description="The name of the embed", required=True)
    async def cmd_import(self, ctx: discord.ApplicationContext, json: str, name: str):
        """
        Import an embed from JSON.

        Args:
            ctx (discord.ApplicationContext): The application context.
            json (str): The JSON data for the embed.
            name (str): The name of the embed.
        """
        if await utils.has_permission(ctx, "manage_embeds", self.bot.db_location):
            if re.match(self.name_regex, name):
                await ctx.respond("❌ `Invalid name. Name must contain only letters, numbers, spaces, and hyphens.`",
                                  ephemeral=True)
                return
            if json:
                try:
                    embed_json = cjson.loads(json)
                except cjson.JSONDecodeError:
                    await ctx.respond("❌ `Invalid JSON provided. Please use a discord embed generator or a "
                                      "JSON validator.`", ephemeral=True)
                    return
                embeds = []
                for embed in embed_json["embeds"]:
                    embeds.append(discord.Embed.from_dict(embed))
                embeds.append(discord.Embed(title="Embeds", description=f"Above are the embeds you provided. Would you "
                                                                        f"like to save them under the name **{name}**?"))
                await ctx.respond(embeds=embeds, view=DisplayExampleEmbedView(self.bot.db_location, ctx.author.id),
                                  ephemeral=True)
            else:
                await ctx.respond("❌ `No JSON provided. Please use a discord embed generator or a JSON validator.`",
                                  ephemeral=True)
        else:
            await ctx.respond("❌ `You do not have permission to manage embeds`", ephemeral=True)

    @embed.command(name="create", description="Create a new embed")
    @option(name="name", description="The name of the embed", required=True)
    @option(name="embed-color", description="The HEX color code of the embed. (#FFFFFF)", required=False)
    @option(name="embed-title", description="The title of the embed", required=False)
    @option(name="text", description="The description of the embed", required=True)
    @option(name="embed-image", description="The image of the embed", required=False)
    @option(name="embed-thumbnail", description="The thumbnail of the embed", required=False)
    @option(name="embed-author", description="The author of the embed", required=False)
    @option(name="embed-fields", description="The fields of the embed", required=False)
    @option(name="embed-footer", description="The footer of the embed", required=False)
    async def create(self, ctx: discord.ApplicationContext, name: str, embed_description: str,
                     embed_color: str = None, embed_title: str = None,
                     embed_image: discord.Attachment = None, embed_thumbnail: str = None,
                     embed_author: discord.User = None, embed_fields: str = None, embed_footer: str = None):

        if await utils.has_permission(ctx, "manage_embeds", self.bot.db_location):
            await ctx.defer()
            if embed_color is not None:
                print(embed_color)
                try:
                    if embed_color.startswith("#"):
                        pass
                    elif embed_color.isdigit():
                        embed_color = discord.Color(int(embed_color))
                    else:
                        embed_color = discord.Color(embed_color)
                except discord.ext.commands.errors.BadColourArgument:
                    await ctx.respond("❌ `Invalid color provided`", ephemeral=True)
                    return
                except TypeError:
                    await ctx.respond("❌ `Invalid color provided`", ephemeral=True)
                    return
            embed = discord.Embed(title=embed_title, description=embed_description,
                                  color=embed_color)
            if embed_image:
                embed.set_image(url=embed_image)
            if embed_thumbnail:
                embed.set_thumbnail(url=embed_thumbnail)
            if embed_author:
                embed.set_author(name=embed_author.name, icon_url=embed_author.avatar.url)
            if embed_fields:
                fields = embed_fields.split(",")
                for field in fields:
                    name, value, inline = field.split(":")
                    embed.add_field(name=name, value=value,
                                    inline=True if inline.lower() == "true" or inline.lower() == "t" else False)
            if embed_footer:
                embed.set_footer(text=embed_footer)
            embeds = []
            embed_json = {"embeds": [embed.to_dict()]}
            for embed in embed_json["embeds"]:
                embeds.append(discord.Embed.from_dict(embed))
            embeds.append(discord.Embed(title="Embeds", description=f"Above are the embeds you provided. Would you "
                                                                    f"like to save them under the name **{name}**?"))
            await ctx.respond(embeds=embeds, view=DisplayExampleEmbedView(self.bot.db_location, ctx.author.id),
                              ephemeral=True)
        else:
            await ctx.respond("❌ `You do not have permission to manage embeds`", ephemeral=True)

    @embed.command(name="post", description="Post an embed to the Chat")
    async def post(self, ctx: discord.ApplicationContext, name: discord.Option(str, name="name",
                                                                               description="Select an embed",
                                                                               autocomplete=build_embed_choices)):
        """
        Post an embed to the chat.

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
            avalible_embeds = build_embed_choices(ctx.guild.id)
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
                await ctx.respond(f"❌ `Embed with a name of {name} was not found`", ephemeral=True)

    @embed.command(name="delete", description="Delete an embed")
    @option(name="name", description="The name of the embed", required=False, autocomplete=build_embed_choices)
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
                await ctx.respond(f"✔ `Embed with the name of {name} has been deleted.`", ephemeral=True)
                return True

        if await utils.has_permission(ctx, "manage_embeds", self.bot.db_location):
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
                    await ctx.respond(f"✔ `Embed with the name of {name} has been deleted.`", ephemeral=True)
                    return True
            await ctx.respond(f"❌ `Could not find embed with the name of {name}.`", ephemeral=True)

    @embed.command(name="edit", description="Edit an embed")
    @option(name="name", description="The name of the embed", required=True, autocomplete=build_embed_choices)
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

        if await utils.has_permission(ctx, "manage_embeds", self.bot.db_location):
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
                    await ctx.send_modal(
                        EditEmbedModal(embed=data[0], embed_name=name, db_location=self.bot.db_location))
                    return True
            await ctx.respond(f"❌ `Could not find embed with the name of {name}.`", ephemeral=True)
        else:
            await ctx.respond("❌ `You do not have permission to manage embeds`", ephemeral=True)

    @embed.command(name="rename", description="Rename an embed")
    @option(name="name", description="The name of the embed", required=True, autocomplete=build_embed_choices)
    @option(name="new_name", description="The new name of the embed", required=True)
    async def rename(self, ctx: discord.ApplicationContext, name: str, new_name: str):
        """
        Rename an embed.

        Args:
            ctx (discord.ApplicationContext): The application context.
            name (str): The name of the embed.
            new_name (str): The new name of the embed.
        """
        if await utils.has_permission(ctx, "manage_embeds", self.bot.db_location):
            if name is None or name == "":
                await ctx.respond("❌ `No embed provided!`", ephemeral=True)
                return
            elif (name != "" and name is not None) and not re.match(self.name_regex, name):
                async with aiosqlite.connect(self.bot.db_location) as db:
                    async with db.execute("SELECT data FROM embeds WHERE name = ? AND guild_id = ?",
                                          (name, ctx.guild.id)) as cursor:
                        data = await cursor.fetchone()
                if data:
                    async with aiosqlite.connect(self.bot.db_location) as db:
                        await db.execute("UPDATE embeds SET name = ? WHERE name = ? AND guild_id = ?",
                                         (new_name, name, ctx.guild.id))
                        await db.commit()
                    await ctx.respond(f"✔ `Embed with the name of {name} has been renamed to {new_name}.`",
                                      ephemeral=True)
                    return True
            await ctx.respond(f"❌ `Could not find embed with the name of {name}.`", ephemeral=True)
        else:
            await ctx.respond("❌ `You do not have permission to manage embeds`", ephemeral=True)

    @embed.command(name="export", description="Export an embed to JSON")
    @option(name="name", description="The name of the embed", required=True, autocomplete=build_embed_choices)
    async def export(self, ctx: discord.ApplicationContext, name: str):
        """
        Export an embed to JSON.

        Args:
            ctx (discord.ApplicationContext): The application context.
            name (str): The name of the embed.
        """
        if await utils.has_permission(ctx, "manage_embeds", self.bot.db_location):
            if name is None or name == "":
                await ctx.respond("❌ `No embed provided!`", ephemeral=True)
                return
            elif (name != "" and name is not None) and not re.match(self.name_regex, name):
                async with aiosqlite.connect(self.bot.db_location) as db:
                    async with db.execute("SELECT data FROM embeds WHERE name = ? AND guild_id = ?",
                                          (name, ctx.guild.id)) as cursor:
                        data = await cursor.fetchone()
                if data:
                    data = {"embeds": cjson.loads(data[0])}
                    if len(str(data)) > 2000:
                        # convert data to bytes using iobytes, then send as a file
                        stream = io.BytesIO(bytes(str(data), "utf-8"))
                        await ctx.respond("❌ `Too large to send inside discord message.`",
                                          ephemeral=True, file=discord.File(stream,
                                                                            filename=f"{name}_export.json"))
                        return
                    await ctx.respond(f"```json\n{cjson.dumps(data)}```", ephemeral=True)
                    return True
            await ctx.respond(f"❌ `Could not find embed with the name of {name}.`", ephemeral=True)
        else:
            await ctx.respond("❌ `You do not have permission to manage embeds`", ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info(f'Hello from {self.__class__.__name__}!')


def setup(bot):
    """
    Set up the embed_cog. bot.logger should have been set previously in main.py.
    Args:
        bot (commands.Bot): The bot instance.
    """
    bot.add_cog(EmbedCog(bot, bot.logger))
