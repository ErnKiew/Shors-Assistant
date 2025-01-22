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

# Logging
import logging

# Async Request
import aiohttp

# Miscellaneous
import typing
import random

# Important constants
TIMEZONE = ZoneInfo("Asia/Singapore")
UTC = ZoneInfo("UTC")
DB = "database.db"
REQUEST_DELAY = 2 # Delay between requests

# Settings
CHALLENGE_TIME = datetime.time(hour=21, minute=0, second=0, tzinfo=UTC)
CHALLENGE_RATINGS = [800, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 2800, 3000, 3200, 3400]
MIN_CHALLENGE_CONTEST_ID = 1000

# Global variables
challenge_channel_id = {} # Dictionary of guild to challenge channel
challenge_guilds = [] # List of all challenge guilds

# Logging
logger = logging.getLogger('disnake')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='disnake.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

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
    
async def get_scoring(rating):
    return 10 + (rating-800)//100

# Gets Codeforces url from contestId and index 
async def get_cf_url(contestID, index):
    return f"https://codeforces.com/problemset/problem/{contestID}/{index}"

# Given a list of tuples of {slugs (str), parameters (dicts)}, return an ordered list of responses.
# If successful, a dict (parsed json) will be returned
# Otherwise, the status code is returned
async def make_cf_requests(requests : list[tuple[str, dict]]) -> list[dict | int]:
    responses = []
    async with aiohttp.ClientSession('https://codeforces.com/api/') as session:
        for req in requests:
            async with session.get(req[0], params=req[1]) as resp:
                status = resp.status
                
                if 200 <= status and status <= 299: # 2XX successful
                    responses.append( await resp.json() )
                else:
                    responses.append(status)
            
            await asyncio.sleep(REQUEST_DELAY) # Delay requests
    
    return responses

# Updates database for new codeforces handle
async def db_update_handle(userID, handle):
    async with sql.connect(DB) as db:
        await db.execute("UPDATE OR IGNORE user_data SET codeforcesHandle = ? WHERE userID = ?", (handle, userID))
        await db.execute("INSERT OR IGNORE INTO user_data(userID, codeforcesHandle, score) VALUES(?, ?, ?)", (userID, handle, 0))
        await db.commit()
        
# Generates challenge set
# In particular, returns a dict of {rating: problemJSON}
async def generate_challenge_set():
    candidates = {}
    # Rating to list of jsons
    
    pset_req = ("problemset.problems", {})
    pset_result = (await make_cf_requests([pset_req]))[0]
    
    while True:
        if isinstance(pset_result, int):
            print(f"Error (CHALLENGE PSET): Codeforces responded with a status code of {pset_result}!")
            await asyncio.sleep(60)
            continue
        elif pset_result["status"] != "OK":
            print(f"Error (CHALLENGE PSET): Codeforces responded with a status string of {pset_result['status']}!")
            await asyncio.sleep(60)
            continue
        else:
            pset_result = pset_result["result"]["problems"]
            
            for problem in pset_result:
                if "contestId" not in problem:
                    # Reject due to no contestID
                    continue
                
                if "rating" not in problem:
                    # Reject due to no rating
                    continue
                
                '''
                if "type" not in problem or problem["type"] != "CF":
                    # Reject non-CF (ICPC or IOI or ...)
                    continue
                '''  
                
                try:
                    if problem["contestId"] <= MIN_CHALLENGE_CONTEST_ID:
                        # Reject due to too low contestID (recency check)
                        continue
                except:
                    continue # Not even a normal contestID
                
                if problem["rating"] not in candidates:
                    candidates[problem["rating"]] = []
                
                candidates[problem["rating"]].append(problem)   
                
            break                 
    
    challenge_set = {}
    for rating in CHALLENGE_RATINGS:
        challenge_set[rating] = candidates[rating][random.randint(0, len(candidates[rating]) - 1)]
        
    return challenge_set

