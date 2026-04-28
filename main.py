import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
DATA_PATH = BASE_DIR / "saves.json"


@dataclass
class BotConfig:
    token: str
    prefix: str = "!"
    owner_ids: list[int] | None = None
    welcome_channel_id: int | None = None
    log_channel_id: int | None = None
    auto_role_id: int | None = None
    ticket_category_id: int | None = None

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if value in (None, "", 0):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def load(cls, path: Path) -> "BotConfig":
        if not path.exists():
            raise FileNotFoundError(
                "config.json غير موجود. انسخ config.example.json إلى config.json ثم عدل الإعدادات."
            )

        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        token = raw.get("token") or os.getenv("DISCORD_TOKEN")
        if not token:
            raise ValueError("ضع token داخل config.json أو متغير البيئة DISCORD_TOKEN")

        owner_ids_raw = raw.get("owner_ids") or []
        owner_ids = [int(x) for x in owner_ids_raw if str(x).isdigit()] if owner_ids_raw else []

        return cls(
            token=token,
            prefix=raw.get("prefix", "!"),
            owner_ids=owner_ids,
            welcome_channel_id=cls._as_int(raw.get("welcome_channel_id")),
            log_channel_id=cls._as_int(raw.get("log_channel_id")),
            auto_role_id=cls._as_int(raw.get("auto_role_id")),
            ticket_category_id=cls._as_int(raw.get("ticket_category_id")),
        )


class JsonStore:
    def __init__(self, path: Path):
        self.path = path
        self.data = {
            "warns": {},
            "suggestions_count": 0,
        }
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.save()
            return

        try:
            with self.path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.data.update(loaded)
        except json.JSONDecodeError:
            self.save()

    def save(self) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 إغلاق التذكرة", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("لا تملك صلاحية إغلاق التذكرة.", ephemeral=True)
            return

        await interaction.response.send_message("سيتم حذف التذكرة بعد 5 ثوانٍ.")
        await asyncio.sleep(5)
        if interaction.channel:
            await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")


class TicketOpenView(discord.ui.View):
    def __init__(self, bot: "FullSystemBot"):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="🎫 فتح تذكرة", style=discord.ButtonStyle.success, custom_id="ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, _: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user

        if guild is None or not isinstance(user, discord.Member):
            await interaction.response.send_message("هذا الزر يعمل داخل السيرفر فقط.", ephemeral=True)
            return

        existing = discord.utils.get(guild.text_channels, name=f"ticket-{user.id}")
        if existing:
            await interaction.response.send_message(f"لديك تذكرة مفتوحة بالفعل: {existing.mention}", ephemeral=True)
            return

        category = guild.get_channel(self.bot.config.ticket_category_id) if self.bot.config.ticket_category_id else None
        if category and not isinstance(category, discord.CategoryChannel):
            category = None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }

        channel = await guild.create_text_channel(
            name=f"ticket-{user.id}",
            category=category,
            overwrites=overwrites,
            reason=f"Ticket opened by {user}",
        )

        embed = discord.Embed(
            title="🎟️ تم فتح التذكرة",
            description="اكتب مشكلتك بالتفصيل وسيتم الرد عليك من فريق الإدارة.",
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"صاحب التذكرة: {user}")

        await channel.send(content=user.mention, embed=embed, view=TicketCloseView())
        await interaction.response.send_message(f"تم إنشاء التذكرة: {channel.mention}", ephemeral=True)


