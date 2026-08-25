import os
import re
import time
import random
import sqlite3
import asyncio
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks


# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from Railway Variables.")

DB = sqlite3.connect("bot.db")
DB.row_factory = sqlite3.Row


# ============================================================
# DATABASE
# ============================================================

DB.executescript("""
CREATE TABLE IF NOT EXISTS users (
    guild_id INTEGER,
    user_id INTEGER,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 0,
    coins INTEGER DEFAULT 0,
    warnings INTEGER DEFAULT 0,
    last_xp INTEGER DEFAULT 0,
    last_daily INTEGER DEFAULT 0,
    PRIMARY KEY(guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS settings (
    guild_id INTEGER PRIMARY KEY,
    log_channel INTEGER DEFAULT 0,
    welcome_channel INTEGER DEFAULT 0,
    welcome_message TEXT DEFAULT 'Welcome {user} to {server}!',
    autorole INTEGER DEFAULT 0,
    antispam INTEGER DEFAULT 1,
    antiraid INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    channel_id INTEGER,
    message TEXT,
    execute_at INTEGER
);

CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    moderator_id INTEGER,
    reason TEXT,
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS giveaways (
    message_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    guild_id INTEGER,
    prize TEXT,
    winners INTEGER,
    end_time INTEGER
);

CREATE TABLE IF NOT EXISTS tickets (
    channel_id INTEGER PRIMARY KEY,
    guild_id INTEGER,
    user_id INTEGER
);

CREATE TABLE IF NOT EXISTS reaction_roles (
    message_id INTEGER,
    emoji TEXT,
    role_id INTEGER,
    guild_id INTEGER
);
""")

DB.commit()


# ============================================================
# DATABASE HELPERS
# ============================================================

def get_settings(guild_id):
    row = DB.execute(
        "SELECT * FROM settings WHERE guild_id=?",
        (guild_id,)
    ).fetchone()

    if not row:
        DB.execute(
            "INSERT INTO settings (guild_id) VALUES (?)",
            (guild_id,)
        )
        DB.commit()

        row = DB.execute(
            "SELECT * FROM settings WHERE guild_id=?",
            (guild_id,)
        ).fetchone()

    return row


