import requests, socketio, asyncio, aiohttp, uuid, time
import traceback

from slchat.context import Context
from slchat.models import Struct


domain = "slchat.alwaysdata.net"


class Bot:
    def __init__(self, prefix, debug=False):
        self.prefix = prefix
        self.debug = debug

        self.token = ""
        self.bot_id = ""
        self.servers = []
        self.dms = []

        self.sio_instances = {}
        self.user_socket = None
        self.session = None
        self.cache = {}
        self.user_cache = {}
        self.pending_temps = {}
        self.events = {}
        self.commands = {}
        self.waiters = {"message": []}

        self.send_lock = asyncio.Lock()
        self.last_send_time = 0

    def event(self, func):
        self.events[func.__name__] = func
        return func

    def command(self, *, aliases=[]):
        def decorator(func):
            self.commands[func.__name__] = func
            for alias in aliases:
                self.commands[alias] = func
            return func
        return decorator

    async def run_error(self, exception, context):
        if "on_error" in self.events:
            await self.events["on_error"](exception, context)

    async def run(self, token, bot_id):
        self.token = token
        self.bot_id = bot_id

        try:
            self.user_socket = socketio.AsyncClient(logger=self.debug, engineio_logger=self.debug)

            @self.user_socket.on('setup', namespace='/user')
            async def on_setup(data):
                await self.on_socket_user_setup(data)

            await self.user_socket.connect(f"https://{domain}", headers={"Cookie": f"op={self.bot_id}; token={self.token}"}, transports=["websocket"], namespaces=['/user'])
        except Exception as e:
            print(traceback.format_exc())
            await self.run_error(e, f"run - connection failed")

        self.session = aiohttp.ClientSession()

        await asyncio.create_task(self.cache_wipe_loop())
        await asyncio.Event().wait()

    async def on_socket_user_setup(self, data):
        self.user_cache[self.bot_id] = data["user"]
        self.servers = data["servers"]
        self.dms = data["dms"]
        await asyncio.gather(*(self.connect_to_chat(server["id"], "server") for server in self.servers))
        await asyncio.gather(*(self.connect_to_chat(dm["id"], "dm") for dm in self.dms))

        if "on_start" in self.events:
            await self.events["on_start"]()

    async def connect_to_chat(self, chat_id, chat_type):
        try:
            sio = socketio.AsyncClient(logger=self.debug, engineio_logger=self.debug)

            @sio.on('setup', namespace='/chat')
            async def on_socket_chat_setup(data):
                await self.on_socket_chat_setup(data)

            @sio.on('message_receive', namespace='/chat')
            async def on_socket_message_receive(data):
                await self.on_socket_message_receive(data, chat_id)

            @sio.on('message_change', namespace='/chat')
            async def on_socket_message_change(data):
                await self.on_socket_message_change(data, chat_id)

            @sio.on('chat_change', namespace='/chat')
            async def on_socket_chat_change(data):
                await self.on_socket_chat_change(data, chat_id)

            if chat_type == "server":
                @sio.on('user_add', namespace='/chat')
                async def on_socket_server_user_add(data):
                    await self.on_socket_server_user_add(data)

            await sio.connect(f"https://{domain}/chat?type={chat_type}&id={chat_id}&status=online", headers={"Cookie": f"op={self.bot_id}; token={self.token}"}, namespaces=['/chat'])
            self.sio_instances[chat_id] = sio
        except Exception as e:
            print(traceback.format_exc())
            await self.run_error(e, f"connect_to_chat - {chat_id}")

    async def on_socket_chat_setup(self, data):
        for member in data["users"]:
            self.user_cache[member["id"]] = member

    async def on_socket_chat_change(self, data, chat_id):
        self.servers[chat_id] = data

    async def on_socket_server_user_add(self, member):
        self.user_cache[member["id"]] = member

    """async def on_socket_server_user_remove(self, member):
        self.user_cache[member["id"]] = member"""

    async def on_socket_message_receive(self, data, chat_id):
        temp = data.get("temp")
        if temp and temp in self.pending_temps:
            future = self.pending_temps.pop(temp)
            if not future.done():
                future.set_result(data)
        await self.message_receive(data['message'], chat_id)

    async def on_socket_message_change(self, data, chat_id):
        if "on_message_edit" in self.events or "on_message_delete" in self.events:
            if 'owner' in data:
                data['owner'] = await self.get_user(data['owner'], True)
                if "bot" in data['owner']['badges']:
                    return
            if data["text"]:
                if "on_message_edit" in self.events:
                    context = Context(data, chat_id, self)
                    await self.events["on_message_edit"](context)
            else:
                if "on_message_delete" in self.events:
                    context = Context(data, chat_id, self)
                    await self.events["on_message_delete"](context)

    async def message_receive(self, message, chat_id):
        message['owner'] = await self.get_user(message['owner'], True)
        if "bot" in message['owner']['badges']:
            return
        context = Context(message, chat_id, self)
        self.dispatch("message", context)
        if "on_message" in self.events:
            await self.events["on_message"](context)
        if message['text'].startswith(self.prefix):
            parts = message['text'][len(self.prefix):].split(" ", 1)
            command_name = parts[0]
            argument = parts[1] if len(parts) > 1 else ""

            command_func = self.commands.get(command_name)
            if command_func:
                try:
                    if command_func.__code__.co_argcount > 1:
                        await command_func(context, argument)
                    else:
                        await command_func(context)
                except Exception as e:
                    await self.run_error(e, f"command: {command_name}")
            else:
                error_msg = f"Unknown command: {command_name}"
                await self.run_error(error_msg, "message_receive")

    async def send(self, text, chat_id):
        async with self.send_lock:
            now = time.monotonic()
            elapsed = now - self.last_send_time
            delay = max(0.0, 0.75 - elapsed)
            if delay > 0:
                await asyncio.sleep(delay)
            self.last_send_time = time.monotonic()
            if chat_id not in self.sio_instances:
                await self.run_error(f"Bot is not in chat [{chat_id}]", "send")
                return
            try:
                temp_id = str(uuid.uuid4())
                future = asyncio.get_running_loop().create_future()
                self.pending_temps[temp_id] = future
                await self.sio_instances[chat_id].emit('message_send', {"text": text, "temp": temp_id}, namespace='/chat')
                try:
                    message_data = await asyncio.wait_for(future, timeout=5)
                    message = message_data["message"]
                    return Context(message, chat_id, self)
                except asyncio.TimeoutError:
                    print("Timeout waiting for message confirmation")
                    return None
            except Exception as e:
                await self.run_error(e, "send")

    async def edit(self, text, message_id, chat_id):
        if chat_id not in self.sio_instances:
            await self.run_error(f"Bot is not in server [{chat_id}]", "edit")
            return
        try:
            await self.sio_instances[chat_id].emit('message_edit', {"id": message_id, "action": "edit", "text": text}, namespace='/chat')
        except Exception as e:
            await self.run_error(e, "edit")

    async def delete(self, message_id, chat_id):
        if chat_id not in self.sio_instances:
            await self.run_error(f"Bot is not in server [{chat_id}]", "delete")
            return
        try:
            await self.sio_instances[chat_id].emit('message_edit', {"id": message_id, "action": "delete"}, namespace='/chat')
        except Exception as e:
            await self.run_error(e, "delete")

    def dispatch(self, event, ctx):
        waiters = self.waiters.get(event, [])
        for check, future in waiters:
            if future.done():
                continue
            try:
                if check is None or check(ctx):
                    future.set_result(ctx)
                    self.waiters[event].remove((check, future))
            except:
                continue

    async def wait_for(self, event, check=None, timeout=None):
        if event not in self.waiters:
            self.waiters[event] = []
        future = asyncio.get_running_loop().create_future()
        self.waiters[event].append((check, future))
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            self.waiters[event].remove((check, future))
            raise

    async def change(self, key, value):
        try:
            response = requests.post(
                f"https://{domain}/api/change",
                data={"key": key, "value": value},
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                cookies={"token": self.token, "op": self.bot_id}
            )
            response.raise_for_status()
            print(f"Changed [{key}] into [{value}]")
        except Exception as e:
            await self.run_error(e, "change")

    async def cache_wipe_loop(self):
        while True:
            await asyncio.sleep(7200)
            self.cache.clear()

    async def get_json_cache(self, url):
        if url.startswith(f"https://{domain}/api/user/"):
            user_id = url.replace(f"https://{domain}/api/user/", "").replace("/", "")
            if user_id not in self.user_cache:
                async with self.session.get(url, cookies={"token": self.token, "op": self.bot_id}) as response:
                    response.raise_for_status()
                    self.user_cache[user_id] = await response.json()
            return self.user_cache[user_id]
        elif url not in self.cache:
            async with self.session.get(url, cookies={"token": self.token, "op": self.bot_id}) as response:
                response.raise_for_status()
                self.cache[url] = await response.json()
        return self.cache[url]

    async def get_user(self, id, is_json=False):
        try:
            json = await self.get_json_cache(f"https://{domain}/api/user/{id}/")
            return json if is_json else Struct(**json)
        except:
            return None

    async def get_user_by_username(self, username, is_json=False):
        for user in self.user_cache.values():
            if user["username"] == username:
                return user if is_json else Struct(**user)
        return None

    async def get_server(self, id):
        try:
            return Struct(**await self.get_json_cache(f"https://{domain}/api/server/{id}/"))
        except:
            return None
