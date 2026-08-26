import os
import time
import random
import asyncio
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks


# ============================================================
# NORMAL BOT JUNIOR
# One-file Discord bot
# External package: discord.py only
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID_RAW = os.getenv("OWNER_ID")

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN is missing from Railway Variables."
    )

if not OWNER_ID_RAW:
    raise RuntimeError(
        "OWNER_ID is missing from Railway Variables."
    )

try:
    OWNER_ID = int(OWNER_ID_RAW)
except ValueError:
    raise RuntimeError(
        "OWNER_ID must be your numeric Discord user ID."
    )


# ============================================================
# INTENTS
# ============================================================

intents = discord.Intents.default()

# Required for member join/leave and member information
intents.members = True

# Required for message-based security/XP features
intents.message_content = True


# ============================================================
# DATA
# No database = resets when Railway restarts
# ============================================================

guild_data = defaultdict(lambda: {
    "log_channel": None,
    "welcome_channel": None,
    "goodbye_channel": None,
    "level_channel": None,

    "autorole": None,
    "mod_role": None,
    "verification_role": None,

    "antispam": True,
    "antilink": False,
    "antiraid": False,
    "antimention": True,

    "welcome_message":
        "Welcome {user} to **{server}**!",

    "goodbye_message":
        "**{username}** left the server."
})

user_data = defaultdict(lambda: {
    "xp": 0,
    "level": 0,
    "coins": 0,
    "rep": 0,

    "warnings": [],

    "last_xp": 0,
    "last_daily": 0,
    "last_weekly": 0,
    "last_work": 0,
    "last_beg": 0,
    "last_crime": 0,
    "last_rob": 0
})

cases = defaultdict(list)

reminders = {}

giveaways = {}

tickets = {}

temp_voice_channels = set()

message_tracker = defaultdict(deque)

join_tracker = defaultdict(deque)


# ============================================================
# HELPERS
# ============================================================

def config(guild_id):
    return guild_data[guild_id]


def profile(guild_id, user_id):
    return user_data[(guild_id, user_id)]


def is_owner(user):
    return user.id == OWNER_ID


def is_staff(member):
    if member.guild_permissions.administrator:
        return True

    if member.guild_permissions.manage_messages:
        return True

    role_id = config(member.guild.id)["mod_role"]

    if role_id:
        role = member.guild.get_role(role_id)

        if role and role in member.roles:
            return True

    return False


def format_time(seconds):
    seconds = max(0, int(seconds))

    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    parts = []

    if days:
        parts.append(f"{days}d")

    if hours:
        parts.append(f"{hours}h")

    if minutes:
        parts.append(f"{minutes}m")

    if seconds:
        parts.append(f"{seconds}s")

    return " ".join(parts) or "0s"


async def log_action(guild, text):
    channel_id = config(guild.id)["log_channel"]

    if not channel_id:
        return

    channel = guild.get_channel(channel_id)

    if not channel:
        return

    try:
        await channel.send(text)
    except discord.HTTPException:
        pass


async def create_case(
    guild,
    action,
    target,
    moderator,
    reason
):
    number = len(cases[guild.id]) + 1

    case = {
        "id": number,
        "action": action,
        "target": str(target),
        "moderator": str(moderator),
        "reason": reason,
        "time": int(time.time())
    }

    cases[guild.id].append(case)

    await log_action(
        guild,
        f"📋 **Case #{number}**\n"
        f"Action: `{action}`\n"
        f"Target: `{target}`\n"
        f"Moderator: `{moderator}`\n"
        f"Reason: {reason}"
    )

    return number


# ============================================================
# BOT
# ============================================================

class NormalBotJunior(commands.Bot):

    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

        self.started_tasks = False

    async def setup_hook(self):

        # Register persistent buttons BEFORE connecting.
        self.add_view(TicketPanelView())
        self.add_view(TicketCloseView())
        self.add_view(VerificationView())
        self.add_view(GiveawayView())

        # Sync slash commands.
        synced = await self.tree.sync()

        print(
            f"Synced {len(synced)} slash commands."
        )

        # Start background tasks exactly once.
        if not self.started_tasks:

            self.reminder_loop.start()
            self.giveaway_loop.start()

            self.started_tasks = True

    @tasks.loop(seconds=5)
    async def reminder_loop(self):

        now = time.time()
        expired = []

        for reminder_id, reminder in list(
            reminders.items()
        ):

            if now < reminder["time"]:
                continue

            channel = self.get_channel(
                reminder["channel_id"]
            )

            if channel:

                try:
                    await channel.send(
                        f"⏰ <@{reminder['user_id']}> "
                        f"**Reminder:** "
                        f"{reminder['message']}"
                    )
                except discord.HTTPException:
                    pass

            expired.append(reminder_id)

        for reminder_id in expired:
            reminders.pop(reminder_id, None)

    @tasks.loop(seconds=5)
    async def giveaway_loop(self):

        now = time.time()
        finished = []

        for message_id, giveaway in list(
            giveaways.items()
        ):

            if now < giveaway["end"]:
                continue

            channel = self.get_channel(
                giveaway["channel_id"]
            )

            if channel:

                entries = list(
                    giveaway["entries"]
                )

                if entries:

                    count = min(
                        giveaway["winners"],
                        len(entries)
                    )

                    winners = random.sample(
                        entries,
                        count
                    )

                    mentions = " ".join(
                        f"<@{user_id}>"
                        for user_id in winners
                    )

                    await channel.send(
                        f"🎉 **Giveaway ended!**\n"
                        f"Prize: **{giveaway['prize']}**\n"
                        f"Winner(s): {mentions}"
                    )

                else:

                    await channel.send(
                        f"🎉 Giveaway for "
                        f"**{giveaway['prize']}** "
                        f"ended with no entries."
                    )

            finished.append(message_id)

        for message_id in finished:
            giveaways.pop(message_id, None)