def get_user(guild_id, user_id):
    row = DB.execute(
        "SELECT * FROM users WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    ).fetchone()

    if not row:
        DB.execute(
            "INSERT INTO users (guild_id,user_id) VALUES (?,?)",
            (guild_id, user_id)
        )
        DB.commit()

        row = DB.execute(
            "SELECT * FROM users WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        ).fetchone()

    return row


def update_user(guild_id, user_id, **values):
    if not values:
        return

    fields = ", ".join(f"{k}=?" for k in values)

    DB.execute(
        f"""
        UPDATE users
        SET {fields}
        WHERE guild_id=? AND user_id=?
        """,
        (*values.values(), guild_id, user_id)
    )

    DB.commit()


async def send_log(guild, message):
    settings = get_settings(guild.id)
    channel_id = settings["log_channel"]

    if not channel_id:
        return

    channel = guild.get_channel(channel_id)

    if channel:
        try:
            await channel.send(message)
        except discord.HTTPException:
            pass


# ============================================================
# INTENTS
# ============================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.presences = True


# ============================================================
# BOT
# ============================================================

class MyBot(commands.Bot):

    async def setup_hook(self):
        await self.tree.sync()
        reminder_loop.start()
        giveaway_loop.start()


bot = MyBot(
    command_prefix="!",
    intents=intents
)


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():
    print("=" * 60)
    print(f"Logged in as {bot.user}")
    print(f"Servers: {len(bot.guilds)}")
    print("Bot is running.")
    print("=" * 60)


# ============================================================
# WELCOME / AUTOROLE
# ============================================================

@bot.event
async def on_member_join(member):

    settings = get_settings(member.guild.id)

    role_id = settings["autorole"]

    if role_id:
        role = member.guild.get_role(role_id)

        if role:
            try:
                await member.add_roles(role)
            except discord.HTTPException:
                pass

    channel_id = settings["welcome_channel"]

    if channel_id:
        channel = member.guild.get_channel(channel_id)

        if channel:
            message = settings["welcome_message"]

            message = message.replace(
                "{user}",
                member.mention
            ).replace(
                "{username}",
                member.name
            ).replace(
                "{server}",
                member.guild.name
            ).replace(
                "{membercount}",
                str(member.guild.member_count)
            )

            try:
                await channel.send(message)
            except discord.HTTPException:
                pass

    await send_log(
        member.guild,
        f"📥 {member.mention} joined the server."
    )


@bot.event
async def on_member_remove(member):
    await send_log(
        member.guild,
        f"📤 **{member}** left the server."
    )


# ============================================================
# XP / ANTI-SPAM
# ============================================================

message_tracker = {}


@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if not message.guild:
        await bot.process_commands(message)
        return

    guild_id = message.guild.id
    user_id = message.author.id

    settings = get_settings(guild_id)

    # --------------------------------------------------------
    # Anti-spam
    # --------------------------------------------------------

    if settings["antispam"]:

        key = (guild_id, user_id)

        now = time.time()

        if key not in message_tracker:
            message_tracker[key] = []

        message_tracker[key].append(now)

        message_tracker[key] = [
            x for x in message_tracker[key]
            if now - x <= 7
        ]

        if len(message_tracker[key]) >= 7:

            try:
                await message.author.timeout(
                    timedelta(minutes=1),
                    reason="Automatic anti-spam"
                )

                await message.channel.send(
                    f"🛡️ {message.author.mention} was timed out "
                    f"for spam."
                )

                await send_log(
                    message.guild,
                    f"🛡️ Anti-spam timed out {message.author}."
                )

            except discord.HTTPException:
                pass

            message_tracker[key].clear()

    # --------------------------------------------------------
    # XP
    # --------------------------------------------------------

    user = get_user(guild_id, user_id)

    now = int(time.time())

    if now - user["last_xp"] >= 45:

        earned = random.randint(10, 20)

        xp = user["xp"] + earned
        level = user["level"]

        required = 100 + level * 50

        if xp >= required:

            xp -= required
            level += 1

            await message.channel.send(
                f"🎉 {message.author.mention} reached "
                f"**Level {level}**!"
            )

        update_user(
            guild_id,
            user_id,
            xp=xp,
            level=level,
            last_xp=now
        )

    await bot.process_commands(message)


# ============================================================
# BASIC
# ============================================================

@bot.tree.command(
    name="ping",
    description="Check bot latency"
)
async def ping(interaction):

    ms = round(bot.latency * 1000)

    await interaction.response.send_message(
        f"🏓 Pong! `{ms}ms`"
    )


@bot.tree.command(
    name="botinfo",
    description="Show bot information"
)
async def botinfo(interaction):

    embed = discord.Embed(
        title="🤖 Bot Information",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Servers",
        value=str(len(bot.guilds))
    )

    embed.add_field(
        name="Users",
        value=str(len(bot.users))
    )

    embed.add_field(
        name="Latency",
        value=f"{round(bot.latency * 1000)}ms"
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# FUN
# ============================================================

@bot.tree.command(
    name="roll",
    description="Roll a dice"
)
async def roll(
    interaction,
    sides: app_commands.Range[int, 2, 1000] = 6
):

    result = random.randint(1, sides)

    await interaction.response.send_message(
        f"🎲 You rolled **{result}** / {sides}"
    )


@bot.tree.command(
    name="coinflip",
    description="Flip a coin"
)
async def coinflip(interaction):

    await interaction.response.send_message(
        f"🪙 **{random.choice(['Heads', 'Tails'])}!**"
    )


@bot.tree.command(
    name="8ball",
    description="Ask the magic 8-ball"
)
async def eightball(
    interaction,
    question: str
):

    answers = [
        "Yes.",
        "No.",
        "Definitely.",
        "Probably.",
        "Probably not.",
        "Ask again later.",
        "Absolutely.",
        "Absolutely not.",
        "The answer is unclear."
    ]

    await interaction.response.send_message(
        f"🎱 **{question}**\n"
        f"**{random.choice(answers)}**"
    )


@bot.tree.command(
    name="choose",
    description="Choose between options"
)
async def choose(
    interaction,
    options: str
):

    choices = [
        x.strip()
        for x in options.split(",")
        if x.strip()
    ]

    if len(choices) < 2:

        await interaction.response.send_message(
            "❌ Give me at least two options."
        )

        return

    await interaction.response.send_message(
        f"🤔 I choose **{random.choice(choices)}**!"
    )


@bot.tree.command(
    name="rate",
    description="Rate something"
)
async def rate(
    interaction,
    thing: str
):

    score = random.randint(0, 100)

    await interaction.response.send_message(
        f"📊 **{thing}** gets **{score}/100**."
    )


# ============================================================
# USER
# ============================================================

@bot.tree.command(
    name="avatar",
    description="Show a user's avatar"
)
async def avatar(
    interaction,
    member: discord.Member = None
):

    member = member or interaction.user

    embed = discord.Embed(
        title=f"{member.display_name}'s Avatar"
    )

    embed.set_image(
        url=member.display_avatar.url
    )

    await interaction.response.send_message(
        embed=embed
    )


@bot.tree.command(
    name="userinfo",
    description="Show user information"
)
async def userinfo(
    interaction,
    member: discord.Member = None
):

    member = member or interaction.user

    user = get_user(
        interaction.guild.id,
        member.id
    )

    embed = discord.Embed(
        title=f"👤 {member}",
        color=discord.Color.blurple()
    )

    embed.set_thumbnail(
        url=member.display_avatar.url
    )

    embed.add_field(
        name="ID",
        value=str(member.id),
        inline=False
    )

    embed.add_field(
        name="Level",
        value=str(user["level"])
    )

    embed.add_field(
        name="XP",
        value=str(user["xp"])
    )

    embed.add_field(
        name="Coins",
        value=str(user["coins"])
    )

    embed.add_field(
        name="Warnings",
        value=str(user["warnings"])
    )

    await interaction.response.send_message(
        embed=embed
    )


@bot.tree.command(
    name="serverinfo",
    description="Show server information"
)
async def serverinfo(interaction):

    guild = interaction.guild

    embed = discord.Embed(
        title=f"🏠 {guild.name}",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Members",
        value=str(guild.member_count)
    )

    embed.add_field(
        name="Channels",
        value=str(len(guild.channels))
    )

    embed.add_field(
        name="Roles",
        value=str(len(guild.roles))
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# MODERATION
# ============================================================

@bot.tree.command(
    name="clear",
    description="Delete messages"
)
@app_commands.checks.has_permissions(
    manage_messages=True
)
async def clear(
    interaction,
    amount: app_commands.Range[int, 1, 100]
):

    await interaction.response.defer(
        ephemeral=True
    )

    deleted = await interaction.channel.purge(
        limit=amount
    )

    await interaction.followup.send(
        f"🧹 Deleted **{len(deleted)}** messages.",
        ephemeral=True
    )


@bot.tree.command(
    name="kick",
    description="Kick a member"
)
@app_commands.checks.has_permissions(
    kick_members=True
)
async def kick(
    interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    if member == interaction.user:

        await interaction.response.send_message(
            "❌ You can't kick yourself.",
            ephemeral=True
        )

        return

    await member.kick(
        reason=reason
    )

    await interaction.response.send_message(
        f"👢 **{member}** was kicked.\n"
        f"Reason: {reason}"
    )

    await send_log(
        interaction.guild,
        f"👢 {member} was kicked by {interaction.user}."
    )


@bot.tree.command(
    name="ban",
    description="Ban a member"
)
@app_commands.checks.has_permissions(
    ban_members=True
)
async def ban(
    interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    if member == interaction.user:

        await interaction.response.send_message(
            "❌ You can't ban yourself.",
            ephemeral=True
        )

        return

    await member.ban(
        reason=reason
    )

    await interaction.response.send_message(
        f"🔨 **{member}** was banned.\n"
        f"Reason: {reason}"
    )

    await send_log(
        interaction.guild,
        f"🔨 {member} was banned by {interaction.user}."
    )


@bot.tree.command(
    name="unban",
    description="Unban a user by ID"
)
@app_commands.checks.has_permissions(
    ban_members=True
)
async def unban(
    interaction,
    user_id: str
):

    try:
        user = await bot.fetch_user(
            int(user_id)
        )

        await interaction.guild.unban(user)

        await interaction.response.send_message(
            f"🔓 Unbanned **{user}**."
        )

    except Exception:

        await interaction.response.send_message(
            "❌ Could not unban that user.",
            ephemeral=True
        )


@bot.tree.command(
    name="timeout",
    description="Timeout a member"
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def timeout(
    interaction,
    member: discord.Member,
    minutes: app_commands.Range[int, 1, 40320],
    reason: str = "No reason provided"
):

    await member.timeout(
        timedelta(minutes=minutes),
        reason=reason
    )

    await interaction.response.send_message(
        f"⏱️ {member.mention} was timed out for "
        f"**{minutes} minutes**."
    )


@bot.tree.command(
    name="untimeout",
    description="Remove a timeout"
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def untimeout(
    interaction,
    member: discord.Member
):

    await member.timeout(None)

    await interaction.response.send_message(
        f"🔓 Timeout removed from {member.mention}."
    )


# ============================================================
# WARNINGS
# ============================================================

@bot.tree.command(
    name="warn",
    description="Warn a member"
)
@app_commands.checks.has_permissions(
    manage_messages=True
)
async def warn(
    interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    user = get_user(
        interaction.guild.id,
        member.id
    )

    warnings = user["warnings"] + 1

    update_user(
        interaction.guild.id,
        member.id,
        warnings=warnings
    )

    DB.execute(
        """
        INSERT INTO warnings
        (guild_id,user_id,moderator_id,reason,created_at)
        VALUES (?,?,?,?,?)
        """,
        (
            interaction.guild.id,
            member.id,
            interaction.user.id,
            reason,
            int(time.time())
        )
    )

    DB.commit()

    await interaction.response.send_message(
        f"⚠️ {member.mention} warned.\n"
        f"Reason: {reason}\n"
        f"Warnings: **{warnings}**"
    )


@bot.tree.command(
    name="warnings",
    description="Show warnings"
)
@app_commands.checks.has_permissions(
    manage_messages=True
)
async def warnings(
    interaction,
    member: discord.Member
):

    user = get_user(
        interaction.guild.id,
        member.id
    )

    rows = DB.execute(
        """
        SELECT * FROM warnings
        WHERE guild_id=? AND user_id=?
        ORDER BY id DESC
        LIMIT 10
        """,
        (
            interaction.guild.id,
            member.id
        )
    ).fetchall()

    if not rows:

        await interaction.response.send_message(
            f"✅ {member.mention} has no warnings."
        )

        return

    text = "\n".join(
        f"`#{row['id']}` {row['reason']}"
        for row in rows
    )

    await interaction.response.send_message(
        f"⚠️ **{member} — {user['warnings']} warnings**\n\n"
        f"{text}"
    )


@bot.tree.command(
    name="resetwarnings",
    description="Reset warnings"
)
@app_commands.checks.has_permissions(
    manage_messages=True
)
async def resetwarnings(
    interaction,
    member: discord.Member
):

    update_user(
        interaction.guild.id,
        member.id,
        warnings=0
    )

    DB.execute(
        """
        DELETE FROM warnings
        WHERE guild_id=? AND user_id=?
        """,
        (
            interaction.guild.id,
            member.id
        )
    )

    DB.commit()

    await interaction.response.send_message(
        f"✅ Reset warnings for {member.mention}."
    )


# ============================================================
# CHANNEL LOCK
# ============================================================

@bot.tree.command(
    name="lock",
    description="Lock the current channel"
)
@app_commands.checks.has_permissions(
    manage_channels=True
)
async def lock(interaction):

    overwrite = interaction.channel.overwrites_for(
        interaction.guild.default_role
    )

    overwrite.send_messages = False

    await interaction.channel.set_permissions(
        interaction.guild.default_role,
        overwrite=overwrite
    )

    await interaction.response.send_message(
        "🔒 Channel locked."
    )


@bot.tree.command(
    name="unlock",
    description="Unlock the current channel"
)
@app_commands.checks.has_permissions(
    manage_channels=True
)
async def unlock(interaction):

    overwrite = interaction.channel.overwrites_for(
        interaction.guild.default_role
    )

    overwrite.send_messages = None

    await interaction.channel.set_permissions(
        interaction.guild.default_role,
        overwrite=overwrite
    )

    await interaction.response.send_message(
        "🔓 Channel unlocked."
    )


# ============================================================
# SLOWMODE
# ============================================================

@bot.tree.command(
    name="slowmode",
    description="Set channel slowmode"
)
@app_commands.checks.has_permissions(
    manage_channels=True
)
async def slowmode(
    interaction,
    seconds: app_commands.Range[int, 0, 21600]
):

    await interaction.channel.edit(
        slowmode_delay=seconds
    )

    await interaction.response.send_message(
        f"🐌 Slowmode: **{seconds}s**"
    )


# ============================================================
# ECONOMY
# ============================================================

@bot.tree.command(
    name="balance",
    description="Check your balance"
)
async def balance(interaction):

    user = get_user(
        interaction.guild.id,
        interaction.user.id
    )

    await interaction.response.send_message(
        f"💰 {interaction.user.mention} has "
        f"**{user['coins']} coins**."
    )


@bot.tree.command(
    name="daily",
    description="Claim your daily reward"
)
async def daily(interaction):

    user = get_user(
        interaction.guild.id,
        interaction.user.id
    )

    now = int(time.time())

    if now - user["last_daily"] < 86400:

        remaining = 86400 - (
            now - user["last_daily"]
        )

        hours = remaining // 3600
        minutes = (remaining % 3600) // 60

        await interaction.response.send_message(
            f"⏳ Try again in **{hours}h {minutes}m**.",
            ephemeral=True
        )

        return

    reward = random.randint(100, 500)

    update_user(
        interaction.guild.id,
        interaction.user.id,
        coins=user["coins"] + reward,
        last_daily=now
    )

    await interaction.response.send_message(
        f"💰 You received **{reward} coins**!"
    )


@bot.tree.command(
    name="work",
    description="Work for coins"
)
async def work(interaction):

    user = get_user(
        interaction.guild.id,
        interaction.user.id
    )

    reward = random.randint(25, 150)

    jobs = [
        "programmer",
        "YouTuber",
        "game developer",
        "pizza delivery driver",
        "streamer",
        "Discord moderator"
    ]

    update_user(
        interaction.guild.id,
        interaction.user.id,
        coins=user["coins"] + reward
    )

    await interaction.response.send_message(
        f"💼 You worked as a **{random.choice(jobs)}** "
        f"and earned **{reward} coins**."
    )


@bot.tree.command(
    name="give",
    description="Give coins"
)
async def give(
    interaction,
    member: discord.Member,
    amount: app_commands.Range[int, 1, 1000000]
):

    sender = get_user(
        interaction.guild.id,
        interaction.user.id
    )

    receiver = get_user(
        interaction.guild.id,
        member.id
    )

    if sender["coins"] < amount:

        await interaction.response.send_message(
            "❌ You don't have enough coins.",
            ephemeral=True
        )

        return

    update_user(
        interaction.guild.id,
        interaction.user.id,
        coins=sender["coins"] - amount
    )

    update_user(
        interaction.guild.id,
        member.id,
        coins=receiver["coins"] + amount
    )

    await interaction.response.send_message(
        f"💸 Gave **{amount} coins** to {member.mention}."
    )


# ============================================================
# LEVELS
# ============================================================

@bot.tree.command(
    name="rank",
    description="Show your level"
)
async def rank(interaction):

    user = get_user(
        interaction.guild.id,
        interaction.user.id
    )

    required = 100 + user["level"] * 50

    await interaction.response.send_message(
        f"⭐ **{interaction.user.display_name}**\n"
        f"Level: **{user['level']}**\n"
        f"XP: **{user['xp']} / {required}**"
    )


@bot.tree.command(
    name="leaderboard",
    description="Show XP leaderboard"
)
async def leaderboard(interaction):

    rows = DB.execute(
        """
        SELECT * FROM users
        WHERE guild_id=?
        ORDER BY level DESC, xp DESC
        LIMIT 10
        """,
        (interaction.guild.id,)
    ).fetchall()

    if not rows:

        await interaction.response.send_message(
            "No data yet."
        )

        return

    text = []

    for i, row in enumerate(rows, 1):

        member = interaction.guild.get_member(
            row["user_id"]
        )

        name = (
            member.display_name
            if member
            else f"User {row['user_id']}"
        )

        text.append(
            f"**{i}.** {name} — "
            f"Level {row['level']} ({row['xp']} XP)"
        )

    embed = discord.Embed(
        title="🏆 Leaderboard",
        description="\n".join(text),
        color=discord.Color.gold()
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# POLLS
# ============================================================

@bot.tree.command(
    name="poll",
    description="Create a poll"
)
async def poll(
    interaction,
    question: str,
    options: str
):

    choices = [
        x.strip()
        for x in options.split("|")
        if x.strip()
    ]

    if len(choices) < 2 or len(choices) > 10:

        await interaction.response.send_message(
            "❌ Use between 2 and 10 options."
        )

        return

    emojis = [
        "🇦", "🇧", "🇨", "🇩", "🇪",
        "🇫", "🇬", "🇭", "🇮", "🇯"
    ]

    description = "\n".join(
        f"{emojis[i]} {option}"
        for i, option in enumerate(choices)
    )

    embed = discord.Embed(
        title=f"📊 {question}",
        description=description,
        color=discord.Color.blurple()
    )

    await interaction.response.send_message(
        embed=embed
    )

    message = await interaction.original_response()

    for i in range(len(choices)):

        await message.add_reaction(
            emojis[i]
        )


# ============================================================
# REMINDERS
# ============================================================

@bot.tree.command(
    name="remind",
    description="Set a reminder"
)
async def remind(
    interaction,
    minutes: app_commands.Range[int, 1, 10080],
    message: str
):

    execute_at = int(time.time()) + minutes * 60

    DB.execute(
        """
        INSERT INTO reminders
        (user_id,channel_id,message,execute_at)
        VALUES (?,?,?,?)
        """,
        (
            interaction.user.id,
            interaction.channel.id,
            message,
            execute_at
        )
    )

    DB.commit()

    await interaction.response.send_message(
        f"⏰ Reminder set for **{minutes} minutes**."
    )


@tasks.loop(seconds=10)
async def reminder_loop():

    now = int(time.time())

    rows = DB.execute(
        """
        SELECT * FROM reminders
        WHERE execute_at <= ?
        """,
        (now,)
    ).fetchall()

    for row in rows:

        channel = bot.get_channel(
            row["channel_id"]
        )

        if channel:

            try:

                await channel.send(
                    f"⏰ <@{row['user_id']}> "
                    f"Reminder: **{row['message']}**"
                )

            except discord.HTTPException:
                pass

        DB.execute(
            "DELETE FROM reminders WHERE id=?",
            (row["id"],)
        )

    DB.commit()


# ============================================================
# WELCOME SETTINGS
# ============================================================

@bot.tree.command(
    name="setwelcome",
    description="Set welcome channel"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def setwelcome(
    interaction,
    channel: discord.TextChannel
):

    DB.execute(
        """
        UPDATE settings
        SET welcome_channel=?
        WHERE guild_id=?
        """,
        (
            channel.id,
            interaction.guild.id
        )
    )

    DB.commit()

    await interaction.response.send_message(
        f"👋 Welcome channel set to {channel.mention}."
    )


@bot.tree.command(
    name="setwelcomemessage",
    description="Set welcome message"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def setwelcomemessage(
    interaction,
    message: str
):

    DB.execute(
        """
        UPDATE settings
        SET welcome_message=?
        WHERE guild_id=?
        """,
        (
            message,
            interaction.guild.id
        )
    )

    DB.commit()

    await interaction.response.send_message(
        "✅ Welcome message updated."
    )


# ============================================================
# LOG CHANNEL
# ============================================================

@bot.tree.command(
    name="setlog",
    description="Set moderation log channel"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def setlog(
    interaction,
    channel: discord.TextChannel
):

    DB.execute(
        """
        UPDATE settings
        SET log_channel=?
        WHERE guild_id=?
        """,
        (
            channel.id,
            interaction.guild.id
        )
    )

    DB.commit()

    await interaction.response.send_message(
        f"📋 Log channel set to {channel.mention}."
    )


# ============================================================
# AUTOROLE
# ============================================================

@bot.tree.command(
    name="setautorole",
    description="Set automatic join role"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def setautorole(
    interaction,
    role: discord.Role
):

    DB.execute(
        """
        UPDATE settings
        SET autorole=?
        WHERE guild_id=?
        """,
        (
            role.id,
            interaction.guild.id
        )
    )

    DB.commit()

    await interaction.response.send_message(
        f"🎭 Auto-role set to {role.mention}."
    )


# ============================================================
# TICKETS
# ============================================================

@bot.tree.command(
    name="ticket",
    description="Create a private support ticket"
)
async def ticket(interaction):

    guild = interaction.guild

    existing = DB.execute(
        """
        SELECT * FROM tickets
        WHERE guild_id=? AND user_id=?
        """,
        (
            guild.id,
            interaction.user.id
        )
    ).fetchone()

    if existing:

        await interaction.response.send_message(
            f"❌ You already have a ticket: "
            f"<#{existing['channel_id']}>",
            ephemeral=True
        )

        return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False
        ),
        interaction.user: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True
        )
    }

    channel = await guild.create_text_channel(
        f"ticket-{interaction.user.name}",
        overwrites=overwrites
    )

    DB.execute(
        """
        INSERT INTO tickets
        (channel_id,guild_id,user_id)
        VALUES (?,?,?)
        """,
        (
            channel.id,
            guild.id,
            interaction.user.id
        )
    )

    DB.commit()

    await interaction.response.send_message(
        f"🎫 Ticket created: {channel.mention}",
        ephemeral=True
    )

    await channel.send(
        f"🎫 Welcome {interaction.user.mention}!\n"
        f"Explain your issue here."
    )


@bot.tree.command(
    name="closeticket",
    description="Close the current ticket"
)
async def closeticket(interaction):

    ticket = DB.execute(
        """
        SELECT * FROM tickets
        WHERE channel_id=?
        """,
        (interaction.channel.id,)
    ).fetchone()

    if not ticket:

        await interaction.response.send_message(
            "❌ This isn't a ticket channel.",
            ephemeral=True
        )

        return

    DB.execute(
        "DELETE FROM tickets WHERE channel_id=?",
        (interaction.channel.id,)
    )

    DB.commit()

    await interaction.response.send_message(
        "🔒 Closing ticket..."
    )

    await asyncio.sleep(3)

    await interaction.channel.delete()


# ============================================================
# GIVEAWAYS
# ============================================================

class GiveawayView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Enter Giveaway",
        emoji="🎉",
        style=discord.ButtonStyle.green,
        custom_id="giveaway_enter"
    )
    async def enter(
        self,
        interaction,
        button
    ):

        message = interaction.message

        try:
            await message.add_reaction("🎉")

            await interaction.response.send_message(
                "🎉 You entered the giveaway!",
                ephemeral=True
            )

        except discord.HTTPException:

            await interaction.response.send_message(
                "❌ Could not enter.",
                ephemeral=True
            )


@bot.tree.command(
    name="giveaway",
    description="Start a giveaway"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def giveaway(
    interaction,
    minutes: app_commands.Range[int, 1, 10080],
    winners: app_commands.Range[int, 1, 20],
    prize: str
):

    end_time = int(time.time()) + minutes * 60

    embed = discord.Embed(
        title="🎉 GIVEAWAY",
        description=(
            f"Prize: **{prize}**\n"
            f"Winners: **{winners}**\n\n"
            f"Ends <t:{end_time}:R>\n\n"
            f"Click **Enter Giveaway** to participate!"
        ),
        color=discord.Color.gold()
    )

    await interaction.response.send_message(
        embed=embed,
        view=GiveawayView()
    )

    message = await interaction.original_response()

    DB.execute(
        """
        INSERT INTO giveaways
        (message_id,channel_id,guild_id,prize,winners,end_time)
        VALUES (?,?,?,?,?,?)
        """,
        (
            message.id,
            interaction.channel.id,
            interaction.guild.id,
            prize,
            winners,
            end_time
        )
    )

    DB.commit()


@tasks.loop(seconds=15)
async def giveaway_loop():

    now = int(time.time())

    rows = DB.execute(
        """
        SELECT * FROM giveaways
        WHERE end_time <= ?
        """,
        (now,)
    ).fetchall()

    for giveaway in rows:

        channel = bot.get_channel(
            giveaway["channel_id"]
        )

        if not channel:
            continue

        try:
            message = await channel.fetch_message(
                giveaway["message_id"]
            )

            reaction = discord.utils.get(
                message.reactions,
                emoji="🎉"
            )

            if not reaction:

                await channel.send(
                    "🎉 Giveaway ended, but nobody entered."
                )

            else:

                users = [
                    user async for user
                    in reaction.users()
                    if not user.bot
                ]

                if not users:

                    await channel.send(
                        "🎉 Giveaway ended, but nobody entered."
                    )

                else:

                    winners = random.sample(
                        users,
                        min(
                            giveaway["winners"],
                            len(users)
                        )
                    )

                    mentions = ", ".join(
                        user.mention
                        for user in winners
                    )

                    await channel.send(
                        f"🎉 Congratulations {mentions}!\n"
                        f"You won **{giveaway['prize']}**!"
                    )

        except discord.HTTPException:
            pass

        DB.execute(
            "DELETE FROM giveaways WHERE message_id=?",
            (giveaway["message_id"],)
        )

    DB.commit()


# ============================================================
# HELP
# ============================================================

@bot.tree.command(
    name="help",
    description="Show bot commands"
)
async def help_command(interaction):

    embed = discord.Embed(
        title="🤖 Bot Commands",
        description="All-in-one Discord bot",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🛡️ Moderation",
        value=(
            "`/ban`\n"
            "`/kick`\n"
            "`/unban`\n"
            "`/timeout`\n"
            "`/untimeout`\n"
            "`/warn`\n"
            "`/warnings`\n"
            "`/resetwarnings`\n"
            "`/clear`\n"
            "`/lock`\n"
            "`/unlock`\n"
            "`/slowmode`"
        ),
        inline=True
    )

    embed.add_field(
        name="💰 Economy",
        value=(
            "`/balance`\n"
            "`/daily`\n"
            "`/work`\n"
            "`/give`"
        ),
        inline=True
    )

    embed.add_field(
        name="⭐ Levels",
        value=(
            "`/rank`\n"
            "`/leaderboard`"
        ),
        inline=True
    )

    embed.add_field(
        name="🎮 Fun",
        value=(
            "`/roll`\n"
            "`/coinflip`\n"
            "`/8ball`\n"
            "`/choose`\n"
            "`/rate`"
        ),
        inline=True
    )

    embed.add_field(
        name="🎫 Server",
        value=(
            "`/ticket`\n"
            "`/closeticket`\n"
            "`/poll`\n"
            "`/giveaway`"
        ),
        inline=True
    )

    embed.add_field(
        name="⚙️ Setup",
        value=(
            "`/setlog`\n"
            "`/setwelcome`\n"
            "`/setwelcomemessage`\n"
            "`/setautorole`"
        ),
        inline=True
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# ERROR HANDLER
# ============================================================

@bot.tree.error
async def on_command_error(
    interaction,
    error
):

    if isinstance(
        error,
        app_commands.MissingPermissions
    ):

        message = (
            "❌ You don't have permission "
            "to use this command."
        )

    elif isinstance(
        error,
        app_commands.BotMissingPermissions
    ):

        message = (
            "❌ I don't have the permissions "
            "required for that."
        )

    else:

        print(
            "COMMAND ERROR:",
            repr(error)
        )

        message = (
            "❌ Something went wrong "
            "while running the command."
        )

    if interaction.response.is_done():

        await interaction.followup.send(
            message,
            ephemeral=True
        )

    else:

        await interaction.response.send_message(
            message,
            ephemeral=True
        )


# ============================================================
# START
# ============================================================

bot.run(TOKEN)