class FullSystemBot(commands.Bot):
    def __init__(self, config: BotConfig, store: JsonStore):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True

        super().__init__(
            command_prefix=config.prefix,
            intents=intents,
            help_command=None,
        )
        self.config = config
        self.store = store

    async def setup_hook(self) -> None:
        self.add_view(TicketOpenView(self))
        self.add_view(TicketCloseView())

    async def on_ready(self):
        logging.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "?")
        await self.change_presence(activity=discord.Game(name=f"{self.config.prefix}help | نظام متكامل"))

    async def on_member_join(self, member: discord.Member):
        if self.config.auto_role_id:
            role = member.guild.get_role(self.config.auto_role_id)
            if role:
                try:
                    await member.add_roles(role, reason="Auto role")
                except discord.Forbidden:
                    logging.warning("Missing permission for auto role")

        if self.config.welcome_channel_id:
            channel = member.guild.get_channel(self.config.welcome_channel_id)
            if isinstance(channel, discord.TextChannel):
                embed = discord.Embed(
                    title="👋 عضو جديد",
                    description=f"أهلاً {member.mention} في **{member.guild.name}**",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc),
                )
                await channel.send(embed=embed)

    async def on_member_remove(self, member: discord.Member):
        await self.send_log(member.guild, f"🚪 {member} غادر السيرفر.")

    async def on_message_delete(self, message: discord.Message):
        if message.guild and not message.author.bot:
            content = (message.content or "[بدون نص]")[:1000]
            await self.send_log(message.guild, f"🗑️ تم حذف رسالة من {message.author.mention}: {content}")

    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.guild and not before.author.bot and before.content != after.content:
            old = (before.content or "[بدون نص]")[:400]
            new = (after.content or "[بدون نص]")[:400]
            await self.send_log(before.guild, f"✏️ تعديل رسالة بواسطة {before.author.mention}\nقبل: {old}\nبعد: {new}")

    async def send_log(self, guild: discord.Guild, message: str):
        if not self.config.log_channel_id:
            return
        channel = guild.get_channel(self.config.log_channel_id)
        if isinstance(channel, discord.TextChannel):
            await channel.send(message)


def admin_or_owner():
    async def predicate(ctx: commands.Context):
        bot: FullSystemBot = ctx.bot  # type: ignore
        if isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator:
            return True
        return ctx.author.id in (bot.config.owner_ids or [])

    return commands.check(predicate)


config = BotConfig.load(CONFIG_PATH)
store = JsonStore(DATA_PATH)
bot = FullSystemBot(config=config, store=store)


@bot.command(name="help")
async def help_command(ctx: commands.Context):
    embed = discord.Embed(title="📚 أوامر البوت", color=discord.Color.gold())
    embed.add_field(name="الأساسيات", value=f"`{config.prefix}ping` `userinfo` `serverinfo`", inline=False)
    embed.add_field(name="الإدارة", value=f"`{config.prefix}kick` `ban` `timeout` `clear`", inline=False)
    embed.add_field(name="التحذيرات", value=f"`{config.prefix}warn` `warnings` `unwarn`", inline=False)
    embed.add_field(name="الأنظمة", value=f"`{config.prefix}setup` `ticketpanel` `suggest`", inline=False)
    await ctx.send(embed=embed)


@bot.command()
async def ping(ctx: commands.Context):
    await ctx.send(f"🏓 Pong: `{round(bot.latency * 1000)}ms`")


@bot.command()
async def userinfo(ctx: commands.Context, member: discord.Member | None = None):
    member = member or ctx.author
    embed = discord.Embed(title=f"معلومات العضو: {member}", color=discord.Color.blue())
    embed.add_field(name="ID", value=member.id)
    embed.add_field(name="تاريخ الانضمام", value=member.joined_at.strftime("%Y-%m-%d") if member.joined_at else "-")
    embed.add_field(name="تاريخ إنشاء الحساب", value=member.created_at.strftime("%Y-%m-%d"))
    await ctx.send(embed=embed)


@bot.command()
async def serverinfo(ctx: commands.Context):
    g = ctx.guild
    if not g:
        await ctx.send("هذا الأمر يعمل داخل السيرفر فقط.")
        return
    embed = discord.Embed(title=f"معلومات السيرفر: {g.name}", color=discord.Color.purple())
    embed.add_field(name="الأعضاء", value=g.member_count)
    embed.add_field(name="القنوات", value=len(g.channels))
    embed.add_field(name="الرولات", value=len(g.roles))
    await ctx.send(embed=embed)


@bot.command()
@admin_or_owner()
async def clear(ctx: commands.Context, amount: int):
    amount = max(1, min(amount, 200))
    deleted = await ctx.channel.purge(limit=amount + 1)
    msg = await ctx.send(f"✅ تم حذف {len(deleted)-1} رسالة.")
    await asyncio.sleep(4)
    await msg.delete()


@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx: commands.Context, member: discord.Member, *, reason: str = "بدون سبب"):
    await member.kick(reason=reason)
    await ctx.send(f"👢 تم طرد {member.mention}. السبب: {reason}")
    await bot.send_log(ctx.guild, f"👢 {ctx.author} طرد {member}. السبب: {reason}")


