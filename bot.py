# ============================================================
# MEGA DISCORD BOT - SINGLE FILE
# discord.py 2.x
#
# Railway:
#   DISCORD_TOKEN=your_bot_token
#
# requirements.txt:
#   discord.py
#
# Procfile:
#   worker: python bot.py
#
# IMPORTANT:
# Without a database, data resets whenever the bot restarts.
# ============================================================

import os
import random
import time
import asyncio
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks


# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing.")

PREFIX = "!"

# In-memory storage
guild_config = defaultdict(lambda: {
    "log_channel": None,
    "welcome_channel": None,
    "welcome_message": "Welcome {user} to **{server}**!",
    "goodbye_channel": None,
    "goodbye_message": "{username} left the server.",
    "autorole": None,
    "mod_role": None,
    "ticket_category": None,
    "level_channel": None,
    "xp_enabled": True,
    "economy_enabled": True,
    "antispam": True,
    "antilink": False,
    "antiraid": False,
    "verification_role": None,
})

users = defaultdict(lambda: {
    "xp": 0,
    "level": 0,
    "coins": 0,
    "warnings": [],
    "rep": 0,
    "last_xp": 0,
    "last_daily": 0,
    "last_work": 0,
    "last_beg": 0,
})

tickets = {}
giveaways = {}
reminders = {}
cases = defaultdict(list)
reaction_roles = defaultdict(dict)
custom_commands = defaultdict(dict)
birthday_data = {}
temporary_voice_channels = set()

message_tracker = defaultdict(deque)
join_tracker = defaultdict(deque)

# Used to stop duplicate background loops
background_started = False


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

class MegaBot(commands.Bot):

    async def setup_hook(self):
        await self.tree.sync()

        # Persistent button view
        self.add_view(TicketPanelView())
        self.add_view(VerificationView())

        global background_started

        if not background_started:
            reminder_loop.start()
            giveaway_loop.start()
            background_started = True


bot = MegaBot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)


# ============================================================
# HELPERS
# ============================================================

def cfg(guild_id):
    return guild_config[guild_id]


def profile(guild_id, user_id):
    return users[(guild_id, user_id)]


def is_admin(member):
    return member.guild_permissions.administrator


def is_mod(member):
    settings = cfg(member.guild.id)

    if is_admin(member):
        return True

    role_id = settings["mod_role"]

    if role_id:
        role = member.guild.get_role(role_id)

        if role and role in member.roles:
            return True

    return member.guild_permissions.manage_messages


async def log_event(guild, text):
    settings = cfg(guild.id)

    channel_id = settings["log_channel"]

    if not channel_id:
        return

    channel = guild.get_channel(channel_id)

    if channel:
        try:
            await channel.send(text)
        except discord.HTTPException:
            pass


async def add_case(guild, action, target, moderator, reason):
    case_id = len(cases[guild.id]) + 1

    data = {
        "id": case_id,
        "action": action,
        "target": target,
        "moderator": moderator,
        "reason": reason,
        "time": int(time.time()),
    }

    cases[guild.id].append(data)

    await log_event(
        guild,
        f"📋 **Case #{case_id}** | `{action}` | "
        f"Target: {target} | Moderator: {moderator}\n"
        f"Reason: {reason}"
    )

    return case_id


def format_duration(seconds):
    seconds = int(seconds)

    days = seconds // 86400
    seconds %= 86400

    hours = seconds // 3600
    seconds %= 3600

    minutes = seconds // 60
    seconds %= 60

    result = []

    if days:
        result.append(f"{days}d")

    if hours:
        result.append(f"{hours}h")

    if minutes:
        result.append(f"{minutes}m")

    if seconds:
        result.append(f"{seconds}s")

    return " ".join(result) or "0s"


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():
    print("=" * 60)
    print(f"Bot: {bot.user}")
    print(f"ID: {bot.user.id}")
    print(f"Servers: {len(bot.guilds)}")
    print("Mega bot is online.")
    print("=" * 60)


# ============================================================
# MEMBER JOIN
# ============================================================

@bot.event
async def on_member_join(member):
    settings = cfg(member.guild.id)

    # Join tracker
    now = time.time()

    tracker = join_tracker[member.guild.id]
    tracker.append(now)

    while tracker and now - tracker[0] > 30:
        tracker.popleft()

    if settings["antiraid"] and len(tracker) >= 10:
        await log_event(
            member.guild,
            "🚨 **Possible raid detected!** "
            f"{len(tracker)} members joined within 30 seconds."
        )

    # Autorole
    role_id = settings["autorole"]

    if role_id:
        role = member.guild.get_role(role_id)

        if role:
            try:
                await member.add_roles(role, reason="Automatic role")
            except discord.HTTPException:
                pass

    # Welcome
    channel_id = settings["welcome_channel"]

    if channel_id:
        channel = member.guild.get_channel(channel_id)

        if channel:
            message = settings["welcome_message"]

            message = message.replace(
                "{user}", member.mention
            ).replace(
                "{username}", member.name
            ).replace(
                "{server}", member.guild.name
            ).replace(
                "{membercount}", str(member.guild.member_count)
            )

            try:
                await channel.send(message)
            except discord.HTTPException:
                pass

    await log_event(
        member.guild,
        f"📥 {member.mention} joined the server."
    )