bot = NormalBotJunior()


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():

    print()
    print("=" * 55)
    print("NORMAL BOT JUNIOR")
    print("=" * 55)
    print(f"Logged in as: {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    print(f"Servers: {len(bot.guilds)}")
    print("=" * 55)
    print()


# ============================================================
# MEMBER EVENTS
# ============================================================

@bot.event
async def on_member_join(member):

    guild = member.guild
    settings = config(guild.id)

    # -----------------------------
    # Anti-raid detection
    # -----------------------------

    now = time.time()

    joins = join_tracker[guild.id]

    joins.append(now)

    while joins and now - joins[0] > 30:
        joins.popleft()

    if settings["antiraid"] and len(joins) >= 10:

        await log_action(
            guild,
            f"🚨 **Possible raid detected.** "
            f"{len(joins)} members joined "
            f"within 30 seconds."
        )

    # -----------------------------
    # Autorole
    # -----------------------------

    role_id = settings["autorole"]

    if role_id:

        role = guild.get_role(role_id)

        if role:

            try:
                await member.add_roles(
                    role,
                    reason="Normal Bot Junior autorole"
                )
            except discord.HTTPException:
                pass

    # -----------------------------
    # Welcome
    # -----------------------------

    channel_id = settings["welcome_channel"]

    if channel_id:

        channel = guild.get_channel(
            channel_id
        )

        if channel:

            message = settings[
                "welcome_message"
            ]

            message = message.replace(
                "{user}",
                member.mention
            )

            message = message.replace(
                "{username}",
                member.name
            )

            message = message.replace(
                "{server}",
                guild.name
            )

            message = message.replace(
                "{membercount}",
                str(guild.member_count)
            )

            try:
                await channel.send(message)
            except discord.HTTPException:
                pass

    await log_action(
        guild,
        f"📥 **{member}** joined."
    )


@bot.event
async def on_member_remove(member):

    guild = member.guild
    settings = config(guild.id)

    channel_id = settings["goodbye_channel"]

    if channel_id:

        channel = guild.get_channel(
            channel_id
        )

        if channel:

            message = settings[
                "goodbye_message"
            ]

            message = message.replace(
                "{username}",
                member.name
            )

            message = message.replace(
                "{server}",
                guild.name
            )

            try:
                await channel.send(message)
            except discord.HTTPException:
                pass

    await log_action(
        guild,
        f"📤 **{member}** left."
    )


# ============================================================
# MESSAGE HANDLER
# ============================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if not message.guild:
        return

    guild = message.guild
    member = message.author
    settings = config(guild.id)

    # -----------------------------
    # Anti invite
    # -----------------------------

    if settings["antilink"] and not is_staff(member):

        if "discord.gg/" in message.content.lower():

            try:
                await message.delete()

                await message.channel.send(
                    f"🚫 {member.mention}, "
                    f"Discord invites aren't allowed here.",
                    delete_after=5
                )

                await log_action(
                    guild,
                    f"🔗 Deleted Discord invite "
                    f"from {member}."
                )

            except discord.HTTPException:
                pass

            return

    # -----------------------------
    # Mention spam
    # -----------------------------

    if settings["antimention"] and not is_staff(member):

        if len(message.mentions) >= 8:

            try:
                await message.delete()

                await member.timeout(
                    timedelta(minutes=2),
                    reason="Mention spam"
                )

                await message.channel.send(
                    f"🛡️ {member.mention} was timed "
                    f"out for mention spam.",
                    delete_after=6
                )

            except discord.HTTPException:
                pass

            return

    # -----------------------------
    # Anti spam
    # -----------------------------

    if settings["antispam"] and not is_staff(member):

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
                    reason="Automatic spam protection"
                )

                await message.channel.send(
                    f"🛡️ {member.mention} was "
                    f"timed out for spam.",
                    delete_after=6
                )

                await log_action(
                    guild,
                    f"🛡️ Anti-spam timeout: {member}"
                )

                tracker.clear()

            except discord.HTTPException:
                pass

            return

    # -----------------------------
    # XP
    # -----------------------------

    user = profile(
        guild.id,
        member.id
    )

    now = int(time.time())

    if now - user["last_xp"] >= 45:

        user["last_xp"] = now
        user["xp"] += random.randint(10, 20)

        needed = 100 + (
            user["level"] * 50
        )

        if user["xp"] >= needed:

            user["xp"] -= needed
            user["level"] += 1

            channel_id = settings[
                "level_channel"
            ]

            channel = (
                guild.get_channel(channel_id)
                if channel_id
                else message.channel
            )

            if channel:

                try:
                    await channel.send(
                        f"✨ {member.mention} reached "
                        f"**Level {user['level']}**!"
                    )
                except discord.HTTPException:
                    pass


# ============================================================
# BASIC COMMANDS
# ============================================================

@bot.tree.command(
    name="ping",
    description="Check the bot latency"
)
async def ping(interaction):

    latency = round(
        bot.latency * 1000
    )

    await interaction.response.send_message(
        f"🏓 **{latency}ms**"
    )


