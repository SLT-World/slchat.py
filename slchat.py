#Version 2.7

import requests, socketio, asyncio, aiohttp, uuid, time
import traceback

command_dict = {}
domain = "slchat.alwaysdata.net"

def command(name):
    def decorator(func):
        command_dict[name] = func
        return func
    return decorator

class Struct:
    def __init__(self, **entries):
        for key, value in entries.items():
            if isinstance(value, dict):
                value = Struct(**value)
            self.__dict__[key] = value

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
    def __init__(self, message, server_id, bot):
        self.text = message["text"]
        self.before = message["before"] if "before" in message else ""
        self.owner = Struct(**message['owner'])
        self.date = message['date']
        self.id = message['id']
        self.server_id = server_id
        self.bot = bot

    async def send(self, text):
        return await self.bot.send(text, self.server_id)

    async def edit(self, text):
        await self.bot.edit(text, self.id, self.server_id)

    async def delete(self):
        await self.bot.delete(self.id, self.server_id)

    def typing(self):
        return TypingIndicator(self)

    async def send_typing(self):
        await self.bot.sio_instances[self.server_id].emit("typing")

    async def stop_typing(self):
        await self.bot.sio_instances[self.server_id].emit("stop_typing")

class Bot:
    def __init__(self, prefix, on_error=None, on_start=None, on_message=None, on_message_edit=None, on_message_delete=None):
        self.prefix = prefix
        self.on_error = on_error
        self.on_start = on_start
        self.on_message = on_message
        self.on_message_edit = on_message_edit
        self.on_message_delete = on_message_delete

        self.token = ""
        self.bot_id = ""
        self.server_ids = []

        self.sio_instances = {}
        self.session = None
        self.cache = {}
        self.user_cache = {}
        self.pending_temps = {}
        self.waiters = {"message": []}

        self.send_lock = asyncio.Lock()
        self.last_send_time = 0

    async def run_error(self, exception, context):
        if self.on_error:
            await self.on_error(exception, context)

    async def run(self, token, bot_id):
        self.token = token
        self.bot_id = bot_id
        self.session = aiohttp.ClientSession()

        try:
            user_data = await self.get_json_cache(f"https://{domain}/api/user/{bot_id}/")
            self.server_ids = [str(s) for s in user_data.get("servers", [])]
            print(f"Servers: {self.server_ids}")
        except Exception as e:
            await self.run_error(e, "run - fetching user")
            return

        await asyncio.gather(*(self.connect_to_server(server_id) for server_id in self.server_ids))

        if self.on_start:
            await self.on_start()

        await asyncio.create_task(self.cache_wipe_loop())
        await asyncio.Event().wait()

    async def connect_to_server(self, server_id):
        try:
            sio = socketio.AsyncClient()
            sio.on('prompt', self.on_socket_message)
            sio.on('start', self.on_socket_start)
            sio.on('user_add', self.on_socket_user_add)
            sio.on('update', self.on_socket_message_update)
            await sio.connect(f"https://{domain}?server={server_id}&status=online", headers={ "Cookie": f"op={self.bot_id}; token={self.token}" })
            self.sio_instances[server_id] = sio
        except Exception as e:
            print(traceback.format_exc())
            await self.run_error(e, f"connect_to_server - {server_id}")

    async def on_socket_start(self, data):
        for member in data:
            self.user_cache[member["id"]] = member

    async def on_socket_user_add(self, member):
        self.user_cache[member["id"]] = member

    async def on_socket_message(self, data):
        temp = data.get("temp")
        if temp and temp in self.pending_temps:
            future = self.pending_temps.pop(temp)
            if not future.done():
                future.set_result(data)
        await self.check_new_command(data['message'], data['server_id'])

    async def on_socket_message_update(self, data):
        if self.on_message_edit or self.on_message_delete:
            data["message"]['owner'] = await self.get_user(data["message"]['owner'], True)
            if data["message"]['owner']['badge']['name'] == "Bot":
                return
            if data["action"] == "edit":
                if self.on_message_edit:
                    context = Context(data["message"], data["server"], self)
                    await self.on_message_edit(context)
            elif data["action"] == "delete":
                if self.on_message_delete:
                    context = Context(data["message"], data["server"], self)
                    await self.on_message_delete(context)

    async def check_new_command(self, message, server_id):
        message['owner'] = await self.get_user(message['owner'], True)
        if message['owner']['badge']['name'] == "Bot":
            return
        context = Context(message, server_id, self)
        self.dispatch("message", context)
        if self.on_message:
            await self.on_message(context)
        if message['text'].startswith(self.prefix):
            parts = message['text'][len(self.prefix):].split(" ", 1)
            command_name = parts[0]
            argument = parts[1] if len(parts) > 1 else ""

            command_func = command_dict.get(command_name)
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
                await self.run_error(error_msg, "check_new_command")

    async def send(self, text, server_id):
        async with self.send_lock:
            now = time.monotonic()
            elapsed = now - self.last_send_time
            delay = max(0.0, 0.75 - elapsed)
            if delay > 0:
                await asyncio.sleep(delay)
            self.last_send_time = time.monotonic()
            if server_id not in self.sio_instances:
                await self.run_error(f"Bot is not in server [{server_id}]", "send")
                return
            try:
                temp_id = str(uuid.uuid4())
                future = asyncio.get_running_loop().create_future()
                self.pending_temps[temp_id] = future
                await self.sio_instances[server_id].emit('message', {"text": text, "temp": temp_id})
                try:
                    message_data = await asyncio.wait_for(future, timeout=5)
                    message = message_data["message"]
                    server_id = message_data["server_id"]
                    return Context(message, server_id, self)
                except asyncio.TimeoutError:
                    print("Timeout waiting for message confirmation")
                    return None
            except Exception as e:
                await self.run_error(e, "send")

    async def edit(self, text, message_id, server_id):
        if server_id not in self.sio_instances:
            await self.run_error(f"Bot is not in server [{server_id}]", "edit")
            return
        try:
            await self.sio_instances[server_id].emit('edit', {"id": message_id, "action": "edit", "text": text})
        except Exception as e:
            await self.run_error(e, "edit")

    async def delete(self, message_id, server_id):
        print("Hey")
        if server_id not in self.sio_instances:
            await self.run_error(f"Bot is not in server [{server_id}]", "delete")
            return
        try:
            await self.sio_instances[server_id].emit('edit', {"id": message_id, "action": "delete"})
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
                data={"change_key": key, "change_value": value},
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                cookies={"token": self.token, "op": self.bot_id}
            )
            response.raise_for_status()
            print(f"Changed [{key}] into [{value}]")
        except Exception as e:
            await self.run_error(e, "change")

    async def cache_wipe_loop(self):
        while True:
            await asyncio.sleep(7200) # 2 hour
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

