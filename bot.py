import os
import random
import sqlite3
import asyncio
import time
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks


# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("Set the DISCORD_TOKEN environment variable.")

PREFIX = "!"
DB_FILE = "bot.db"


# ============================================================
# DATABASE
# ============================================================

db = sqlite3.connect(DB_FILE)
db.row_factory = sqlite3.Row

db.execute("""
CREATE TABLE IF NOT EXISTS users (
    guild_id INTEGER,
    user_id INTEGER,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 0,
    coins INTEGER DEFAULT 0,
    warnings INTEGER DEFAULT 0,
    last_daily INTEGER DEFAULT 0,
    last_message INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS settings (
    guild_id INTEGER PRIMARY KEY,
    welcome_channel INTEGER,
    log_channel INTEGER,
    welcome_message TEXT
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    channel_id INTEGER,
    message TEXT,
    execute_at INTEGER
)
""")

db.commit()


def get_user(guild_id, user_id):
    user = db.execute(
        "SELECT * FROM users WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    ).fetchone()

    if not user:
        db.execute(
            "INSERT INTO users (guild_id,user_id) VALUES (?,?)",
            (guild_id, user_id)
        )
        db.commit()

        user = db.execute(
            "SELECT * FROM users WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        ).fetchone()

    return user


def update_user(guild_id, user_id, **values):
    if not values:
        return

    fields = ", ".join(f"{key}=?" for key in values)
    params = list(values.values())
    params.extend([guild_id, user_id])

    db.execute(
        f"UPDATE users SET {fields} WHERE guild_id=? AND user_id=?",
        params
    )
    db.commit()


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

class Bot(commands.Bot):
    async def setup_hook(self):
        await self.tree.sync()
        reminder_loop.start()


bot = Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():
    print("=" * 50)
    print(f"Logged in as: {bot.user}")
    print(f"Servers: {len(bot.guilds)}")
    print("Bot is online.")
    print("=" * 50)


# ============================================================
# XP / LEVELING
# ============================================================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.guild:
        user = get_user(message.guild.id, message.author.id)

        now = int(time.time())

        # Don't give XP for every single message.
        if now - user["last_message"] >= 45:
            earned = random.randint(10, 20)

            xp = user["xp"] + earned
            level = user["level"]

            required = 100 + (level * 50)

            if xp >= required:
                xp -= required
                level += 1

                try:
                    await message.channel.send(
                        f"🎉 {message.author.mention} reached **Level {level}**!"
                    )
                except discord.HTTPException:
                    pass

            update_user(
                message.guild.id,
                message.author.id,
                xp=xp,
                level=level,
                last_message=now
            )

    await bot.process_commands(message)


# ============================================================
# BASIC
# ============================================================

@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! `{ms}ms`")


@bot.tree.command(name="botinfo", description="Show bot information")
async def botinfo(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Bot Information",
        color=discord.Color.blurple()
    )

    embed.add_field(name="Servers", value=str(len(bot.guilds)))
    embed.add_field(name="Users", value=str(len(bot.users)))
    embed.add_field(
        name="Latency",
        value=f"{round(bot.latency * 1000)}ms"
    )

    await interaction.response.send_message(embed=embed)


# ============================================================
# FUN
# ============================================================

@bot.tree.command(name="roll", description="Roll a dice")
@app_commands.describe(sides="Number of sides")
async def roll(
    interaction: discord.Interaction,
    sides: app_commands.Range[int, 2, 1000] = 6
):
    result = random.randint(1, sides)
    await interaction.response.send_message(
        f"🎲 {interaction.user.mention} rolled **{result}** / {sides}"
    )


@bot.tree.command(name="coinflip", description="Flip a coin")
async def coinflip(interaction: discord.Interaction):
    result = random.choice(["Heads", "Tails"])
    await interaction.response.send_message(f"🪙 **{result}!**")


@bot.tree.command(name="8ball", description="Ask the magic 8-ball")
@app_commands.describe(question="Your question")
async def eightball(
    interaction: discord.Interaction,
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
        "The answer is unclear.",
        "I don't know."
    ]

    await interaction.response.send_message(
        f"🎱 **Question:** {question}\n"
        f"**Answer:** {random.choice(answers)}"
    )


@bot.tree.command(name="choose", description="Choose between options")
@app_commands.describe(options="Separate options with commas")
async def choose(
    interaction: discord.Interaction,
    options: str
):
    choices = [x.strip() for x in options.split(",") if x.strip()]

    if len(choices) < 2:
        await interaction.response.send_message(
            "❌ Give me at least 2 options separated by commas."
        )
        return

    await interaction.response.send_message(
        f"🤔 I choose **{random.choice(choices)}**!"
    )


@bot.tree.command(name="rate", description="Rate something from 0-100")
@app_commands.describe(thing="What should I rate?")
async def rate(
    interaction: discord.Interaction,
    thing: str
):
    score = random.randint(0, 100)

    await interaction.response.send_message(
        f"📊 I rate **{thing}** a **{score}/100**."
    )


# ============================================================
# USER INFO
# ============================================================

@bot.tree.command(name="avatar", description="Show a user's avatar")
@app_commands.describe(member="Member")
async def avatar(
    interaction: discord.Interaction,
    member: discord.Member = None
):
    member = member or interaction.user

    embed = discord.Embed(
        title=f"{member.display_name}'s Avatar",
        color=discord.Color.blurple()
    )

    embed.set_image(url=member.display_avatar.url)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="userinfo", description="Show user information")
@app_commands.describe(member="Member")
async def userinfo(
    interaction: discord.Interaction,
    member: discord.Member = None
):
    member = member or interaction.user

    user = get_user(interaction.guild.id, member.id)

    embed = discord.Embed(
        title=f"👤 {member}",
        color=discord.Color.blurple()
    )

    embed.set_thumbnail(url=member.display_avatar.url)

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

    embed.add_field(
        name="Joined",
        value=discord.utils.format_dt(member.joined_at, "R")
    )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="serverinfo", description="Show server information")
