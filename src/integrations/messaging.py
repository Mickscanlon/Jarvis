"""
messaging.py - Discord bot for remote JARVIS control and notifications
"""
import os
import asyncio
import logging
from typing import Callable
from dotenv import load_dotenv

load_dotenv(dotenv_path="C:/Users/micha/jarvis/.env")
logger = logging.getLogger(__name__)

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0") or "0")

PRIORITY_COLORS = {"critical": 0xFF0000, "medium": 0xFF8C00, "low": 0x0EA5E9}
PRIORITY_EMOJIS = {"critical": "🔴", "medium": "🟠", "low": "🔵"}

_discord_client = None


async def start_discord_bot(run_agent_fn: Callable, broadcast_fn: Callable):
    """Start Discord bot in background."""
    if not DISCORD_TOKEN:
        return

    try:
        import discord
        from discord.ext import commands

        intents = discord.Intents.default()
        intents.message_content = True
        bot = discord.Client(intents=intents)

        global _discord_client
        _discord_client = bot

        @bot.event
        async def on_ready():
            logger.info(f"[Discord] Bot ready as {bot.user}")
            if DISCORD_CHANNEL_ID:
                ch = bot.get_channel(DISCORD_CHANNEL_ID)
                if ch:
                    await ch.send("🟢 JARVIS online, sir.")

        @bot.event
        async def on_message(message):
            if message.author == bot.user:
                return
            if not DISCORD_CHANNEL_ID or message.channel.id != DISCORD_CHANNEL_ID:
                return

            text = message.content.strip()
            if not text:
                return

            # Accept commands starting with "jarvis" or bot mention
            bot_mention = f"<@{bot.user.id}>"
            if text.lower().startswith("jarvis") or bot_mention in text:
                query = text.replace("jarvis", "", 1).replace(bot_mention, "").strip()
                if not query:
                    return
                async with message.channel.typing():
                    try:
                        response = await run_agent_fn(query)
                        await message.reply(response[:2000])
                    except Exception as e:
                        await message.reply(f"Error: {e}")

        await bot.start(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"[Discord] Bot error: {e}")


async def post_to_discord(priority: str, message: str):
    """Post a notification to the configured Discord channel."""
    if not _discord_client or not DISCORD_CHANNEL_ID:
        logger.debug("[Discord] Not configured, skipping notification.")
        return

    try:
        ch = _discord_client.get_channel(DISCORD_CHANNEL_ID)
        if ch:
            emoji = PRIORITY_EMOJIS.get(priority, "ℹ️")
            await ch.send(f"{emoji} {message[:1900]}")
    except Exception as e:
        logger.error(f"[Discord] Post error: {e}")


async def send_rich_embed(title: str, content: str, color_key: str = "low"):
    """Send a rich embed message to Discord."""
    if not _discord_client or not DISCORD_CHANNEL_ID:
        return
    try:
        import discord
        embed = discord.Embed(
            title=title,
            description=content[:2000],
            color=PRIORITY_COLORS.get(color_key, 0x0EA5E9)
        )
        ch = _discord_client.get_channel(DISCORD_CHANNEL_ID)
        if ch:
            await ch.send(embed=embed)
    except Exception as e:
        logger.error(f"[Discord] Embed error: {e}")
