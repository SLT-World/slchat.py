from slchat.classes import TypingIndicator


class Context:
    def __init__(self, message, chat_id, bot):
        self.text = message["text"]
        self.before = message["before"] if "before" in message else None
        self.owner = message['owner'] if "owner" in message else None
        self.date = message['date'] if "before" in message else None
        self.id = message['id']
        self.bot = bot
        self.chat = self.bot.get_server(chat_id) or self.bot.get_dm(chat_id)
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