@bot.tree.command(
    name="botinfo",
    description="Information about Normal Bot Junior"
)
async def botinfo(interaction):

    embed = discord.Embed(
        title="Normal Bot Junior",
        description=(
            "A private utility and moderation bot."
        ),
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Servers",
        value=str(len(bot.guilds)),
        inline=True
    )

    embed.add_field(
        name="Latency",
        value=f"{round(bot.latency * 1000)}ms",
        inline=True
    )

    embed.add_field(
        name="Owner",
        value=f"<@{OWNER_ID}>",
        inline=True
    )

    embed.set_footer(
        text="Normal Bot Junior"
    )

    await interaction.response.send_message(
        embed=embed
    )


@bot.tree.command(
    name="stats",
    description="Show bot statistics"
)
async def stats(interaction):

    members = sum(
        guild.member_count or 0
        for guild in bot.guilds
    )

    await interaction.response.send_message(
        f"**Normal Bot Junior**\n\n"
        f"Servers: `{len(bot.guilds)}`\n"
        f"Members: `{members}`\n"
        f"Latency: `{round(bot.latency * 1000)}ms`"
    )


# ============================================================
# USER / SERVER INFO
# ============================================================

@bot.tree.command(
    name="avatar",
    description="Show a member's avatar"
)
async def avatar(
    interaction,
    member: discord.Member = None
):

    member = member or interaction.user

    embed = discord.Embed(
        title=f"{member.display_name}'s avatar",
        color=discord.Color.blurple()
    )

    embed.set_image(
        url=member.display_avatar.url
    )

    await interaction.response.send_message(
        embed=embed
    )


