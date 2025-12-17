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