@bot.event
async def on_member_remove(member):
    settings = cfg(member.guild.id)

    channel_id = settings["goodbye_channel"]

    if channel_id:
        channel = member.guild.get_channel(channel_id)

        if channel:
            message = settings["goodbye_message"]

            message = message.replace(
                "{username}", member.name
            ).replace(
                "{server}", member.guild.name
            )

            try:
                await channel.send(message)
            except discord.HTTPException:
                pass

    await log_event(
        member.guild,
        f"📤 **{member}** left the server."
    )


# ============================================================
# MESSAGE HANDLER
# ============================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if not message.guild:
        await bot.process_commands(message)
        return

    guild = message.guild
    member = message.author
    settings = cfg(guild.id)

    # --------------------------------------------------------
    # Custom commands
    # --------------------------------------------------------

    if message.content.startswith(PREFIX):
        command_name = message.content[len(PREFIX):].split()[0].lower()

        if command_name in custom_commands[guild.id]:
            text = custom_commands[guild.id][command_name]
            text = text.replace("{user}", member.mention)
            text = text.replace("{username}", member.name)

            await message.channel.send(text)

    # --------------------------------------------------------
    # Anti-link
    # --------------------------------------------------------

    if settings["antilink"] and not is_mod(member):

        if "discord.gg/" in message.content.lower():
            try:
                await message.delete()

                await message.channel.send(
                    f"🚫 {member.mention}, Discord invites aren't allowed.",
                    delete_after=5
                )

                await log_event(
                    guild,
                    f"🔗 Deleted Discord invite from {member}."
                )

            except discord.HTTPException:
                pass

    # --------------------------------------------------------
    # Anti-spam
    # --------------------------------------------------------

    if settings["antispam"] and not is_mod(member):

        key = (guild.id, member.id)
        now = time.time()

        tracker = message_tracker[key]
        tracker.append(now)

        while tracker and now - tracker[0] > 7:
            tracker.popleft()

        if len(tracker) >= 7:

            try:
                await member.timeout(
                    timedelta(minutes=1),
                    reason="Automatic anti-spam"
                )

                await message.channel.send(
                    f"🛡️ {member.mention} was timed out "
                    f"for spam.",
                    delete_after=8
                )

                await log_event(
                    guild,
                    f"🛡️ Anti-spam timeout: {member}."
                )

                tracker.clear()

            except discord.HTTPException:
                pass

    # --------------------------------------------------------
    # XP
    # --------------------------------------------------------

    if settings["xp_enabled"]:

        data = profile(guild.id, member.id)
        now = int(time.time())

        if now - data["last_xp"] >= 45:

            earned = random.randint(10, 20)

            data["xp"] += earned
            data["last_xp"] = now

            required = 100 + data["level"] * 50

            if data["xp"] >= required:

                data["xp"] -= required
                data["level"] += 1

                channel_id = settings["level_channel"]

                channel = (
                    guild.get_channel(channel_id)
                    if channel_id
                    else message.channel
                )

                try:
                    await channel.send(
                        f"🎉 {member.mention} reached "
                        f"**Level {data['level']}**!"
                    )
                except discord.HTTPException:
                    pass

    await bot.process_commands(message)


# ============================================================
# BASIC COMMANDS
# ============================================================

@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction):
    ms = round(bot.latency * 1000)

    await interaction.response.send_message(
        f"🏓 Pong! `{ms}ms`"
    )


@bot.tree.command(name="botinfo", description="Show bot information")
async def botinfo(interaction):

    embed = discord.Embed(
        title="🤖 Mega Bot",
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

    embed.add_field(
        name="Commands",
        value=str(len(bot.tree.get_commands()))
    )

    await interaction.response.send_message(embed=embed)


# ============================================================
# FUN COMMANDS
# ============================================================

@bot.tree.command(name="roll", description="Roll a dice")
async def roll(
    interaction,
    sides: app_commands.Range[int, 2, 1000] = 6
):
    result = random.randint(1, sides)

    await interaction.response.send_message(
        f"🎲 {interaction.user.mention} rolled "
        f"**{result}** / {sides}"
    )


@bot.tree.command(name="coinflip", description="Flip a coin")
async def coinflip(interaction):
    await interaction.response.send_message(
        f"🪙 **{random.choice(['Heads', 'Tails'])}!**"
    )


@bot.tree.command(name="8ball", description="Ask the magic 8-ball")
async def eightball(interaction, question: str):

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
        "Without a doubt.",
    ]

    await interaction.response.send_message(
        f"🎱 **Question:** {question}\n"
        f"**Answer:** {random.choice(answers)}"
    )


@bot.tree.command(name="choose", description="Choose an option")
async def choose(interaction, options: str):

    choices = [
        x.strip()
        for x in options.split(",")
        if x.strip()
    ]

    if len(choices) < 2:
        await interaction.response.send_message(
            "❌ Provide at least 2 options separated by commas.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"🤔 I choose **{random.choice(choices)}**!"
    )


@bot.tree.command(name="rate", description="Rate something")
async def rate(interaction, thing: str):

    score = random.randint(0, 100)

    await interaction.response.send_message(
        f"📊 I rate **{thing}** **{score}/100**."
    )


