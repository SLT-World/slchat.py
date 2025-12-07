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
        self.before = message["before"] if "before" in message else ""
        self.owner = message['owner'] if "owner" in message else None
        self.date = message['date'] if "before" in message else None
        self.id = message['id']
        self.bot = bot
        self.chat = self.bot.get_server(chat_id) or self.bot.get_dm(chat_id)

    async def send(self, text, embed=None):
        return await self.bot.send(text, self.chat.id, embed)

    async def edit(self, text, embed=None):
        await self.bot.edit(text, self.id, self.chat.id, embed)

    async def delete(self):
        await self.bot.delete(self.id, self.chat.id)

    def typing(self):
        return TypingIndicator(self)

    async def send_typing(self):
        await self.bot.sio_instances[self.chat.id].emit("typing")

    async def stop_typing(self):
        await self.bot.sio_instances[self.chat.id].emit("stop_typing")