EMBED_ICONS = {
    "error":    "bx-x-circle",
    "warn":     "bx-alert-triangle",
    "info":     "bx-info-circle",
    "success":  "bx-check-circle",
    "note":     "bx-note",
    "clean":    None,
    "default":  None
}

class Embed:
    def __init__(self, embed_type="default", title="", description="", color=""):
        self.embed_type = embed_type
        self.title = title
        self.color = color
        self.icon = ""
        self.description = description
        self.attachment = ""
        self.author_html = ""
        self.fields_html = []
        self.spoiler = False

    def set_type(self, embed_type):
        self.embed_type = embed_type
        return self

    def set_title(self, text):
        self.title = text
        return self

    def set_icon(self, icon):
        self.icon = icon
        return self

    def set_color(self, color):
        self.color = color
        return self

    def set_description(self, text):
        self.description = text
        return self

    def set_attachment(self, url, spoiler=False):
        self.attachment = url
        self.spoiler = spoiler
        return self

    def set_author(self, title, url):
        self.author_html = f"<div class='center gap'><img class='avatar' loading='lazy' src='{url}'>{title}</div>"
        return self

    def add_field(self, name, value, inline=False, color=None, icon=None):
        style = f" style='color: {color};'" if color else ""
        icon_html = f"<i class='bx {icon}'></i>" if icon else ""
        inline_html = " inline" if inline else ""

        value_html = f"<p class='center gap'{style}>{icon_html}{value}</p>" if color or icon else value

        field_html = f"<div class='center gap{inline_html}'><strong>{name}</strong> {value_html if isinstance(value_html, str) else value}</div>"
        self.fields_html.append(field_html)
        return self

    def build(self):
        icon = self.icon if self.icon else EMBED_ICONS.get(self.embed_type)
        type_class = f" {self.embed_type}" if self.embed_type != "default" else ""
        icon_parent_class = "" if icon else " block"
        icon_html = f"<i class='bx {icon}'></i><div class='inline'>" if icon else ""
        icon_end_html = "</div>" if icon else ""
        attachment_html = f"<img class='attachment{" spoiler" if self.spoiler else ""}' src='{self.attachment}'>" if self.attachment else ""
        title_html = f"<h4>{self.title}</h4>" if self.title else ""
        color_html = f" style='--color:{self.color};'" if self.color else ""

        return (
            f"<div class='embed{icon_parent_class}{type_class}'{color_html}>"
            f"{icon_html}"
            f"{self.author_html}"
            f"{title_html}"
            f"{self.description}"
            f"{''.join(self.fields_html)}"
            f"{attachment_html}"
            f"{icon_end_html}"
            f"</div>"
        )