async def serverinfo(interaction: discord.Interaction):
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

    embed.add_field(
        name="Owner",
        value=str(guild.owner)
    )

    await interaction.response.send_message(embed=embed)


# ============================================================
# MODERATION
# ============================================================

@bot.tree.command(name="clear", description="Delete messages")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.describe(amount="Number of messages")
async def clear(
    interaction: discord.Interaction,
    amount: app_commands.Range[int, 1, 100]
):
    await interaction.response.defer(ephemeral=True)

    deleted = await interaction.channel.purge(limit=amount)

    await interaction.followup.send(
        f"🧹 Deleted **{len(deleted)}** messages.",
        ephemeral=True
    )


@bot.tree.command(name="kick", description="Kick a member")
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.describe(member="Member", reason="Reason")
async def kick(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):
    if member == interaction.user:
        await interaction.response.send_message(
            "❌ You can't kick yourself.",
            ephemeral=True
        )
        return

    await member.kick(reason=reason)

    await interaction.response.send_message(
        f"👢 **{member}** was kicked.\nReason: {reason}"
    )


@bot.tree.command(name="ban", description="Ban a member")
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.describe(member="Member", reason="Reason")
async def ban(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):
    if member == interaction.user:
        await interaction.response.send_message(
            "❌ You can't ban yourself.",
            ephemeral=True
        )
        return

    await member.ban(reason=reason)

    await interaction.response.send_message(
        f"🔨 **{member}** was banned.\nReason: {reason}"
    )


@bot.tree.command(name="timeout", description="Timeout a member")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.describe(
    member="Member",
    minutes="Timeout duration",
    reason="Reason"
)
async def timeout(
    interaction: discord.Interaction,
    member: discord.Member,
    minutes: app_commands.Range[int, 1, 40320],
    reason: str = "No reason provided"
):
    until = discord.utils.utcnow() + timedelta(minutes=minutes)

    await member.timeout(
        until,
        reason=reason
    )

    await interaction.response.send_message(
        f"⏱️ {member.mention} has been timed out for "
        f"**{minutes} minutes**."
    )


@bot.tree.command(name="untimeout", description="Remove a timeout")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout(
    interaction: discord.Interaction,
    member: discord.Member
):
    await member.timeout(None)

    await interaction.response.send_message(
        f"🔓 Removed timeout from {member.mention}."
    )


@bot.tree.command(name="warn", description="Warn a member")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.describe(member="Member", reason="Reason")
async def warn(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):
    user = get_user(interaction.guild.id, member.id)

    warnings = user["warnings"] + 1

    update_user(
        interaction.guild.id,
        member.id,
        warnings=warnings
    )

    await interaction.response.send_message(
        f"⚠️ {member.mention} has been warned.\n"
        f"Reason: {reason}\n"
        f"Warnings: **{warnings}**"
    )


