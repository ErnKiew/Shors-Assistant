# Discord module
import disnake
from disnake.ext import tasks, commands # For tasks and slash commands

# Bot token grabbing
from dotenv import load_dotenv
import os

# Async
import asyncio

# Date and time
from zoneinfo import ZoneInfo
import datetime

# Database interaction
import aiosqlite as sql # Async wrapper for sqlite

# Important constants
TIMEZONE = ZoneInfo("Asia/Singapore")
DB = "database.db"

# Settings
CHALLENGE_TIME = datetime.time(hour=20, minute=35, second=0, tzinfo=TIMEZONE)

# Global variables
challenge_channel_id = {} # Dictionary of guild to challenge channel
challenge_guilds = [] # List of all challenge guilds

# Utility functions
def grab_token():
    # Function that grabs token from .env file.
    # Hi, my bot's token isn't public, sorry if you thought it was :v
    
    load_dotenv() # Loads .env file into os.environ
    
    if "BOT_TOKEN" in os.environ:
        return os.environ["BOT_TOKEN"]
    else:
        raise Exception("grab_token() failed. Bot token not found. Does .env exist in the same folder as main.py and have a BOT_TOKEN environment variable?")

async def fetch_challenge_data():
    
    global challenge_channel_id
    global challenge_guilds
    
    challenge_guilds = []
    challenge_channel_id = {}
    
    async with sql.connect(DB) as db:
        async with db.execute("SELECT guild, challenge_channel FROM guild_data") as cursor:
            values = await cursor.fetchall()
            for row in values:
                challenge_guilds.append(row[0])
                challenge_channel_id[ row[0] ] = row[1]
    
    print("Challenge data fetched!")
                
# Create bot for slash commands
command_sync_flags = commands.CommandSyncFlags.default()
command_sync_flags.sync_commands_debug = True
bot = commands.InteractionBot(
    command_sync_flags=command_sync_flags,
    test_guilds=[593099338096574466], # Personal Test Server ID
)

# Bot Startup
@bot.event
async def on_ready():
    challenge_update.start()
    print("The bot is ready!")

# IMPORTANT
# Commands!
@bot.slash_command(description="Gives you information about yourself!")
async def info(ctx : disnake.ApplicationCommandInteraction):
    auth = ctx.author
    
    display_name = auth.display_name
    avatar_url = auth.display_avatar.url
    
    info = ""
    
    # CF Username
    info += "Codeforces Username: "
    info += "NONE" # TODO: Replace with Codeforces username check
    info += "\n"
    
    info = info.strip()
    
    embed = disnake.Embed(
        title= f"{display_name}",
        description=f"{info}",
        color=disnake.Colour.yellow(),
        timestamp=datetime.datetime.now(),
    )
    
    if avatar_url is not None:
        embed.set_thumbnail(url=avatar_url)
    
    await ctx.response.send_message(embed=embed)
    
@bot.slash_command(description="Sets the challenge channel to the current channel!")
async def set_challenge_channel(ctx : disnake.ApplicationCommandInteraction):

    guildID = ctx.guild_id
    channelID = ctx.channel_id
    
    async with sql.connect(DB) as db:
        await db.execute("UPDATE OR IGNORE guild_data SET challenge_channel = ? WHERE guild = ?", (channelID, guildID))
        await db.execute("INSERT OR IGNORE INTO guild_data(challenge_channel, guild) VALUES(?, ?)", (channelID, guildID))
        await db.commit()

    asyncio.run_coroutine_threadsafe(fetch_challenge_data(), bot.loop)
    # To maintainer: This code is SLOW if the discord bot runs on multiple servers!
    # This is only acceptable due to the bot being built for one/two servers.
    
    await ctx.response.send_message("Challenge channel successfully set!")

# Tasks
@tasks.loop(hours=23, minutes=58)
async def challenge_update():
    cur_date = datetime.datetime.now(tz=TIMEZONE).date()
    should_perform_challenge_today = False
    async with sql.connect(DB) as db:
        async with db.execute('SELECT data FROM app_data WHERE key = "last_challenge_date"') as cursor:
            last_challenge_date = datetime.date.fromisoformat( (await cursor.fetchone())[0])
            # Fetch last challenge date, and converts it to datetime.date object
            
            if cur_date > last_challenge_date:
                should_perform_challenge_today = True
                
    print(f"Challenge check - should perform challenge? : {should_perform_challenge_today}")
    
    if should_perform_challenge_today:
        cur_dt = datetime.datetime.now(tz=TIMEZONE)
        chall_dt = datetime.datetime.combine(cur_date, CHALLENGE_TIME, tzinfo=TIMEZONE)
                    
        # Gets how long we need to wait till challenge begins today
        seconds_to_challenge_time = (chall_dt - cur_dt).total_seconds()
        
        # Waits until challenge time
        await asyncio.sleep(seconds_to_challenge_time)
        
        for guild in challenge_guilds:
            if challenge_channel_id[guild] is None:
                continue # Ignore this guild
            
            # Begin challenge!
            channelID = challenge_channel_id[guild]
            channel = await bot.fetch_channel(channelID)
            
            await channel.send("Test")
        
        async with sql.connect(DB) as db:
            await db.execute('UPDATE app_data SET data = ? WHERE key = "last_challenge_date"', (cur_date,))
            await db.commit()  
        
            
                

        
        
            

# Main Function
token = grab_token()
print("Bot token retrieval successful.")
asyncio.run(fetch_challenge_data())
bot.run(token)