@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx: commands.Context, member: discord.Member, *, reason: str = "بدون سبب"):
    await member.ban(reason=reason, delete_message_days=0)
    await ctx.send(f"🔨 تم حظر {member.mention}. السبب: {reason}")
    await bot.send_log(ctx.guild, f"🔨 {ctx.author} حظر {member}. السبب: {reason}")


@bot.command()
@commands.has_permissions(moderate_members=True)
async def timeout(ctx: commands.Context, member: discord.Member, minutes: int, *, reason: str = "بدون سبب"):
    minutes = max(1, min(minutes, 40320))
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    await member.timeout(until, reason=reason)
    await ctx.send(f"⏱️ تم عمل timeout لـ {member.mention} لمدة {minutes} دقيقة.")
    await bot.send_log(ctx.guild, f"⏱️ {ctx.author} timeout {member} لمدة {minutes} دقيقة. السبب: {reason}")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn(ctx: commands.Context, member: discord.Member, *, reason: str = "بدون سبب"):
    guild_key = str(ctx.guild.id)
    user_key = str(member.id)
    warns = store.data.setdefault("warns", {}).setdefault(guild_key, {}).setdefault(user_key, [])
    warns.append({
        "reason": reason,
        "by": ctx.author.id,
        "at": datetime.now(timezone.utc).isoformat(),
    })
    store.save()
    await ctx.send(f"⚠️ تم تحذير {member.mention}. عدد التحذيرات الآن: {len(warns)}")


@bot.command(name="warnings")
async def warnings_command(ctx: commands.Context, member: discord.Member):
    warns = store.data.get("warns", {}).get(str(ctx.guild.id), {}).get(str(member.id), [])
    if not warns:
        await ctx.send("لا يوجد تحذيرات لهذا العضو.")
        return

    lines = []
    for idx, w in enumerate(warns, start=1):
        lines.append(f"{idx}) {w['reason']} (By: {w['by']})")
    await ctx.send("\n".join(lines[:20]))


@bot.command(name="unwarn")
@commands.has_permissions(manage_messages=True)
async def unwarn(ctx: commands.Context, member: discord.Member, index: int):
    warns = store.data.get("warns", {}).get(str(ctx.guild.id), {}).get(str(member.id), [])
    if not warns:
        await ctx.send("لا يوجد تحذيرات لحذفها.")
        return
    if index < 1 or index > len(warns):
        await ctx.send("رقم التحذير غير صحيح.")
        return

    removed = warns.pop(index - 1)
    store.save()
    await ctx.send(f"✅ تم حذف التحذير: {removed['reason']}")


@bot.command()
@admin_or_owner()
async def setup(ctx: commands.Context, key: str, channel_or_role_id: int):
    valid = {"welcome_channel_id", "log_channel_id", "auto_role_id", "ticket_category_id"}
    if key not in valid:
        await ctx.send(f"القيمة غير صحيحة. القيم المتاحة: {', '.join(sorted(valid))}")
        return

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    raw[key] = channel_or_role_id
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)

    setattr(bot.config, key, channel_or_role_id)
    await ctx.send(f"✅ تم تحديث {key} إلى `{channel_or_role_id}`")


@bot.command()
@admin_or_owner()
async def ticketpanel(ctx: commands.Context):
    embed = discord.Embed(
        title="🎫 نظام التذاكر",
        description="اضغط على الزر لفتح تذكرة دعم خاصة بك.",
        color=discord.Color.teal(),
    )
    await ctx.send(embed=embed, view=TicketOpenView(bot))


@bot.command()
async def suggest(ctx: commands.Context, *, text: str):
    store.data["suggestions_count"] = int(store.data.get("suggestions_count", 0)) + 1
    store.save()
    suggestion_id = store.data["suggestions_count"]

    embed = discord.Embed(
        title=f"💡 اقتراح #{suggestion_id}",
        description=text,
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
    msg = await ctx.send(embed=embed)
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")
    await bot.send_log(ctx.guild, f"💡 اقتراح جديد #{suggestion_id} بواسطة {ctx.author.mention}")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ لا تملك الصلاحيات المطلوبة.")
        return
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ استخدام خاطئ للأمر. جرب `{config.prefix}help`.")
        return
    logging.exception("Command error", exc_info=error)
    await ctx.send("حدث خطأ غير متوقع أثناء تنفيذ الأمر.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    bot.run(config.token)