@bot.tree.command(name="ship", description="Ship two members")
async def ship(
    interaction,
    user1: discord.Member,
    user2: discord.Member
):

    score = random.randint(0, 100)

    await interaction.response.send_message(
        f"❤️ {user1.mention} + {user2.mention} "
        f"= **{score}%** compatibility."
    )


@bot.tree.command(name="mock", description="Mock some text")
async def mock(interaction, text: str):

    result = "".join(
        char.upper() if i % 2 else char.lower()
        for i, char in enumerate(text)
    )

    await interaction.response.send_message(result)


# ============================================================
# USER COMMANDS
# ============================================================

@bot.tree.command(name="avatar", description="Show a user's avatar")
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


@bot.tree.command(name="userinfo", description="Show user information")
async def userinfo(
    interaction,
    member: discord.Member = None
):

    member = member or interaction.user
    data = profile(interaction.guild.id, member.id)

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
        value=str(data["level"])
    )

    embed.add_field(
        name="XP",
        value=str(data["xp"])
    )

    embed.add_field(
        name="Coins",
        value=str(data["coins"])
    )

    embed.add_field(
        name="Warnings",
        value=str(len(data["warnings"]))
    )

    embed.add_field(
        name="Reputation",
        value=str(data["rep"])
    )

    await interaction.response.send_message(
        embed=embed
    )