@bot.tree.command(name="warnings", description="View member warnings")
@app_commands.checks.has_permissions(manage_messages=True)
async def warnings(
    interaction: discord.Interaction,
    member: discord.Member
):
    user = get_user(interaction.guild.id, member.id)

    await interaction.response.send_message(
        f"⚠️ {member.mention} has **{user['warnings']} warnings**."
    )


# ============================================================
# LOCK / UNLOCK
# ============================================================

@bot.tree.command(name="lock", description="Lock the current channel")
@app_commands.checks.has_permissions(manage_channels=True)
async def lock(interaction: discord.Interaction):
    channel = interaction.channel

    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False

    await channel.set_permissions(
        interaction.guild.default_role,
        overwrite=overwrite
    )

    await interaction.response.send_message(
        "🔒 This channel has been locked."
    )


@bot.tree.command(name="unlock", description="Unlock the current channel")
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock(interaction: discord.Interaction):
    channel = interaction.channel

    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None

    await channel.set_permissions(
        interaction.guild.default_role,
        overwrite=overwrite
    )

    await interaction.response.send_message(
        "🔓 This channel has been unlocked."
    )


# ============================================================
# SLOWMODE
# ============================================================

@bot.tree.command(name="slowmode", description="Set channel slowmode")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(seconds="Slowmode seconds")
async def slowmode(
    interaction: discord.Interaction,
    seconds: app_commands.Range[int, 0, 21600]
):
    await interaction.channel.edit(
        slowmode_delay=seconds
    )

    await interaction.response.send_message(
        f"🐌 Slowmode set to **{seconds} seconds**."
    )


# ============================================================
# ECONOMY
# ============================================================

@bot.tree.command(name="balance", description="Check your coins")
async def balance(interaction: discord.Interaction):
    user = get_user(
        interaction.guild.id,
        interaction.user.id
    )

    await interaction.response.send_message(
        f"💰 {interaction.user.mention} has "
        f"**{user['coins']} coins**."
    )


@bot.tree.command(name="daily", description="Claim your daily reward")
async def daily(interaction: discord.Interaction):
    user = get_user(
        interaction.guild.id,
        interaction.user.id
    )

    now = int(time.time())

    if now - user["last_daily"] < 86400:
        remaining = 86400 - (now - user["last_daily"])

        hours = remaining // 3600
        minutes = (remaining % 3600) // 60

        await interaction.response.send_message(
            f"⏳ You already claimed your daily reward.\n"
            f"Try again in **{hours}h {minutes}m**.",
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


@bot.tree.command(name="work", description="Work for coins")
async def work(interaction: discord.Interaction):
    user = get_user(
        interaction.guild.id,
        interaction.user.id
    )

    reward = random.randint(25, 150)

    update_user(
        interaction.guild.id,
        interaction.user.id,
        coins=user["coins"] + reward
    )

    jobs = [
        "programmer",
        "pizza delivery driver",
        "game developer",
        "YouTuber",
        "Discord moderator",
        "shopkeeper",
        "streamer"
    ]

    job = random.choice(jobs)

    await interaction.response.send_message(
        f"💼 You worked as a **{job}** and earned **{reward} coins**."
    )


@bot.tree.command(name="give", description="Give coins to another member")
async def give(
    interaction: discord.Interaction,
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
        f"💸 {interaction.user.mention} gave "
        f"**{amount} coins** to {member.mention}."
    )


# ============================================================
# LEVEL
# ============================================================

@bot.tree.command(name="rank", description="Show your level")
async def rank(interaction: discord.Interaction):
    user = get_user(
        interaction.guild.id,
        interaction.user.id
    )

    required = 100 + (user["level"] * 50)

    await interaction.response.send_message(
        f"⭐ **{interaction.user.display_name}**\n"
        f"Level: **{user['level']}**\n"
        f"XP: **{user['xp']} / {required}**"
    )


@bot.tree.command(name="leaderboard", description="Show the XP leaderboard")
async def leaderboard(interaction: discord.Interaction):
    rows = db.execute(
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
            "No leaderboard data yet."
        )
        return

    text = []

    for index, row in enumerate(rows, start=1):
        member = interaction.guild.get_member(row["user_id"])

        if member:
            name = member.display_name
        else:
            name = f"User {row['user_id']}"

        text.append(
            f"**{index}.** {name} — "
            f"Level {row['level']} ({row['xp']} XP)"
        )

    embed = discord.Embed(
        title="🏆 XP Leaderboard",
        description="\n".join(text),
        color=discord.Color.gold()
    )

    await interaction.response.send_message(embed=embed)


# ============================================================
# POLL
# ============================================================

@bot.tree.command(name="poll", description="Create a poll")
@app_commands.describe(
    question="Poll question",
    options="Options separated by |"
)
async def poll(
    interaction: discord.Interaction,
    question: str,
    options: str
):
    choices = [x.strip() for x in options.split("|")]

    if len(choices) < 2:
        await interaction.response.send_message(
            "❌ You need at least 2 options."
        )
        return

    if len(choices) > 10:
        await interaction.response.send_message(
            "❌ Maximum 10 options."
        )
        return

    letters = [
        "🇦", "🇧", "🇨", "🇩", "🇪",
        "🇫", "🇬", "🇭", "🇮", "🇯"
    ]

    description = "\n".join(
        f"{letters[i]} {option}"
        for i, option in enumerate(choices)
    )

    embed = discord.Embed(
        title=f"📊 {question}",
        description=description,
        color=discord.Color.blurple()
    )

    await interaction.response.send_message(embed=embed)

    message = await interaction.original_response()

    for i in range(len(choices)):
        await message.add_reaction(letters[i])


# ============================================================
# ANNOUNCEMENT
# ============================================================

@bot.tree.command(name="announce", description="Send an announcement")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    message="Announcement text"
)
async def announce(
    interaction: discord.Interaction,
    message: str
):
    embed = discord.Embed(
        title="📢 Announcement",
        description=message,
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )

    embed.set_footer(
        text=f"Sent by {interaction.user}"
    )

    await interaction.channel.send(embed=embed)

    await interaction.response.send_message(
        "✅ Announcement sent.",
        ephemeral=True
    )


