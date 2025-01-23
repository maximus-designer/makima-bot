import discord
from discord.ext import commands
import logging
import os
from dotenv import load_dotenv
import asyncio

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("No DISCORD_TOKEN found in .env file")

# Set up logging
logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Intents setup
intents = discord.Intents.default()
intents.members = True
intents.message_content = True  # Enable Message Content Intent

bot = commands.Bot(command_prefix=".", intents=intents)

# List of cogs to load
cogs = [
    "cogs.status_changer",
    "cogs.dragmee",
    "cogs.AvatarBannerUpdater",
    "cogs.giveaway",
    "cogs.steal",
    "cogs.stats",
    "cogs.afk_cog",
    "cogs.purge",
    "cogs.sticky",
    "cogs.reqrole",
    "cogs.confess",
    "cogs.thread",
    "cogs.av",
    # Other cogs
]

async def load_cogs():
    """Load all specified cogs."""
    for cog in cogs:
        try:
            if cog not in bot.extensions:
                await bot.load_extension(cog)
                logging.info(f"{cog} has been loaded.")
            else:
                logging.info(f"{cog} is already loaded.")
        except Exception as error:
            logging.error(f"Error loading {cog}: {error}")
            # Gracefully shut down if a critical cog fails to load (optional)
            if "critical_cog" in cog:
                logging.error(f"Critical cog {cog} failed to load. Shutting down.")
                await bot.close()

async def sync_commands_with_retry():
    """Sync slash commands with retry logic to handle rate limits."""
    retry_attempts = 5  # Set number of retry attempts
    for attempt in range(retry_attempts):
        try:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} command(s)")
            break  # Break out of loop if successful
        except discord.HTTPException as e:
            if e.code == 429:  # Rate-limited error
                retry_after = e.retry_after  # Retry time in seconds
                print(f"Rate limited. Retrying in {retry_after} seconds...")
                await asyncio.sleep(retry_after)  # Wait before retrying
            else:
                print(f"Error syncing commands: {e}")
                logging.error(f"Error syncing commands: {e}")
                if attempt == retry_attempts - 1:
                    logging.warning("Failed to sync commands after multiple attempts.")
                break  # Exit if an unexpected error occurs

@bot.event
async def on_ready():
    """When the bot is ready, print the bot info, sync commands, and list registered commands."""
    print(f'Logged in as {bot.user}')
    # Load cogs before syncing commands
    await load_cogs()
    # Sync commands with retry logic
    await sync_commands_with_retry()
    # Print all registered slash commands
    print("Registered slash commands:")
    for command in bot.tree.get_commands():
        print(f"- {command.name}")

# Latency Ping Command with rate-limiting
@bot.command()
@commands.cooldown(1, 5, commands.BucketType.user)  # 1 command per 5 seconds per user
async def ping(ctx):
    """A latency ping command."""
    latency = bot.latency  # Bot's latency in seconds
    await ctx.send(f'<a:sukoon_greendot:1322894177775783997> Latency is {latency * 1000:.2f}ms')

# Enhanced error handling for commands
@bot.event
async def on_command_error(ctx, error):
    """Handle command errors."""
    if isinstance(error, commands.CommandNotFound):
        # Provide a helpful message for unknown commands
        if ctx.message.content.strip() == ".":
            await ctx.send(f"❓ You need to specify a command after the prefix. Use `.help` to see available commands.")
        else:
            await ctx.send(f"❓ Unknown command. Use `.help` to see available commands.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument. Use `.help {ctx.command}` for command usage.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Invalid argument. Use `.help {ctx.command}` for correct usage.")
    else:
        # Log unexpected errors
        logging.error(f"Unexpected error: {error}")
        await ctx.send("An unexpected error occurred. Please try again.")

# Start the bot
bot.run(DISCORD_TOKEN)