@bot.tree.command(name="serverinfo", description="Show server information")
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

    embed.add_field(
        name="Boosts",
        value=str(guild.premium_subscription_count)
    )

    embed.add_field(
        name="Owner",
        value=str(guild.owner)
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# MODERATION
# ============================================================

@bot.tree.command(name="clear", description="Delete messages")
@app_commands.checks.has_permissions(manage_messages=True)
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

    await log_event(
        interaction.guild,
        f"🧹 {interaction.user} deleted "
        f"{len(deleted)} messages."
    )


@bot.tree.command(name="kick", description="Kick a member")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(
    interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    if member == interaction.user:
        await interaction.response.send_message(
            "❌ You cannot kick yourself.",
            ephemeral=True
        )
        return

    await member.kick(reason=reason)

    case = await add_case(
        interaction.guild,
        "KICK",
        str(member),
        str(interaction.user),
        reason
    )

    await interaction.response.send_message(
        f"👢 **{member}** was kicked.\n"
        f"Case: `#{case}`\n"
        f"Reason: {reason}"
    )


@bot.tree.command(name="ban", description="Ban a member")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(
    interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    if member == interaction.user:
        await interaction.response.send_message(
            "❌ You cannot ban yourself.",
            ephemeral=True
        )
        return

    await member.ban(reason=reason)

    case = await add_case(
        interaction.guild,
        "BAN",
        str(member),
        str(interaction.user),
        reason
    )

    await interaction.response.send_message(
        f"🔨 **{member}** was banned.\n"
        f"Case: `#{case}`\n"
        f"Reason: {reason}"
    )


@bot.tree.command(name="unban", description="Unban a user")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction, user_id: str):

    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)

        await interaction.response.send_message(
            f"🔓 Unbanned **{user}**."
        )

    except Exception:
        await interaction.response.send_message(
            "❌ Could not unban that user.",
            ephemeral=True
        )


@bot.tree.command(name="timeout", description="Timeout a member")
@app_commands.checks.has_permissions(moderate_members=True)
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

    case = await add_case(
        interaction.guild,
        "TIMEOUT",
        str(member),
        str(interaction.user),
        reason
    )

    await interaction.response.send_message(
        f"⏱️ {member.mention} timed out for "
        f"**{minutes} minutes**.\n"
        f"Case: `#{case}`"
    )


@bot.tree.command(name="untimeout", description="Remove timeout")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout(interaction, member: discord.Member):

    await member.timeout(None)

    await interaction.response.send_message(
        f"🔓 Removed timeout from {member.mention}."
    )


@bot.tree.command(name="warn", description="Warn a member")
@app_commands.checks.has_permissions(manage_messages=True)
async def warn(
    interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    data = profile(
        interaction.guild.id,
        member.id
    )

    data["warnings"].append({
        "reason": reason,
        "moderator": interaction.user.id,
        "time": int(time.time())
    })

    case = await add_case(
        interaction.guild,
        "WARN",
        str(member),
        str(interaction.user),
        reason
    )

    count = len(data["warnings"])

    # Escalation
    if count >= 3:

        try:
            await member.timeout(
                timedelta(minutes=10),
                reason="Reached 3 warnings"
            )

            escalation = (
                "\n⏱️ Automatic 10-minute timeout "
                "applied at 3 warnings."
            )

        except discord.HTTPException:
            escalation = ""

    else:
        escalation = ""

    await interaction.response.send_message(
        f"⚠️ {member.mention} warned.\n"
        f"Warnings: **{count}**\n"
        f"Case: `#{case}`\n"
        f"Reason: {reason}"
        f"{escalation}"
    )


@bot.tree.command(name="warnings", description="View warnings")
@app_commands.checks.has_permissions(manage_messages=True)
async def warnings(
    interaction,
    member: discord.Member
):

    data = profile(
        interaction.guild.id,
        member.id
    )

    if not data["warnings"]:
        await interaction.response.send_message(
            f"✅ {member.mention} has no warnings."
        )
        return

    text = []

    for i, warning in enumerate(
        data["warnings"],
        1
    ):
        text.append(
            f"**{i}.** {warning['reason']}"
        )

    await interaction.response.send_message(
        f"⚠️ **{member} warnings**\n\n"
        + "\n".join(text[:20])
    )


@bot.tree.command(name="clearwarnings", description="Clear warnings")
@app_commands.checks.has_permissions(manage_messages=True)
async def clearwarnings(
    interaction,
    member: discord.Member
):

    data = profile(
        interaction.guild.id,
        member.id
    )

    data["warnings"].clear()

    await interaction.response.send_message(
        f"✅ Cleared warnings for {member.mention}."
    )


@bot.tree.command(name="history", description="Show moderation history")
@app_commands.checks.has_permissions(manage_messages=True)
async def history(
    interaction,
    member: discord.Member
):

    records = [
        x for x in cases[interaction.guild.id]
        if x["target"] == str(member)
    ]

    if not records:
        await interaction.response.send_message(
            "No moderation history found."
        )
        return

    text = []

    for record in records[-15:]:
        text.append(
            f"`#{record['id']}` "
            f"**{record['action']}** — "
            f"{record['reason']}"
        )

    await interaction.response.send_message(
        "\n".join(text)
    )


@bot.tree.command(name="slowmode", description="Set slowmode")
@app_commands.checks.has_permissions(manage_channels=True)
async def slowmode(
    interaction,
    seconds: app_commands.Range[int, 0, 21600]
):

    await interaction.channel.edit(
        slowmode_delay=seconds
    )

    await interaction.response.send_message(
        f"🐌 Slowmode set to **{seconds} seconds**."
    )


@bot.tree.command(name="lock", description="Lock channel")
@app_commands.checks.has_permissions(manage_channels=True)
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


@bot.tree.command(name="unlock", description="Unlock channel")
@app_commands.checks.has_permissions(manage_channels=True)
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


@bot.tree.command(name="lockdown", description="Lock all text channels")
@app_commands.checks.has_permissions(administrator=True)
async def lockdown(interaction):

    await interaction.response.defer()

    count = 0

    for channel in interaction.guild.text_channels:

        try:
            overwrite = channel.overwrites_for(
                interaction.guild.default_role
            )

            overwrite.send_messages = False

            await channel.set_permissions(
                interaction.guild.default_role,
                overwrite=overwrite
            )

            count += 1

        except discord.HTTPException:
            pass

    await interaction.followup.send(
        f"🔒 Locked **{count}** text channels."
    )


@bot.tree.command(name="unlockdown", description="Unlock all text channels")
@app_commands.checks.has_permissions(administrator=True)
async def unlockdown(interaction):

    await interaction.response.defer()

    count = 0

    for channel in interaction.guild.text_channels:

        try:
            overwrite = channel.overwrites_for(
                interaction.guild.default_role
            )

            overwrite.send_messages = None

            await channel.set_permissions(
                interaction.guild.default_role,
                overwrite=overwrite
            )

            count += 1

        except discord.HTTPException:
            pass

    await interaction.followup.send(
        f"🔓 Unlocked **{count}** text channels."
    )


# ============================================================
# CASE COMMAND
# ============================================================

@bot.tree.command(name="case", description="View a moderation case")
@app_commands.checks.has_permissions(manage_messages=True)
async def case(
    interaction,
    case_id: int
):

    records = cases[interaction.guild.id]

    record = next(
        (x for x in records if x["id"] == case_id),
        None
    )

    if not record:
        await interaction.response.send_message(
            "❌ Case not found.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"📋 Case #{case_id}",
        color=discord.Color.orange()
    )

    embed.add_field(
        name="Action",
        value=record["action"]
    )

    embed.add_field(
        name="Target",
        value=record["target"]
    )

    embed.add_field(
        name="Moderator",
        value=record["moderator"]
    )

    embed.add_field(
        name="Reason",
        value=record["reason"],
        inline=False
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# ECONOMY
# ============================================================

@bot.tree.command(name="balance", description="Check your coins")
async def balance(interaction):

    data = profile(
        interaction.guild.id,
        interaction.user.id
    )

    await interaction.response.send_message(
        f"💰 {interaction.user.mention} has "
        f"**{data['coins']} coins**."
    )


@bot.tree.command(name="daily", description="Claim daily coins")
async def daily(interaction):

    data = profile(
        interaction.guild.id,
        interaction.user.id
    )

    now = int(time.time())

    if now - data["last_daily"] < 86400:

        remaining = 86400 - (
            now - data["last_daily"]
        )

        await interaction.response.send_message(
            f"⏳ Come back in "
            f"**{format_duration(remaining)}**.",
            ephemeral=True
        )

        return

    reward = random.randint(250, 750)

    data["coins"] += reward
    data["last_daily"] = now

    await interaction.response.send_message(
        f"💰 Daily reward: **{reward} coins**!"
    )


@bot.tree.command(name="work", description="Work for coins")
async def work(interaction):

    data = profile(
        interaction.guild.id,
        interaction.user.id
    )

    now = int(time.time())

    if now - data["last_work"] < 30:

        await interaction.response.send_message(
            "⏳ You need to wait before working again.",
            ephemeral=True
        )

        return

    jobs = [
        "programmer",
        "YouTuber",
        "game developer",
        "streamer",
        "pizza delivery driver",
        "Discord moderator",
        "shopkeeper",
        "designer",
        "musician",
    ]

    reward = random.randint(50, 250)

    data["coins"] += reward
    data["last_work"] = now

    await interaction.response.send_message(
        f"💼 You worked as a **{random.choice(jobs)}** "
        f"and earned **{reward} coins**."
    )


@bot.tree.command(name="beg", description="Beg for coins")
async def beg(interaction):

    data = profile(
        interaction.guild.id,
        interaction.user.id
    )

    now = int(time.time())

    if now - data["last_beg"] < 20:

        await interaction.response.send_message(
            "⏳ Try again later.",
            ephemeral=True
        )

        return

    data["last_beg"] = now

    if random.random() < 0.25:

        await interaction.response.send_message(
            "💀 Nobody gave you anything."
        )

        return

    amount = random.randint(10, 100)
    data["coins"] += amount

    await interaction.response.send_message(
        f"🪙 Someone gave you **{amount} coins**!"
    )


@bot.tree.command(name="give", description="Give coins")
async def give(
    interaction,
    member: discord.Member,
    amount: app_commands.Range[int, 1, 1000000]
):

    sender = profile(
        interaction.guild.id,
        interaction.user.id
    )

    receiver = profile(
        interaction.guild.id,
        member.id
    )

    if sender["coins"] < amount:

        await interaction.response.send_message(
            "❌ You don't have enough coins.",
            ephemeral=True
        )

        return

    sender["coins"] -= amount
    receiver["coins"] += amount

    await interaction.response.send_message(
        f"💸 Sent **{amount} coins** to {member.mention}."
    )


@bot.tree.command(name="richest", description="Show richest users")
async def richest(interaction):

    entries = []

    for (guild_id, user_id), data in users.items():

        if guild_id != interaction.guild.id:
            continue

        member = interaction.guild.get_member(user_id)

        if member:
            entries.append(
                (member, data["coins"])
            )

    entries.sort(
        key=lambda x: x[1],
        reverse=True
    )

    if not entries:
        await interaction.response.send_message(
            "No economy data yet."
        )
        return

    text = []

    for i, (member, coins) in enumerate(
        entries[:10],
        1
    ):
        text.append(
            f"**{i}.** {member.mention} — "
            f"💰 {coins}"
        )

    await interaction.response.send_message(
        "🏆 **Richest Users**\n\n" +
        "\n".join(text)
    )


# ============================================================
# LEVELING
# ============================================================

@bot.tree.command(name="rank", description="Show your level")
async def rank(interaction):

    data = profile(
        interaction.guild.id,
        interaction.user.id
    )

    required = 100 + data["level"] * 50

    await interaction.response.send_message(
        f"⭐ **{interaction.user.display_name}**\n"
        f"Level: **{data['level']}**\n"
        f"XP: **{data['xp']} / {required}**"
    )


@bot.tree.command(name="leaderboard", description="XP leaderboard")
async def leaderboard(interaction):

    entries = []

    for (guild_id, user_id), data in users.items():

        if guild_id != interaction.guild.id:
            continue

        member = interaction.guild.get_member(user_id)

        if member:
            entries.append(
                (member, data["level"], data["xp"])
            )

    entries.sort(
        key=lambda x: (x[1], x[2]),
        reverse=True
    )

    text = []

    for i, (member, level, xp) in enumerate(
        entries[:10],
        1
    ):
        text.append(
            f"**{i}.** {member.mention} — "
            f"Level {level} ({xp} XP)"
        )

    await interaction.response.send_message(
        "🏆 **Level Leaderboard**\n\n" +
        ("\n".join(text) if text else "No data yet.")
    )


# ============================================================
# REPUTATION
# ============================================================

@bot.tree.command(name="rep", description="Give someone reputation")
async def rep(
    interaction,
    member: discord.Member
):

    if member == interaction.user:
        await interaction.response.send_message(
            "❌ You can't give yourself reputation.",
            ephemeral=True
        )
        return

    data = profile(
        interaction.guild.id,
        member.id
    )

    data["rep"] += 1

    await interaction.response.send_message(
        f"❤️ {interaction.user.mention} gave "
        f"{member.mention} **+1 reputation**."
    )


@bot.tree.command(name="reputation", description="Check reputation")
async def reputation(
    interaction,
    member: discord.Member = None
):

    member = member or interaction.user

    data = profile(
        interaction.guild.id,
        member.id
    )

    await interaction.response.send_message(
        f"❤️ {member.mention} has "
        f"**{data['rep']} reputation**."
    )


# ============================================================
# POLLS
# ============================================================

@bot.tree.command(name="poll", description="Create a poll")
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

    if not 2 <= len(choices) <= 10:

        await interaction.response.send_message(
            "❌ Use between 2 and 10 options.",
            ephemeral=True
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

        try:
            await message.add_reaction(
                emojis[i]
            )
        except discord.HTTPException:
            pass


# ============================================================
# REMINDERS
# ============================================================

@bot.tree.command(name="remind", description="Create a reminder")
async def remind(
    interaction,
    minutes: app_commands.Range[int, 1, 10080],
    message: str
):

    reminder_id = random.randint(
        100000,
        999999
    )

    reminders[reminder_id] = {
        "user_id": interaction.user.id,
        "channel_id": interaction.channel.id,
        "message": message,
        "time": time.time() + minutes * 60,
    }

    await interaction.response.send_message(
        f"⏰ Reminder created: `{reminder_id}`\n"
        f"Time: **{minutes} minutes**"
    )


@tasks.loop(seconds=5)
async def reminder_loop():

    now = time.time()

    expired = []

    for reminder_id, reminder in reminders.items():

        if now >= reminder["time"]:

            channel = bot.get_channel(
                reminder["channel_id"]
            )

            if channel:

                try:
                    await channel.send(
                        f"⏰ <@{reminder['user_id']}> "
                        f"Reminder: **{reminder['message']}**"
                    )
                except discord.HTTPException:
                    pass

            expired.append(reminder_id)

    for reminder_id in expired:
        reminders.pop(reminder_id, None)


# ============================================================
# TICKET SYSTEM
# ============================================================

class TicketPanelView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Create Ticket",
        emoji="🎫",
        style=discord.ButtonStyle.green,
        custom_id="mega_create_ticket"
    )
    async def create_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        guild = interaction.guild
        user = interaction.user

        existing = tickets.get(
            (guild.id, user.id)
        )

        if existing:

            channel = guild.get_channel(existing)

            if channel:

                await interaction.response.send_message(
                    f"❌ You already have {channel.mention}.",
                    ephemeral=True
                )

                return

        settings = cfg(guild.id)

        category = None

        if settings["ticket_category"]:
            category = guild.get_channel(
                settings["ticket_category"]
            )

        overwrites = {
            guild.default_role:
                discord.PermissionOverwrite(
                    view_channel=False
                ),

            user:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                ),

            guild.me:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_channels=True
                )
        }

        channel = await guild.create_text_channel(
            f"ticket-{user.name}",
            category=category,
            overwrites=overwrites
        )

        tickets[(guild.id, user.id)] = channel.id

        embed = discord.Embed(
            title="🎫 Support Ticket",
            description=(
                f"Welcome {user.mention}!\n\n"
                "Explain your issue here.\n"
                "A staff member will assist you."
            ),
            color=discord.Color.blurple()
        )

        await channel.send(
            embed=embed,
            view=TicketCloseView()
        )

        await interaction.response.send_message(
            f"🎫 Ticket created: {channel.mention}",
            ephemeral=True
        )


class TicketCloseView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Close Ticket",
        emoji="🔒",
        style=discord.ButtonStyle.red,
        custom_id="mega_close_ticket"
    )
    async def close_ticket(
        self,
        interaction,
        button
    ):

        if not is_mod(interaction.user):

            await interaction.response.send_message(
                "❌ You need staff permissions.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            "🔒 Closing ticket in 5 seconds..."
        )

        await asyncio.sleep(5)

        for key, channel_id in list(
            tickets.items()
        ):

            if channel_id == interaction.channel.id:
                tickets.pop(key, None)

        try:
            await interaction.channel.delete()
        except discord.HTTPException:
            pass