async def create_challenge_set_embed(challenge_set):
    cur_date = datetime.datetime.now(tz=TIMEZONE).date()
    challenge_description = ""
    for rating in CHALLENGE_RATINGS:
        problem = challenge_set[rating]
        cf_url = await get_cf_url(problem["contestId"], problem["index"])
        challenge_description += f"# {rating}-rating!\n"
        challenge_description += f"[{problem['name']}]({cf_url})\n"
                
    dateString = cur_date.isoformat()
        
    embed = disnake.Embed(
        title= f"Challenge for {dateString}!",
        description=challenge_description,
        color=disnake.Colour.random(),
        timestamp=datetime.datetime.now(),
    )
        
    return embed

# Create bot for slash commands
command_sync_flags = commands.CommandSyncFlags.default()
command_sync_flags.sync_commands_debug = True
bot = commands.InteractionBot(
    command_sync_flags=command_sync_flags,
    # test_guilds=[593099338096574466], # Personal Test Server ID
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
    
    await ctx.response.defer()
    
    auth = ctx.author
    
    auth_id = auth.id
    
    avatar_url = ""
    
    info = ""
    
    # CF Username
    CF_user = None
    score = 0
    async with sql.connect(DB) as db:
        async with db.execute("SELECT codeforcesHandle, score FROM user_data WHERE userID = ?", (auth_id,)) as cursor:
            value = await cursor.fetchone()
            if value is not None:
                CF_user = value[0]
                if value[1] is not None:
                    score = value[1]
                
    info += f"# {CF_user}\n"
    
    if CF_user is not None:
        user_req = ("user.info", {"handles": f"{CF_user}"})
        res = (await make_cf_requests([user_req]))
        user_result = res[0]
        
        rank = ""
        max_rank = ""
        
        # Handle user_result
        if isinstance(user_result, int):
            info += f"Error (USER): Codeforces responded with a status code of {user_result}!\nThe API may be down, do not contact Shor for this error unless you are sure it is a problem with the bot.\n"
        elif user_result["status"] != "OK":
            info += f"Error (USER): Codeforces responded with a status string of { user_result['status'] }!\nCheck that your handle is correct, the API may also be down.\n"
        else:
            user_result = user_result["result"][0]
            
            avatar_url = user_result["avatar"]
            rank = user_result["rank"]
            max_rank = user_result["maxRank"]
            
            info += f"Rank: {rank}\n"
            info += f"Max Rank: {max_rank}\n"
    
    info += f"Challenge Score: {score}\n"
    
    info = info.strip()
    
    embed = disnake.Embed(
        title= f"{auth.display_name}",
        description=f"{info}",
        color=disnake.Colour.blurple(),
        timestamp=datetime.datetime.now(),
    )
    
    if avatar_url is not None:
        embed.set_thumbnail(url=avatar_url)
    
    await ctx.edit_original_response(embed=embed)
    
@bot.slash_command(description="Link your discord and codeforces account!")
async def register(ctx : disnake.ApplicationCommandInteraction, cf_handle : str):
    await ctx.response.defer()
    
    auth = ctx.author
    user_req = ("user.info", {"handles": f"{cf_handle}"})
    pset_req = ("problemset.problems", {})
    res = (await make_cf_requests([user_req, pset_req]))
    user_result = res[0]
    pset_result = res[1]
    
    avatar_url = ""
    rank = None
    max_rank = None
    
    # Handle user_result
    if isinstance(user_result, int):
        await ctx.edit_original_response(content=f"Error (USER): Codeforces responded with a status code of {user_result}!\nThe API may be down, do not contact Shor for this error unless you are sure it is a problem with the bot.")
        return
    elif user_result["status"] != "OK":
        await ctx.edit_original_response(f"Error (USER): Codeforces responded with a status string of { user_result['status'] }!\nCheck that your handle is correct, the API may also be down.")
        return
    else:
        user_result = user_result["result"][0]
        
        avatar_url = user_result["avatar"]
        if rank in user_result:
            rank = user_result["rank"]
        if max_rank in user_result:
            max_rank = user_result["maxRank"]
        
    # Pick random problem
    if isinstance(pset_result, int):
        await ctx.edit_original_response(content=f"Error (PSET): Codeforces responded with a status code of {pset_result}!\nThe API may be down, do not contact Shor for this error unless you are sure it is a problem with the bot.")
        return
    elif pset_result["status"] != "OK":
        await ctx.edit_original_response(content=f"Error (PSET): Codeforces responded with a status string of {pset_result['status']}!\nCheck that your handle is correct, the API may also be down.")
        return
    else:
        pset_result = pset_result["result"]["problems"]
        
        problem_passed_checks = False
        problem = None
        problem_url = None
        while not problem_passed_checks:
            random_problem_idx = random.randint(0, len(pset_result) - 1)
            problem = pset_result[random_problem_idx]
            
            if "contestId" in problem:
                problem_url = await get_cf_url(problem["contestId"], problem["index"])
                problem_passed_checks = True
        
        embed = disnake.Embed(
            title= f"{cf_handle}",
            description=f"Max Rank: {max_rank}\nRank: {rank}\n\nIf this is you, please submit a Compile Error to the problem below within 60 seconds. (click the button!)",
            color=disnake.Colour.yellow(),
            timestamp=datetime.datetime.now(),
        )
        embed.set_thumbnail(url=avatar_url)
        
        await ctx.edit_original_response(embed=embed, components=[
            disnake.ui.Button(label="Click me!", style=disnake.ButtonStyle.link, url=problem_url)
        ])
        
        await asyncio.sleep(60)
        
        sub_req = ("user.status", {"handle": cf_handle, "count": 10})
        sub_result = (await make_cf_requests([sub_req]))[0]
        
        # Get submissions
        verified = False
        
        if isinstance(sub_result, int):
            await ctx.edit_original_response(content=f"Error (SUB): Codeforces responded with a status code of {sub_result}!\nThe API may be down, do not contact Shor for this error unless you are sure it is a problem with the bot.")
            return
        elif sub_result["status"] != "OK":
            await ctx.edit_original_response(f"Error (SUB): Codeforces responded with a status string of {sub_result['status']}!\nCheck that your handle is correct, the API may also be down.")
            return
        else:
            sub_result = sub_result["result"]
            for sub in sub_result:
                isSameProblem = ((sub["problem"]["contestId"] == problem["contestId"]) and (sub["problem"]["index"] == problem["index"]))
                
                if "verdict" in sub and sub["verdict"] == "COMPILATION_ERROR" and isSameProblem:
                    verified = True
        
        if verified:
            await db_update_handle(auth.id, cf_handle)
            embed = disnake.Embed(
                title= f"{cf_handle} verified!",
                description=f"Handle verified!",
                color=disnake.Colour.green(),
                timestamp=datetime.datetime.now(),
            )
            await ctx.edit_original_response(embed=embed, components=[])
        else:
            embed = disnake.Embed(
                title= f"Verification failed.",
                description=f"Did you submit a Compile Error to the problem on the correct account within 60 seconds? If not, please retry.",
                color=disnake.Colour.red(),
                timestamp=datetime.datetime.now(),
            )
            await ctx.edit_original_response(embed=embed, components=[])
    
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
    
@bot.slash_command(description="Tell the bot you've completed today's challenge!")
async def complete_challenge(ctx : disnake.ApplicationCommandInteraction, rating : int):
    await ctx.response.defer()
    userID = ctx.author.id
    cur_chall_date = None
        
    async with sql.connect(DB) as db:
        async with db.execute('SELECT data FROM app_data WHERE key = "last_challenge_date"') as cursor:
            fetched = await cursor.fetchone()
            
            if fetched is None:
                print("ERROR: last_challenge_date is not found in app_data table")
            else:
                cur_chall_date = datetime.date.fromisoformat(fetched[0])
    
    fetched = None
    fetched_problem = None
    async with sql.connect(DB) as db:
        async with db.execute('SELECT codeforcesHandle, lastChallengeDate, score FROM user_data WHERE userID = ?', (userID,)) as cursor:
            fetched = await cursor.fetchone()
            
        async with db.execute('SELECT problemContestID, problemIndex FROM challenge_data WHERE date = ? AND rating = ?', (cur_chall_date.isoformat(), rating)) as cursor:
            fetched_problem = await cursor.fetchone()
            
    if fetched is None or fetched[0] is None:
        await ctx.edit_original_response(content=f"You have not registered with this bot yet! Do /register.")
        return
    
    cf_handle = fetched[0]
    last_challenge_date = datetime.date.fromisoformat( fetched[1] )
    init_score = fetched[2]
    
    if last_challenge_date >= cur_chall_date:
        await ctx.edit_original_response(content=f"You have already completed today ({cur_chall_date.isoformat()})'s challenge! You may only complete one challenge per day.")
        return
    
    if fetched_problem is None:
        await ctx.edit_original_response(content=f"The challenge of {cur_chall_date.isoformat()} at rating of {rating} does not exist!")
        return
    
    problemContestID = fetched_problem[0]
    problemIndex = fetched_problem[1]
    
    sub_req = ("user.status", {"handle": cf_handle, "count": 30})
    sub_result = (await make_cf_requests([sub_req]))[0]
    
    # Get submissions
    verified = False
    
    if isinstance(sub_result, int):
        await ctx.edit_original_response(content=f"Error (SUB): Codeforces responded with a status code of {sub_result}!\nThe API may be down, do not contact Shor for this error unless you are sure it is a problem with the bot.")
        return
    elif sub_result["status"] != "OK":
        await ctx.edit_original_response(f"Error (SUB): Codeforces responded with a status string of {sub_result['status']}!\nCheck that your handle is correct, the API may also be down.")
        return
    else:
        sub_result = sub_result["result"]
        for sub in sub_result:
            isSameProblem = ((sub["problem"]["contestId"] == problemContestID) and (sub["problem"]["index"] == problemIndex))
            
            if "verdict" in sub and sub["verdict"] == "OK" and isSameProblem:
                verified = True
                
    if not verified:
        await ctx.edit_original_response(content=f"No AC submission was detected in your last 30 submissions to the problem {problemContestID}{problemIndex}!\nPlease double check that you have the right problem, and/or resubmit your solution.")
        return
    
    # Verified
    score_increase = await get_scoring(rating)
    async with sql.connect(DB) as db:
        await db.execute('UPDATE user_data SET score = score + ? WHERE userID = ?', (score_increase, userID,))
        await db.execute('UPDATE user_data SET lastChallengeDate = ? WHERE userID = ?', (cur_chall_date, userID,))
        await db.commit()
        
    await ctx.edit_original_response(content=f"Your AC submission has successfully been detected! {score_increase} has been added to your score, making it {init_score + score_increase}.")

# Tasks
@tasks.loop(time=[CHALLENGE_TIME])
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
        
        challenge_set = await generate_challenge_set()
        
        embed = await create_challenge_set_embed(challenge_set)
        
        for guild in challenge_guilds:
            if challenge_channel_id[guild] is None:
                continue # Ignore this guild
            
            
            # Begin challenge!
            channelID = challenge_channel_id[guild]
            channel = await bot.fetch_channel(channelID)
            
            
            await channel.send(embed=embed)
        
        async with sql.connect(DB) as db:
            await db.execute('UPDATE app_data SET data = ? WHERE key = "last_challenge_date"', (cur_date,))
            
            for rating in CHALLENGE_RATINGS:
                problem = challenge_set[rating] 
                await db.execute("INSERT INTO challenge_data(date, rating, problemContestID, problemIndex) VALUES(?, ?, ?, ?)", (cur_date, rating, problem["contestId"], problem["index"]))
            
            await db.commit()  
            
        
            
                

        
        
            

# Main Function
token = grab_token()
print("Bot token retrieval successful.")
asyncio.run(fetch_challenge_data())
bot.run(token)
