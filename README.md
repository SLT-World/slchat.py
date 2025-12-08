# slchat.py

**slchat.py** is a python API wrapper for SLChat.

## Short Example
```py
import slchat
import asyncio

client = slchat.Bot(prefix="!")

@client.command()
async def ping(ctx):
    await ctx.send("Pong")

asyncio.run(client.run("token", "bot_id"))
```

## Events
Events are registered using the `@client.event` decorator.
```py
@client.event
async def on_ready():
    print('Ready')
    
@client.event
async def on_message(ctx):
    print(f"New Message: {ctx.text}")
```

### Connection
```
on_connect()
```
Called when the bot connects to SLChat. This is not the same as the bot being fully initialized.

```
on_ready()
```
Called when the bot is fully initialized.
### Messages
```
on_message(context)
```
Called when a new message is received.
```
on_message_edit(context)
```
Called when a message is updated.
```
on_message_delete(context)
```
Called when a message is deleted.

### Servers
```
on_server_join(server)
```
Called when the bot joins a server.
```
on_server_remove(server)
```
Called when the bot is removed from a server.
```
on_server_update(server)
```
Called when a server is updated.

### DMs
```
on_dm_join(dm)
```
Called when a DM is created.
```
on_dm_remove(dm)
```
Called when a DM is removed.

### Users
```
on_user_join(user, server)
```
Called when a user joins a server.
```
on_user_remove(user, server)
```
Called when a user leaves a server.

### Others
```
on_typing(chat, user)
```
Called when a user starts typing in a chat.
```
on_error(exception, context)
```
Called when an error occurs.