@bot.tree.command(
    name="ticketpanel",
    description="Create a ticket panel"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def ticketpanel(interaction):

    embed = discord.Embed(
        title="🎫 Support",
        description=(
            "Need help?\n\n"
            "Click the button below to create a "
            "private support ticket."
        ),
        color=discord.Color.blurple()
    )

    await interaction.response.send_message(
        embed=embed,
        view=TicketPanelView()
    )


# ============================================================
# GIVEAWAYS
# ============================================================

class GiveawayView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Enter",
        emoji="🎉",
        style=discord.ButtonStyle.green,
        custom_id="mega_giveaway_enter"
    )
    async def enter(
        self,
        interaction,
        button
    ):

        giveaway = giveaways.get(
            interaction.message.id
        )

        if not giveaway:

            await interaction.response.send_message(
                "❌ This giveaway has expired.",
                ephemeral=True
            )

            return

        giveaway["entries"].add(
            interaction.user.id
        )

        await interaction.response.send_message(
            "🎉 You entered the giveaway!",
            ephemeral=True
        )


@bot.tree.command(
    name="giveaway",
    description="Start a giveaway"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway(
    interaction,
    minutes: app_commands.Range[int, 1, 10080],
    winners: app_commands.Range[int, 1, 20],
    prize: str
):

    end = time.time() + minutes * 60

    embed = discord.Embed(
        title="🎉 GIVEAWAY",
        description=(
            f"**Prize:** {prize}\n"
            f"**Winners:** {winners}\n\n"
            f"Ends <t:{int(end)}:R>\n\n"
            "Click **Enter** below!"
        ),
        color=discord.Color.gold()
    )

    await interaction.response.send_message(
        embed=embed,
        view=GiveawayView()
    )

    message = await interaction.original_response()

    giveaways[message.id] = {
        "channel_id": interaction.channel.id,
        "guild_id": interaction.guild.id,
        "prize": prize,
        "winners": winners,
        "end": end,
        "entries": set(),
    }


@tasks.loop(seconds=10)
async def giveaway_loop():

    now = time.time()

    expired = []

    for message_id, giveaway in giveaways.items():

        if now < giveaway["end"]:
            continue

        channel = bot.get_channel(
            giveaway["channel_id"]
        )

        if channel:

            entries = list(
                giveaway["entries"]
            )

            if entries:

                amount = min(
                    giveaway["winners"],
                    len(entries)
                )

                selected = random.sample(
                    entries,
                    amount
                )

                mentions = []

                for user_id in selected:
                    mentions.append(
                        f"<@{user_id}>"
                    )

                await channel.send(
                    f"🎉 Congratulations "
                    f"{', '.join(mentions)}!\n"
                    f"You won **{giveaway['prize']}**!"
                )

            else:

                await channel.send(
                    "🎉 Giveaway ended with no entries."
                )

        expired.append(message_id)

    for message_id in expired:
        giveaways.pop(message_id, None)


# ============================================================
# VERIFICATION
# ============================================================

class VerificationView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Verify",
        emoji="✅",
        style=discord.ButtonStyle.green,
        custom_id="mega_verify"
    )
    async def verify(
        self,
        interaction,
        button
    ):

        role_id = cfg(
            interaction.guild.id
        )["verification_role"]

        if not role_id:

            await interaction.response.send_message(
                "❌ Verification role hasn't been configured.",
                ephemeral=True
            )

            return

        role = interaction.guild.get_role(
            role_id
        )

        if not role:

            await interaction.response.send_message(
                "❌ Verification role no longer exists.",
                ephemeral=True
            )

            return

        try:

            await interaction.user.add_roles(
                role,
                reason="Verification"
            )

            await interaction.response.send_message(
                "✅ You are verified!",
                ephemeral=True
            )

        except discord.HTTPException:

            await interaction.response.send_message(
                "❌ I couldn't give you the role.",
                ephemeral=True
            )