@bot.tree.command(
    name="userinfo",
    description="Show member information"
)
async def userinfo(
    interaction,
    member: discord.Member = None
):

    member = member or interaction.user

    user = profile(
        interaction.guild.id,
        member.id
    )

    embed = discord.Embed(
        title=member.display_name,
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
        name="Rep",
        value=str(user["rep"])
    )

    embed.add_field(
        name="Warnings",
        value=str(len(user["warnings"]))
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
        title=guild.name,
        color=discord.Color.blurple()
    )

    if guild.icon:
        embed.set_thumbnail(
            url=guild.icon.url
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
        value=str(
            guild.premium_subscription_count
        )
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

    await log_action(
        interaction.guild,
        f"🧹 {interaction.user} deleted "
        f"{len(deleted)} messages."
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

    if member == interaction.guild.owner:

        await interaction.response.send_message(
            "❌ You can't ban the server owner.",
            ephemeral=True
        )

        return

    try:

        await member.ban(
            reason=reason
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I can't ban that member. "
            "Check my role position and permissions.",
            ephemeral=True
        )

        return

    case_id = await create_case(
        interaction.guild,
        "BAN",
        member,
        interaction.user,
        reason
    )

    await interaction.response.send_message(
        f"🔨 **{member}** was banned.\n"
        f"Case `#{case_id}`"
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

    try:

        await member.kick(
            reason=reason
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I can't kick that member.",
            ephemeral=True
        )

        return

    case_id = await create_case(
        interaction.guild,
        "KICK",
        member,
        interaction.user,
        reason
    )

    await interaction.response.send_message(
        f"👢 **{member}** was kicked.\n"
        f"Case `#{case_id}`"
    )


@bot.tree.command(
    name="timeout",
    description="Timeout a member"
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def timeout_member(
    interaction,
    member: discord.Member,
    minutes: app_commands.Range[int, 1, 40320],
    reason: str = "No reason provided"
):

    try:

        await member.timeout(
            timedelta(minutes=minutes),
            reason=reason
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I can't timeout that member.",
            ephemeral=True
        )

        return

    case_id = await create_case(
        interaction.guild,
        "TIMEOUT",
        member,
        interaction.user,
        reason
    )

    await interaction.response.send_message(
        f"⏱️ {member.mention} was timed out "
        f"for **{minutes} minutes**.\n"
        f"Case `#{case_id}`"
    )


@bot.tree.command(
    name="untimeout",
    description="Remove a member timeout"
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
        f"🔓 Removed timeout from "
        f"{member.mention}."
    )


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

    user = profile(
        interaction.guild.id,
        member.id
    )

    user["warnings"].append({
        "reason": reason,
        "moderator": interaction.user.id,
        "time": int(time.time())
    })

    case_id = await create_case(
        interaction.guild,
        "WARN",
        member,
        interaction.user,
        reason
    )

    await interaction.response.send_message(
        f"⚠️ {member.mention} was warned.\n"
        f"Warnings: **{len(user['warnings'])}**\n"
        f"Case `#{case_id}`"
    )


@bot.tree.command(
    name="warnings",
    description="View a member's warnings"
)
@app_commands.checks.has_permissions(
    manage_messages=True
)
async def warnings(
    interaction,
    member: discord.Member
):

    user = profile(
        interaction.guild.id,
        member.id
    )

    if not user["warnings"]:

        await interaction.response.send_message(
            f"✅ {member.mention} has no warnings."
        )

        return

    lines = []

    for number, warning in enumerate(
        user["warnings"],
        1
    ):

        lines.append(
            f"**{number}.** {warning['reason']}"
        )

    await interaction.response.send_message(
        f"⚠️ **Warnings for {member}**\n\n"
        + "\n".join(lines[:20])
    )


@bot.tree.command(
    name="clearwarnings",
    description="Clear a member's warnings"
)
@app_commands.checks.has_permissions(
    manage_messages=True
)
async def clearwarnings(
    interaction,
    member: discord.Member
):

    profile(
        interaction.guild.id,
        member.id
    )["warnings"].clear()

    await interaction.response.send_message(
        f"✅ Cleared warnings for "
        f"{member.mention}."
    )


@bot.tree.command(
    name="case",
    description="View a moderation case"
)
@app_commands.checks.has_permissions(
    manage_messages=True
)
async def case(
    interaction,
    case_id: int
):

    found = None

    for item in cases[interaction.guild.id]:

        if item["id"] == case_id:
            found = item
            break

    if not found:

        await interaction.response.send_message(
            "❌ Case not found.",
            ephemeral=True
        )

        return

    embed = discord.Embed(
        title=f"Case #{case_id}",
        color=discord.Color.orange()
    )

    embed.add_field(
        name="Action",
        value=found["action"]
    )

    embed.add_field(
        name="Target",
        value=found["target"]
    )

    embed.add_field(
        name="Moderator",
        value=found["moderator"]
    )

    embed.add_field(
        name="Reason",
        value=found["reason"],
        inline=False
    )

    await interaction.response.send_message(
        embed=embed
    )


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


@bot.tree.command(
    name="lock",
    description="Lock this channel"
)
@app_commands.checks.has_permissions(
    manage_channels=True
)
async def lock(interaction):

    overwrite = (
        interaction.channel.overwrites_for(
            interaction.guild.default_role
        )
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
    description="Unlock this channel"
)
@app_commands.checks.has_permissions(
    manage_channels=True
)
async def unlock(interaction):

    overwrite = (
        interaction.channel.overwrites_for(
            interaction.guild.default_role
        )
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
# SECURITY
# ============================================================

@bot.tree.command(
    name="antispam",
    description="Enable or disable anti-spam"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def antispam(
    interaction,
    enabled: bool
):

    config(
        interaction.guild.id
    )["antispam"] = enabled

    await interaction.response.send_message(
        f"🛡️ Anti-spam: "
        f"**{'ON' if enabled else 'OFF'}**"
    )


@bot.tree.command(
    name="antilink",
    description="Enable or disable Discord invite protection"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def antilink(
    interaction,
    enabled: bool
):

    config(
        interaction.guild.id
    )["antilink"] = enabled

    await interaction.response.send_message(
        f"🔗 Anti-invite: "
        f"**{'ON' if enabled else 'OFF'}**"
    )


@bot.tree.command(
    name="antimention",
    description="Enable or disable mention protection"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def antimention(
    interaction,
    enabled: bool
):

    config(
        interaction.guild.id
    )["antimention"] = enabled

    await interaction.response.send_message(
        f"📢 Mention protection: "
        f"**{'ON' if enabled else 'OFF'}**"
    )


@bot.tree.command(
    name="antiraid",
    description="Enable or disable raid detection"
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def antiraid(
    interaction,
    enabled: bool
):

    config(
        interaction.guild.id
    )["antiraid"] = enabled

    await interaction.response.send_message(
        f"🚨 Anti-raid: "
        f"**{'ON' if enabled else 'OFF'}**"
    )


@bot.tree.command(
    name="security",
    description="View security settings"
)
async def security(interaction):

    settings = config(
        interaction.guild.id
    )

    embed = discord.Embed(
        title="🛡️ Security",
        color=discord.Color.red()
    )

    embed.add_field(
        name="Anti-spam",
        value="ON" if settings["antispam"] else "OFF"
    )

    embed.add_field(
        name="Anti-invite",
        value="ON" if settings["antilink"] else "OFF"
    )

    embed.add_field(
        name="Anti-raid",
        value="ON" if settings["antiraid"] else "OFF"
    )

    embed.add_field(
        name="Mention protection",
        value=(
            "ON"
            if settings["antimention"]
            else "OFF"
        )
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# ECONOMY
# ============================================================

@bot.tree.command(
    name="balance",
    description="Check your coins"
)
async def balance(interaction):

    user = profile(
        interaction.guild.id,
        interaction.user.id
    )

    await interaction.response.send_message(
        f"💰 You have **{user['coins']:,} coins**."
    )


@bot.tree.command(
    name="daily",
    description="Claim your daily reward"
)
async def daily(interaction):

    user = profile(
        interaction.guild.id,
        interaction.user.id
    )

    now = time.time()

    if now - user["last_daily"] < 86400:

        remaining = (
            86400 -
            (now - user["last_daily"])
        )

        await interaction.response.send_message(
            f"⏳ Come back in "
            f"**{format_time(remaining)}**.",
            ephemeral=True
        )

        return

    reward = random.randint(
        250,
        750
    )

    user["coins"] += reward
    user["last_daily"] = now

    await interaction.response.send_message(
        f"💰 You received **{reward:,} coins**."
    )


@bot.tree.command(
    name="weekly",
    description="Claim your weekly reward"
)
async def weekly(interaction):

    user = profile(
        interaction.guild.id,
        interaction.user.id
    )

    now = time.time()

    if now - user["last_weekly"] < 604800:

        remaining = (
            604800 -
            (now - user["last_weekly"])
        )

        await interaction.response.send_message(
            f"⏳ Come back in "
            f"**{format_time(remaining)}**.",
            ephemeral=True
        )

        return

    reward = random.randint(
        1500,
        4000
    )

    user["coins"] += reward
    user["last_weekly"] = now

    await interaction.response.send_message(
        f"💰 You received **{reward:,} coins**."
    )


@bot.tree.command(
    name="work",
    description="Work for coins"
)
async def work(interaction):

    user = profile(
        interaction.guild.id,
        interaction.user.id
    )

    now = time.time()

    if now - user["last_work"] < 30:

        await interaction.response.send_message(
            "⏳ You're tired. Try again soon.",
            ephemeral=True
        )

        return

    jobs = [
        "developer",
        "game tester",
        "streamer",
        "designer",
        "YouTuber",
        "pizza delivery driver",
        "moderator",
        "photographer"
    ]

    job = random.choice(jobs)

    reward = random.randint(
        50,
        250
    )

    user["coins"] += reward
    user["last_work"] = now

    await interaction.response.send_message(
        f"💼 You worked as a **{job}** "
        f"and made **{reward} coins**."
    )


@bot.tree.command(
    name="beg",
    description="Beg for coins"
)
async def beg(interaction):

    user = profile(
        interaction.guild.id,
        interaction.user.id
    )

    now = time.time()

    if now - user["last_beg"] < 20:

        await interaction.response.send_message(
            "⏳ Try again in a few seconds.",
            ephemeral=True
        )

        return

    user["last_beg"] = now

    if random.random() < 0.3:

        await interaction.response.send_message(
            "💀 Nobody gave you anything."
        )

        return

    reward = random.randint(
        10,
        100
    )

    user["coins"] += reward

    await interaction.response.send_message(
        f"🪙 Someone gave you **{reward} coins**."
    )


@bot.tree.command(
    name="give",
    description="Give coins to another member"
)
async def give(
    interaction,
    member: discord.Member,
    amount: app_commands.Range[int, 1, 1000000]
):

    if member == interaction.user:

        await interaction.response.send_message(
            "❌ You can't give yourself coins.",
            ephemeral=True
        )

        return

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
        f"💸 Sent **{amount:,} coins** "
        f"to {member.mention}."
    )


@bot.tree.command(
    name="richest",
    description="Show the richest members"
)
async def richest(interaction):

    results = []

    for (guild_id, user_id), user in user_data.items():

        if guild_id != interaction.guild.id:
            continue

        member = interaction.guild.get_member(
            user_id
        )

        if member:
            results.append(
                (
                    member,
                    user["coins"]
                )
            )

    results.sort(
        key=lambda x: x[1],
        reverse=True
    )

    lines = []

    for number, (member, coins) in enumerate(
        results[:10],
        1
    ):

        lines.append(
            f"**{number}.** {member.mention} "
            f"— `{coins:,}`"
        )

    await interaction.response.send_message(
        "🏆 **Richest**\n\n" +
        (
            "\n".join(lines)
            if lines
            else "No economy data yet."
        )
    )


# ============================================================
# LEVELS
# ============================================================

@bot.tree.command(
    name="rank",
    description="View your XP and level"
)
async def rank(interaction):

    user = profile(
        interaction.guild.id,
        interaction.user.id
    )

    required = 100 + (
        user["level"] * 50
    )

    await interaction.response.send_message(
        f"✨ **{interaction.user.display_name}**\n"
        f"Level: **{user['level']}**\n"
        f"XP: **{user['xp']} / {required}**"
    )


@bot.tree.command(
    name="leaderboard",
    description="View the XP leaderboard"
)
async def leaderboard(interaction):

    results = []

    for (guild_id, user_id), user in user_data.items():

        if guild_id != interaction.guild.id:
            continue

        member = interaction.guild.get_member(
            user_id
        )

        if member:
            results.append(
                (
                    member,
                    user["level"],
                    user["xp"]
                )
            )

    results.sort(
        key=lambda x: (
            x[1],
            x[2]
        ),
        reverse=True
    )

    lines = []

    for number, (
        member,
        level,
        xp
    ) in enumerate(
        results[:10],
        1
    ):

        lines.append(
            f"**{number}.** {member.mention} "
            f"— Level `{level}` • `{xp} XP`"
        )

    await interaction.response.send_message(
        "🏆 **XP Leaderboard**\n\n" +
        (
            "\n".join(lines)
            if lines
            else "No XP data yet."
        )
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

    result = random.randint(
        1,
        sides
    )

    await interaction.response.send_message(
        f"🎲 You rolled **{result}**."
    )


@bot.tree.command(
    name="coinflip",
    description="Flip a coin"
)
async def coinflip(interaction):

    await interaction.response.send_message(
        f"🪙 **{random.choice(['Heads', 'Tails'])}**"
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
        "Probably.",
        "Probably not.",
        "Absolutely.",
        "Not happening.",
        "Ask again later.",
        "I wouldn't count on it.",
        "Looks good.",
        "Definitely."
    ]

    await interaction.response.send_message(
        f"🎱 **{question}**\n\n"
        f"→ {random.choice(answers)}"
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
            "Give me at least two options separated "
            "by commas.",
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        f"🤔 **{random.choice(choices)}**"
    )


@bot.tree.command(
    name="rate",
    description="Rate something"
)
async def rate(
    interaction,
    thing: str
):

    score = random.randint(
        0,
        100
    )

    await interaction.response.send_message(
        f"📊 **{thing}** → **{score}/100**"
    )


@bot.tree.command(
    name="ship",
    description="Calculate compatibility"
)
async def ship(
    interaction,
    user1: discord.Member,
    user2: discord.Member
):

    score = random.randint(
        0,
        100
    )

    await interaction.response.send_message(
        f"💞 **{user1.display_name} + "
        f"{user2.display_name}**\n"
        f"Compatibility: **{score}%**"
    )


# ============================================================
# POLL
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

    if not 2 <= len(choices) <= 10:

        await interaction.response.send_message(
            "Use 2-10 options separated by `|`.",
            ephemeral=True
        )

        return

    emojis = [
        "🇦", "🇧", "🇨", "🇩", "🇪",
        "🇫", "🇬", "🇭", "🇮", "🇯"
    ]

    description = "\n".join(
        f"{emojis[i]} {choice}"
        for i, choice in enumerate(choices)
    )

    embed = discord.Embed(
        title=question,
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

@bot.tree.command(
    name="remind",
    description="Set a reminder"
)
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
        "time": time.time() + (
            minutes * 60
        )
    }

    await interaction.response.send_message(
        f"⏰ Reminder set for "
        f"**{minutes} minutes**."
    )


# ============================================================
# TEMP VOICE
# ============================================================

@bot.tree.command(
    name="tempvoice",
    description="Create a temporary voice channel"
)
async def tempvoice(interaction):

    channel = await interaction.guild.create_voice_channel(
        f"🔊 {interaction.user.display_name}'s room"
    )

    temp_voice_channels.add(
        channel.id
    )

    try:
        await interaction.user.move_to(
            channel
        )
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
        and before.channel.id in temp_voice_channels
        and len(before.channel.members) == 0
    ):

        channel_id = before.channel.id

        try:
            await before.channel.delete()
        except discord.HTTPException:
            pass

        temp_voice_channels.discard(
            channel_id
        )


# ============================================================
# TICKET SYSTEM
# ============================================================

class TicketPanelView(discord.ui.View):

    def __init__(self):
        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="Open a ticket",
        emoji="🎫",
        style=discord.ButtonStyle.primary,
        custom_id="normal_bot_junior:ticket_open"
    )
    async def open_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        guild = interaction.guild
        user = interaction.user

        key = (
            guild.id,
            user.id
        )

        existing_id = tickets.get(key)

        if existing_id:

            existing = guild.get_channel(
                existing_id
            )

            if existing:

                await interaction.response.send_message(
                    f"You already have "
                    f"{existing.mention}.",
                    ephemeral=True
                )

                return

            tickets.pop(
                key,
                None
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
                    read_message_history=True,
                    manage_channels=True
                )
        }

        channel = await guild.create_text_channel(
            f"ticket-{user.name}",
            overwrites=overwrites
        )

        tickets[key] = channel.id

        embed = discord.Embed(
            title="🎫 Support Ticket",
            description=(
                f"Welcome {user.mention}.\n\n"
                "Explain what you need help with."
            ),
            color=discord.Color.blurple()
        )

        await channel.send(
            embed=embed,
            view=TicketCloseView()
        )

        await interaction.response.send_message(
            f"Ticket created: {channel.mention}",
            ephemeral=True
        )


class TicketCloseView(discord.ui.View):

    def __init__(self):
        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="Close",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="normal_bot_junior:ticket_close"
    )
    async def close_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not is_staff(interaction.user):

            await interaction.response.send_message(
                "You need staff permissions to close this ticket.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            "🔒 Closing this ticket..."
        )

        for key, channel_id in list(
            tickets.items()
        ):

            if channel_id == interaction.channel.id:
                tickets.pop(
                    key,
                    None
                )

        await asyncio.sleep(3)

        try:
            await interaction.channel.delete()
        except discord.HTTPException:
            pass


@bot.tree.command(
    name="ticketpanel",
    description="Create a ticket panel"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def ticketpanel(interaction):

    embed = discord.Embed(
        title="Need help?",
        description=(
            "Open a private support ticket "
            "using the button below."
        ),
        color=discord.Color.blurple()
    )

    embed.set_footer(
        text="Normal Bot Junior • Support"
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
        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="Enter",
        emoji="🎉",
        style=discord.ButtonStyle.success,
        custom_id="normal_bot_junior:giveaway_enter"
    )
    async def enter(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        giveaway = giveaways.get(
            interaction.message.id
        )

        if not giveaway:

            await interaction.response.send_message(
                "This giveaway is no longer active.",
                ephemeral=True
            )

            return

        giveaway["entries"].add(
            interaction.user.id
        )

        await interaction.response.send_message(
            "🎉 You're entered.",
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

    end = time.time() + (
        minutes * 60
    )

    embed = discord.Embed(
        title="🎉 Giveaway",
        description=(
            f"**Prize:** {prize}\n"
            f"**Winners:** {winners}\n"
            f"**Ends:** <t:{int(end)}:R>\n\n"
            "Click **Enter** to participate."
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
        "prize": prize,
        "winners": winners,
        "end": end,
        "entries": set()
    }


# ============================================================
# VERIFICATION
# ============================================================

class VerificationView(discord.ui.View):

    def __init__(self):
        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="Verify",
        emoji="✓",
        style=discord.ButtonStyle.success,
        custom_id="normal_bot_junior:verify"
    )
    async def verify(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        role_id = config(
            interaction.guild.id
        )["verification_role"]

        if not role_id:

            await interaction.response.send_message(
                "Verification hasn't been configured.",
                ephemeral=True
            )

            return

        role = interaction.guild.get_role(
            role_id
        )

        if not role:

            await interaction.response.send_message(
                "The verification role no longer exists.",
                ephemeral=True
            )

            return

        try:

            await interaction.user.add_roles(
                role,
                reason="Normal Bot Junior verification"
            )

            await interaction.response.send_message(
                "✅ You're verified.",
                ephemeral=True
            )

        except discord.Forbidden:

            await interaction.response.send_message(
                "❌ I can't give you that role. "
                "Move my bot role above the verification role.",
                ephemeral=True
            )


@bot.tree.command(
    name="verification",
    description="Create a verification panel"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def verification(interaction):

    embed = discord.Embed(
        title="Verification",
        description=(
            "Click **Verify** to receive "
            "the verified role."
        ),
        color=discord.Color.green()
    )

    await interaction.response.send_message(
        embed=embed,
        view=VerificationView()
    )


# ============================================================
# SERVER CONFIG
# ============================================================

@bot.tree.command(
    name="setlog",
    description="Set the moderation log channel"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def setlog(
    interaction,
    channel: discord.TextChannel
):

    config(
        interaction.guild.id
    )["log_channel"] = channel.id

    await interaction.response.send_message(
        f"📋 Logs → {channel.mention}"
    )


@bot.tree.command(
    name="setwelcome",
    description="Set the welcome channel"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def setwelcome(
    interaction,
    channel: discord.TextChannel
):

    config(
        interaction.guild.id
    )["welcome_channel"] = channel.id

    await interaction.response.send_message(
        f"👋 Welcome messages → "
        f"{channel.mention}"
    )


@bot.tree.command(
    name="setgoodbye",
    description="Set the goodbye channel"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def setgoodbye(
    interaction,
    channel: discord.TextChannel
):

    config(
        interaction.guild.id
    )["goodbye_channel"] = channel.id

    await interaction.response.send_message(
        f"👋 Goodbye messages → "
        f"{channel.mention}"
    )


@bot.tree.command(
    name="setautorole",
    description="Set the automatic member role"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def setautorole(
    interaction,
    role: discord.Role
):

    config(
        interaction.guild.id
    )["autorole"] = role.id

    await interaction.response.send_message(
        f"New members will receive "
        f"{role.mention}."
    )


@bot.tree.command(
    name="setmodrole",
    description="Set the moderator role"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def setmodrole(
    interaction,
    role: discord.Role
):

    config(
        interaction.guild.id
    )["mod_role"] = role.id

    await interaction.response.send_message(
        f"🛡️ Moderator role → "
        f"{role.mention}"
    )


@bot.tree.command(
    name="setverificationrole",
    description="Set the verification role"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def setverificationrole(
    interaction,
    role: discord.Role
):

    config(
        interaction.guild.id
    )["verification_role"] = role.id

    await interaction.response.send_message(
        f"✓ Verification role → "
        f"{role.mention}"
    )


@bot.tree.command(
    name="setlevelchannel",
    description="Set the level-up channel"
)
@app_commands.checks.has_permissions(
    manage_guild=True
)
async def setlevelchannel(
    interaction,
    channel: discord.TextChannel
):

    config(
        interaction.guild.id
    )["level_channel"] = channel.id

    await interaction.response.send_message(
        f"✨ Level-up messages → "
        f"{channel.mention}"
    )


# ============================================================
# OWNER COMMANDS
# ============================================================

async def owner_check(interaction):

    if is_owner(interaction.user):
        return True

    await interaction.response.send_message(
        "🔒 This command is restricted to "
        "the bot owner.",
        ephemeral=True
    )

    return False


@bot.tree.command(
    name="owner",
    description="Show the configured bot owner"
)
async def owner(interaction):

    if not await owner_check(interaction):
        return

    await interaction.response.send_message(
        f"👑 Owner: <@{OWNER_ID}>",
        ephemeral=True
    )


@bot.tree.command(
    name="servers",
    description="List the servers the bot is in"
)
async def servers(interaction):

    if not await owner_check(interaction):
        return

    lines = [
        f"**{guild.name}** — `{guild.id}`"
        for guild in bot.guilds
    ]

    text = "\n".join(lines)

    if len(text) > 1900:
        text = text[:1900] + "\n..."

    await interaction.response.send_message(
        text or "No servers.",
        ephemeral=True
    )


@bot.tree.command(
    name="say",
    description="Make the bot send a message"
)
async def say(
    interaction,
    message: str
):

    if not await owner_check(interaction):
        return

    await interaction.response.send_message(
        "Sent.",
        ephemeral=True
    )

    await interaction.channel.send(
        message
    )


@bot.tree.command(
    name="announce",
    description="Send an announcement"
)
async def announce(
    interaction,
    channel: discord.TextChannel,
    title: str,
    message: str
):

    if not await owner_check(interaction):
        return

    embed = discord.Embed(
        title=title,
        description=message,
        color=discord.Color.blurple()
    )

    embed.set_footer(
        text="Normal Bot Junior"
    )

    await channel.send(
        embed=embed
    )

    await interaction.response.send_message(
        "Announcement sent.",
        ephemeral=True
    )


@bot.tree.command(
    name="dm",
    description="DM a Discord member"
)
async def dm(
    interaction,
    member: discord.Member,
    message: str
):

    if not await owner_check(interaction):
        return

    try:

        await member.send(message)

        await interaction.response.send_message(
            "DM sent.",
            ephemeral=True
        )

    except discord.HTTPException:

        await interaction.response.send_message(
            "I couldn't DM that user.",
            ephemeral=True
        )


@bot.tree.command(
    name="setstatus",
    description="Change the bot status"
)
async def setstatus(
    interaction,
    text: str
):

    if not await owner_check(interaction):
        return

    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Game(
            name=text
        )
    )

    await interaction.response.send_message(
        f"Status changed to **{text}**.",
        ephemeral=True
    )


@bot.tree.command(
    name="setactivity",
    description="Change the bot activity"
)
async def setactivity(
    interaction,
    activity_type: str,
    text: str
):

    if not await owner_check(interaction):
        return

    activity_type = activity_type.lower()

    if activity_type == "playing":

        activity = discord.Game(
            name=text
        )

    elif activity_type == "watching":

        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=text
        )

    elif activity_type == "listening":

        activity = discord.Activity(
            type=discord.ActivityType.listening,
            name=text
        )

    elif activity_type == "streaming":

        activity = discord.Streaming(
            name=text,
            url="https://twitch.tv/"
        )

    else:

        await interaction.response.send_message(
            "Use `playing`, `watching`, "
            "`listening`, or `streaming`.",
            ephemeral=True
        )

        return

    await bot.change_presence(
        activity=activity
    )

    await interaction.response.send_message(
        "Activity updated.",
        ephemeral=True
    )


@bot.tree.command(
    name="shutdown",
    description="Shut down the bot"
)
async def shutdown(interaction):

    if not await owner_check(interaction):
        return

    await interaction.response.send_message(
        "Shutting down.",
        ephemeral=True
    )

    await bot.close()


# ============================================================
# HELP MENU
# ============================================================

class HelpView(discord.ui.View):

    def __init__(self):
        super().__init__(
            timeout=180
        )

    @discord.ui.button(
        label="Moderation",
        emoji="🛡️",
        style=discord.ButtonStyle.primary
    )
    async def moderation(
        self,
        interaction,
        button
    ):

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🛡️ Moderation",
                description=(
                    "`/ban`\n"
                    "`/kick`\n"
                    "`/timeout`\n"
                    "`/untimeout`\n"
                    "`/warn`\n"
                    "`/warnings`\n"
                    "`/clearwarnings`\n"
                    "`/case`\n"
                    "`/clear`\n"
                    "`/slowmode`\n"
                    "`/lock`\n"
                    "`/unlock`"
                ),
                color=discord.Color.orange()
            ),
            view=HelpBackView()
        )

    @discord.ui.button(
        label="Security",
        emoji="🚨",
        style=discord.ButtonStyle.danger
    )
    async def security(
        self,
        interaction,
        button
    ):

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🚨 Security",
                description=(
                    "`/antispam`\n"
                    "`/antilink`\n"
                    "`/antimention`\n"
                    "`/antiraid`\n"
                    "`/security`"
                ),
                color=discord.Color.red()
            ),
            view=HelpBackView()
        )

    @discord.ui.button(
        label="Economy",
        emoji="💰",
        style=discord.ButtonStyle.success
    )
    async def economy(
        self,
        interaction,
        button
    ):

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="💰 Economy",
                description=(
                    "`/balance`\n"
                    "`/daily`\n"
                    "`/weekly`\n"
                    "`/work`\n"
                    "`/beg`\n"
                    "`/give`\n"
                    "`/richest`"
                ),
                color=discord.Color.green()
            ),
            view=HelpBackView()
        )

    @discord.ui.button(
        label="Fun",
        emoji="🎮",
        style=discord.ButtonStyle.secondary
    )
    async def fun(
        self,
        interaction,
        button
    ):

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🎮 Fun",
                description=(
                    "`/roll`\n"
                    "`/coinflip`\n"
                    "`/8ball`\n"
                    "`/choose`\n"
                    "`/rate`\n"
                    "`/ship`"
                ),
                color=discord.Color.blurple()
            ),
            view=HelpBackView()
        )

    @discord.ui.button(
        label="Owner",
        emoji="👑",
        style=discord.ButtonStyle.secondary
    )
    async def owner(
        self,
        interaction,
        button
    ):

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="👑 Owner",
                description=(
                    "Private commands.\n\n"
                    "`/owner`\n"
                    "`/servers`\n"
                    "`/say`\n"
                    "`/announce`\n"
                    "`/dm`\n"
                    "`/setstatus`\n"
                    "`/setactivity`\n"
                    "`/shutdown`"
                ),
                color=discord.Color.gold()
            ),
            view=HelpBackView()
        )


class HelpBackView(discord.ui.View):

    def __init__(self):
        super().__init__(
            timeout=180
        )

    @discord.ui.button(
        label="Back",
        emoji="←",
        style=discord.ButtonStyle.secondary
    )
    async def back(
        self,
        interaction,
        button
    ):

        await interaction.response.edit_message(
            embed=help_home_embed(),
            view=HelpView()
        )


def help_home_embed():

    return discord.Embed(
        title="Normal Bot Junior",
        description=(
            "### Command center\n\n"
            "🛡️ **Moderation**\n"
            "Server management and moderation.\n\n"
            "🚨 **Security**\n"
            "Spam, invites, mentions and raid detection.\n\n"
            "💰 **Economy**\n"
            "Coins, rewards and leaderboards.\n\n"
            "🎮 **Fun**\n"
            "Games and random commands.\n\n"
            "👑 **Owner**\n"
            "Private bot-owner controls.\n\n"
            "Use the buttons below."
        ),
        color=discord.Color.blurple()
    )


@bot.tree.command(
    name="help",
    description="Open the command center"
)
async def help_command(interaction):

    await interaction.response.send_message(
        embed=help_home_embed(),
        view=HelpView()
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
        f"[COMMAND ERROR] {repr(error)}"
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
            "⏳ That command is on cooldown."
        )

    else:

        message = (
            "❌ Something went wrong while "
            "running that command."
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
# START
# ============================================================

if __name__ == "__main__":

    print("Starting Normal Bot Junior...")

    bot.run(TOKEN)
