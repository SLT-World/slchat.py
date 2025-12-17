# slchat.py

**slchat.py** is an API wrapper for SLChat, written in Python.

## Quick Start
```py
import slchat
import asyncio

client = slchat.Bot(prefix="!")

@client.command()
async def ping(ctx):
    await ctx.send("Pong")

asyncio.run(client.run("token", "bot_id"))
```

## Links
- [Documentation](https://github.com/SLT-World/slchat.py/wiki/)