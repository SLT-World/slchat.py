from slchat.models import Struct

class TypingIndicator:
    def __init__(self, ctx):
        self.ctx = ctx
        self.stopped = False

    async def __aenter__(self):
        await self.ctx.send_typing()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def stop(self):
        if not self.stopped:
            await self.ctx.stop_typing()
            self.stopped = True

class Context:
    def __init__(self, message, chat_id, bot):
        self.text = message["text"]
        self.before = message["before"] if "before" in message else None
        self.owner = message['owner'] if "owner" in message else None
        self.date = message['date'] if "before" in message else None
        self.id = message['id']
        self.bot = bot
        self.chat = self.bot.fetch_server(chat_id) or self.bot.fetch_dm(chat_id)
        self.invoked_subcommands = []
        self.invoked_with = None

    async def send(self, text, embed=None):
        return await self.bot.send(text, self.chat.id, embed)

    async def edit(self, text, embed=None):
        await self.bot.edit(text, self.id, self.chat.id, embed)

    async def delete(self):
        await self.bot.delete(self.id, self.chat.id)

    def typing(self):
        return TypingIndicator(self)

    async def send_typing(self):
        await self.bot.sio_instances[self.chat.id].emit('typing', namespace='/chat')

    async def stop_typing(self):
        await self.bot.sio_instances[self.chat.id].emit('stop_typing', namespace='/chat')

class Command:
    def __init__(self, name, func=None, description="", aliases=None, alias_of=None):
        self.name = name
        self.func = func
        self.description = description
        self.aliases = aliases or []
        self.alias_of = alias_of

class Group(Command):
    def __init__(self, name, func=None, description="", aliases=None, alias_of=None, invoke_without_command=False):
        super().__init__(name, func, description, aliases, alias_of)
        self.invoke_without_command = invoke_without_command
        self.subcommands = {}

    def command(self, *, name=None, description="", aliases=None):
        def decorator(func):
            command_name = name or func.__name__
            self.subcommands[command_name] = Command(command_name, func, description, aliases)
            if aliases:
                for alias in aliases:
                    self.subcommands[alias] = Command(alias, func, description, None, command_name)
            return func
        return decorator

    def group(self, *, name=None, description="", aliases=None, invoke_without_command=False):
        def decorator(func):
            group_name = name or func.__name__
            group = Group(group_name, func, description, aliases, None, invoke_without_command)
            self.subcommands[group_name] = group
            if aliases:
                for alias in aliases:
                    self.subcommands[alias] = Group(alias, func, description, None, group_name, invoke_without_command)
            return group
        return decorator