@bot.tree.command(
    name="verification",
    description="Create verification panel"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def verification(interaction):

    embed = discord.Embed(
        title="🛡️ Verification",
        description=(
            "Click **Verify** below to receive "
            "the verified role."
        ),
        color=discord.Color.green()
    )

    await interaction.response.send_message(
        embed=embed,
        view=VerificationView()
    )


# ============================================================
# SETUP COMMANDS
# ============================================================

@bot.tree.command(
    name="setlog",
    description="Set logging channel"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def setlog(
    interaction,
    channel: discord.TextChannel
):

    cfg(interaction.guild.id)[
        "log_channel"
    ] = channel.id

    await interaction.response.send_message(
        f"📋 Log channel: {channel.mention}"
    )


@bot.tree.command(
    name="setwelcome",
    description="Set welcome channel"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def setwelcome(
    interaction,
    channel: discord.TextChannel
):

    cfg(interaction.guild.id)[
        "welcome_channel"
    ] = channel.id

    await interaction.response.send_message(
        f"👋 Welcome channel: {channel.mention}"
    )


@bot.tree.command(
    name="setgoodbye",
    description="Set goodbye channel"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def setgoodbye(
    interaction,
    channel: discord.TextChannel
):

    cfg(interaction.guild.id)[
        "goodbye_channel"
    ] = channel.id

    await interaction.response.send_message(
        f"👋 Goodbye channel: {channel.mention}"
    )


@bot.tree.command(
    name="setautorole",
    description="Set automatic member role"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def setautorole(
    interaction,
    role: discord.Role
):

    cfg(interaction.guild.id)[
        "autorole"
    ] = role.id

    await interaction.response.send_message(
        f"🎭 Auto-role: {role.mention}"
    )


@bot.tree.command(
    name="setmodrole",
    description="Set moderator role"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def setmodrole(
    interaction,
    role: discord.Role
):

    cfg(interaction.guild.id)[
        "mod_role"
    ] = role.id

    await interaction.response.send_message(
        f"🛡️ Moderator role: {role.mention}"
    )


@bot.tree.command(
    name="setverificationrole",
    description="Set verification role"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def setverificationrole(
    interaction,
    role: discord.Role
):

    cfg(interaction.guild.id)[
        "verification_role"
    ] = role.id

    await interaction.response.send_message(
        f"✅ Verification role: {role.mention}"
    )


@bot.tree.command(
    name="setlevelchannel",
    description="Set level-up channel"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def setlevelchannel(
    interaction,
    channel: discord.TextChannel
):

    cfg(interaction.guild.id)[
        "level_channel"
    ] = channel.id

    await interaction.response.send_message(
        f"⭐ Level channel: {channel.mention}"
    )


# ============================================================
# SECURITY SETTINGS
# ============================================================

@bot.tree.command(
    name="antispam",
    description="Enable or disable anti-spam"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def antispam(
    interaction,
    enabled: bool
):

    cfg(interaction.guild.id)[
        "antispam"
    ] = enabled

    await interaction.response.send_message(
        f"🛡️ Anti-spam: **{'ON' if enabled else 'OFF'}**"
    )


@bot.tree.command(
    name="antilink",
    description="Enable or disable invite filtering"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def antilink(
    interaction,
    enabled: bool
):

    cfg(interaction.guild.id)[
        "antilink"
    ] = enabled

    await interaction.response.send_message(
        f"🔗 Anti-invite: **{'ON' if enabled else 'OFF'}**"
    )


@bot.tree.command(
    name="antiraid",
    description="Enable or disable raid detection"
)
@app_commands.checks.has_permissions(administrator=True)
async def antiraid(
    interaction,
    enabled: bool
):

    cfg(interaction.guild.id)[
        "antiraid"
    ] = enabled

    await interaction.response.send_message(
        f"🚨 Anti-raid: **{'ON' if enabled else 'OFF'}**"
    )


# ============================================================
# CUSTOM COMMANDS
# ============================================================

@bot.tree.command(
    name="customcommand",
    description="Create a custom command"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def customcommand(
    interaction,
    name: str,
    response: str
):

    name = name.lower().strip()

    custom_commands[
        interaction.guild.id
    ][name] = response

    await interaction.response.send_message(
        f"✅ Custom command `!{name}` created."
    )


@bot.tree.command(
    name="deletecustomcommand",
    description="Delete a custom command"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def deletecustomcommand(
    interaction,
    name: str
):

    name = name.lower()

    if name not in custom_commands[
        interaction.guild.id
    ]:

        await interaction.response.send_message(
            "❌ That command doesn't exist.",
            ephemeral=True
        )

        return

    del custom_commands[
        interaction.guild.id
    ][name]

    await interaction.response.send_message(
        f"🗑️ Deleted `!{name}`."
    )


# ============================================================
# TEMPORARY VOICE CHANNELS
# ============================================================

@bot.tree.command(
    name="tempvoice",
    description="Create a temporary voice channel"
)
async def tempvoice(interaction):

    guild = interaction.guild

    channel = await guild.create_voice_channel(
        f"🔊 {interaction.user.name}'s room"
    )

    temporary_voice_channels.add(
        channel.id
    )

    try:
        await interaction.user.move_to(channel)
    except discord.HTTPException:
        pass

    await interaction.response.send_message(
        f"🔊 Created {channel.mention}.",
        ephemeral=True
    )


@bot.event
async def on_voice_state_update(
    member,
    before,
    after
):

    if (
        before.channel
        and before.channel.id in temporary_voice_channels
        and len(before.channel.members) == 0
    ):

        channel_id = before.channel.id

        try:
            await before.channel.delete()
        except discord.HTTPException:
            pass

        temporary_voice_channels.discard(
            channel_id
        )


# ============================================================
# HELP
# ============================================================

@bot.tree.command(
    name="help",
    description="Show bot commands"
)
async def help_command(interaction):

    embed = discord.Embed(
        title="🤖 Mega Bot",
        description="All available command categories",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🛡️ Moderation",
        value=(
            "`/ban` `/unban` `/kick`\n"
            "`/timeout` `/untimeout`\n"
            "`/warn` `/warnings`\n"
            "`/clearwarnings` `/history`\n"
            "`/case` `/clear`\n"
            "`/lock` `/unlock`\n"
            "`/lockdown` `/unlockdown`\n"
            "`/slowmode`"
        ),
        inline=False
    )

    embed.add_field(
        name="💰 Economy",
        value=(
            "`/balance` `/daily` `/work`\n"
            "`/beg` `/give` `/richest`"
        ),
        inline=False
    )

    embed.add_field(
        name="⭐ Levels",
        value="`/rank` `/leaderboard`",
        inline=True
    )

    embed.add_field(
        name="❤️ Social",
        value="`/rep` `/reputation`",
        inline=True
    )

    embed.add_field(
        name="🎮 Fun",
        value=(
            "`/roll` `/coinflip` `/8ball`\n"
            "`/choose` `/rate` `/ship` `/mock`"
        ),
        inline=False
    )

    embed.add_field(
        name="🎫 Server",
        value=(
            "`/ticketpanel` `/giveaway`\n"
            "`/poll` `/verification`\n"
            "`/tempvoice`"
        ),
        inline=False
    )

    embed.add_field(
        name="⚙️ Configuration",
        value=(
            "`/setlog` `/setwelcome` `/setgoodbye`\n"
            "`/setautorole` `/setmodrole`\n"
            "`/setverificationrole` `/setlevelchannel`\n"
            "`/antispam` `/antilink` `/antiraid`\n"
            "`/customcommand` `/deletecustomcommand`"
        ),
        inline=False
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# ERROR HANDLER
# ============================================================

@bot.tree.error
async def command_error(
    interaction,
    error
):

    print(
        f"Command error: {repr(error)}"
    )

    if isinstance(
        error,
        app_commands.MissingPermissions
    ):

        message = (
            "❌ You don't have permission "
            "to use that command."
        )

    elif isinstance(
        error,
        app_commands.BotMissingPermissions
    ):

        message = (
            "❌ I don't have the permissions "
            "required for that."
        )

    elif isinstance(
        error,
        app_commands.CommandOnCooldown
    ):

        message = (
            "⏳ You're using that command "
            "too quickly."
        )

    else:

        message = (
            "❌ An error occurred. "
            "Check the Railway logs for details."
        )

    try:

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

    except discord.HTTPException:
        pass


# ============================================================
# RUN
# ============================================================

print("Starting Mega Discord Bot...")

bot.run(TOKEN)