# ============================================================
# REMINDERS
# ============================================================

@bot.tree.command(name="remind", description="Set a reminder")
@app_commands.describe(
    minutes="Minutes from now",
    message="Reminder message"
)
async def remind(
    interaction: discord.Interaction,
    minutes: app_commands.Range[int, 1, 10080],
    message: str
):
    execute_at = int(time.time()) + (minutes * 60)

    db.execute(
        """
        INSERT INTO reminders
        (user_id, channel_id, message, execute_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            interaction.user.id,
            interaction.channel.id,
            message,
            execute_at
        )
    )

    db.commit()

    await interaction.response.send_message(
        f"⏰ Reminder set for **{minutes} minutes** from now."
    )


@tasks.loop(seconds=10)
async def reminder_loop():
    now = int(time.time())

    reminders = db.execute(
        "SELECT * FROM reminders WHERE execute_at <= ?",
        (now,)
    ).fetchall()

    for reminder in reminders:
        channel = bot.get_channel(reminder["channel_id"])

        if channel:
            try:
                await channel.send(
                    f"⏰ <@{reminder['user_id']}> "
                    f"Reminder: **{reminder['message']}**"
                )
            except discord.HTTPException:
                pass

        db.execute(
            "DELETE FROM reminders WHERE id=?",
            (reminder["id"],)
        )

    db.commit()


# ============================================================
# HELP
# ============================================================

@bot.tree.command(name="help", description="Show bot commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Bot Commands",
        description="Here are the available commands:",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🎮 Fun",
        value="/roll\n/coinflip\n/8ball\n/choose\n/rate",
        inline=True
    )

    embed.add_field(
        name="👤 User",
        value="/avatar\n/userinfo\n/rank\n/balance",
        inline=True
    )

    embed.add_field(
        name="🛡️ Moderation",
        value="/ban\n/kick\n/timeout\n/untimeout\n/warn\n/clear",
        inline=True
    )

    embed.add_field(
        name="💰 Economy",
        value="/balance\n/daily\n/work\n/give",
        inline=True
    )

    embed.add_field(
        name="📊 Server",
        value="/serverinfo\n/poll\n/announce",
        inline=True
    )

    embed.add_field(
        name="⏰ Utility",
        value="/remind\n/ping\n/botinfo",
        inline=True
    )

    await interaction.response.send_message(embed=embed)


# ============================================================
# ERROR HANDLER
# ============================================================

@bot.tree.error
async def command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        message = "❌ You don't have permission to use this command."

    elif isinstance(error, app_commands.BotMissingPermissions):
        message = "❌ I don't have the permissions required for that."

    elif isinstance(error, app_commands.CommandOnCooldown):
        message = "⏳ You're using that command too quickly."

    else:
        print("COMMAND ERROR:", repr(error))
        message = "❌ An error occurred while running the command."

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
# RUN
# ============================================================

bot.run(TOKEN)
