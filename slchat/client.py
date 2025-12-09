import requests, socketio, asyncio, aiohttp, uuid, time
import traceback
import shlex
import inspect
import html

from slchat.classes import Context, Group, Command, Embed
from slchat.models import Struct


domain = "slchat.alwaysdata.net"


def convert_type(value, annotation, param):
    if annotation is inspect._empty:
        return value
    if isinstance(value, annotation):
        return value
    try:
        if annotation is bool:
            lowered = value.strip().lower()
            if lowered in ('yes', 'y', 'true', 't', '1', 'enable', 'on'):
                return True
            elif lowered in ('no', 'n', 'false', 'f', '0', 'disable', 'off'):
                return False
            else:
                raise ValueError()
        return annotation(value)
    except Exception:
        raise ValueError(f"Argument '{param.name}' expected {annotation.__name__}, got '{value}'")


class Bot:
    def __init__(self, prefix, debug=False):
        self.prefix = prefix
        self.debug = debug

        self.token = ""
        self._servers = {}
        self._dms = {}

        self.sio_instances = {}
        self.user_socket = None
        self.user = None
        self.session = None
        self._users = {}
        self._pending_temps = {}
        self.events = {}
        self.commands = {}
        self.waiters = {"message": []}

        self.send_lock = asyncio.Lock()
        self.last_send_time = 0

    @property
    def servers(self):
        return list(self._servers.values())

    @property
    def dms(self):
        return list(self._dms.values())

    @property
    def users(self):
        return list(self._users.values())

    def event(self, func):
        self.events[func.__name__] = func
        return func

    def group(self, *, name=None, description="", aliases=None, invoke_without_command=False):
        def decorator(func):
            group_name = name or func.__name__
            group = Group(group_name, func, description, aliases, None, invoke_without_command)
            self.commands[group_name] = group
            if aliases:
                for alias in aliases:
                    self.commands[alias] = Group(alias, func, description, None, group_name, invoke_without_command)
            return group
        return decorator

    def command(self, *, name=None, description="", aliases=None):
        def decorator(func):
            command_name = name or func.__name__
            self.commands[command_name] = Command(command_name, func, description, aliases)
            if aliases:
                for alias in aliases:
                    self.commands[alias] = Command(alias, func, description, None, command_name)
            return func
        return decorator

    async def run_error(self, exception, context):
        if "on_error" in self.events:
            await self.events["on_error"](exception, context)

    async def run(self, token: str, bot_id: str):
        self.token = token
        try:
            self.user_socket = socketio.AsyncClient(logger=self.debug, engineio_logger=self.debug)
            @self.user_socket.on('setup', namespace='/user')
            async def on_setup(data):
                await self.on_socket_user_setup(data)

            @self.user_socket.on('server_add', namespace='/user')
            async def on_server_add(data):
                await self.on_server_add(data)

            @self.user_socket.on('server_remove', namespace='/user')
            async def on_server_remove(server_id):
                await self.on_server_remove(server_id)

            @self.user_socket.on('dm_add', namespace='/user')
            async def on_dm_add(data):
                await self.on_dm_add(data)

            @self.user_socket.on('dm_remove', namespace='/user')
            async def on_dm_remove(dm_id):
                await self.on_dm_remove(dm_id)

            await self.user_socket.connect(f"https://{domain}", headers={"Cookie": f"op={bot_id}; token={self.token}"}, namespaces=['/user'])
        except Exception as e:
            print(traceback.format_exc())
            await self.run_error(e, f"run - Failed to connect user socket")
            raise RuntimeError("Failed to connect user socket") from e

        self.session = aiohttp.ClientSession()

        await asyncio.Event().wait()

    async def on_socket_user_setup(self, data):
        self.user = Struct(**data["user"])
        self._users[self.user.id] = self.user

        if "on_connect" in self.events:
            await self.events["on_connect"]()

        for server in data["servers"]:
            server["type"] = "server"
            self._servers[server["id"]] = Struct(**server)
            await self.connect_to_chat(server["id"], "server")

        for dm in data["dms"]:
            dm["type"] = "dm"
            self._dms[dm["id"]] = Struct(**dm)
            await self.connect_to_chat(dm["id"], "dm")

        if "on_ready" in self.events:
            await self.events["on_ready"]()

    async def connect_to_chat(self, chat_id: str, chat_type: str):
        try:
            sio = socketio.AsyncClient(logger=self.debug, engineio_logger=self.debug)

            @sio.on('setup', namespace='/chat')
            async def on_socket_chat_setup(data):
                await self.on_socket_chat_setup(data, chat_type)

            @sio.on('message_receive', namespace='/chat')
            async def on_socket_message_receive(data):
                await self.on_socket_message_receive(data, chat_id)

            @sio.on('message_change', namespace='/chat')
            async def on_socket_message_change(data):
                await self.on_socket_message_change(data, chat_id)

            @sio.on('chat_change', namespace='/chat')
            async def on_socket_chat_change(data):
                await self.on_socket_chat_change(data, chat_id, chat_type)

            @sio.on('user_typing', namespace='/chat')
            async def on_user_typing(data):
                await self.on_user_typing(data, chat_id, chat_type)

            if chat_type == "server":
                @sio.on('user_add', namespace='/chat')
                async def on_user_add(data):
                    await self.on_user_add(data, chat_id)

                @sio.on('user_remove', namespace='/chat')
                async def on_user_remove(user_id):
                    await self.on_user_remove(user_id, chat_id)

            await sio.connect(f"https://{domain}/chat?type={chat_type}&id={chat_id}&status=online", headers={"Cookie": f"op={self.user.id}; token={self.token}"}, namespaces=['/chat'])
            self.sio_instances[chat_id] = sio
        except Exception as e:
            print(traceback.format_exc())
            await self.run_error(e, f"connect_to_chat - {chat_id}")
            #raise RuntimeError(f"Failed to connect to chat {chat_id}") from e

    async def on_socket_chat_setup(self, data, chat_type: str):
        data["chat"]["users"] = []
        for user in data["users"]:
            member = Struct(**user)
            data["chat"]["users"].append(member)
            self._users[member.id] = member
        data["chat"]["type"] = chat_type
        chat_data = Struct(**data["chat"])
        if chat_type == "server":
            self._servers[chat_data.id] = chat_data
        else:
            self._dms[chat_data.id] = chat_data

    async def on_socket_chat_change(self, data, chat_id: str, chat_type: str):
        if chat_type == "server":
            before = self._servers[chat_id]
            self._servers[chat_id] = data
            if "on_server_update" in self.events:
                await self.events["on_server_update"](before, data)
        else:
            self._dms[chat_id] = data

    async def on_user_add(self, user, server_id: str):
        member = Struct(**user)
        server = self.get_server(server_id)
        server.users.append(member)
        self._users[member.id] = member
        if "on_user_join" in self.events:
            await self.events["on_user_join"](member, server)

    async def on_user_remove(self, user_id: str, server_id: str):
        server = self.get_server(server_id)
        for user in server.users:
            if user.id == user_id:
                server.users.remove(user)
                break
        if user_id in self._users:
            member = self._users[user_id]
            del self._users[user_id]
            if "on_user_remove" in self.events:
                await self.events["on_user_remove"](member, server)

    async def on_dm_add(self, data):
        dm_id = data["id"]
        data["type"] = "dm"
        dm = Struct(**data)
        self._dms[dm_id] = dm
        self.user.dms.append(dm_id)
        await self.connect_to_chat(dm_id, "dm")
        if "on_dm_join" in self.events:
            await self.events["on_dm_join"](dm)

    async def on_dm_remove(self, dm_id: str):
        if dm_id in self.user.dms:
            self.user.dms.remove(dm_id)
        if dm_id in self.sio_instances:
            sio = self.sio_instances.pop(dm_id)
            await sio.disconnect()
        if dm_id in self._dms:
            data = self._dms[dm_id]
            del self._dms[dm_id]
            if "on_dm_remove" in self.events:
                await self.events["on_dm_remove"](data)

    async def on_server_add(self, data):
        server_id = data["id"]
        data["type"] = "server"
        server = Struct(**data)
        self._servers[server_id] = server
        self.user.servers.append(server_id)
        await self.connect_to_chat(server_id, "server")
        if "on_server_join" in self.events:
            await self.events["on_server_join"](server)

    async def on_server_remove(self, server_id: str):
        if server_id in self.user.servers:
            self.user.servers.remove(server_id)
        if server_id in self.sio_instances:
            sio = self.sio_instances.pop(server_id)
            await sio.disconnect()
        if server_id in self._servers:
            data = self._servers[server_id]
            del self._servers[server_id]
            if "on_server_remove" in self.events:
                await self.events["on_server_remove"](data)

    async def on_user_typing(self, user_id, chat_id: str, chat_type: str):
        user = self.get_user(user_id)

        if chat_type == "server":
            chat = self.get_server(chat_id)
        else:
            chat = self.get_dm(chat_id)

        if "on_typing" in self.events:
            await self.events["on_typing"](chat, user)

    async def on_socket_message_receive(self, data, chat_id: str):
        temp = data.get("temp")
        if temp and temp in self._pending_temps:
            future = self._pending_temps.pop(temp)
            if not future.done():
                future.set_result(data)
        await self.message_receive(data['message'], chat_id)

    async def message_receive(self, message, chat_id: str):
        message['owner'] = self.get_user(message['owner'])
        message['text'] = html.unescape(message['text'])
        if "bot" in message['owner'].badges:
            return
        context = Context(message, chat_id, self)
        self.dispatch("message", context)
        if "on_message" in self.events:
            await self.events["on_message"](context)
        if message['text'].startswith(self.prefix):
            await self.process_command(context, message)

    async def process_command(self, ctx: Context, message):
        raw = message['text'][len(self.prefix):]

        try:
            parts = shlex.split(raw)
        except:
            await self.run_error("Invalid quotes in command", "process_command")
            return

        if not parts:
            return

        command_name = parts.pop(0)
        command_info = self.commands.get(command_name)
        if not command_info:
            await self.run_error(f"Unknown command: {command_name}", "process_command")
            return

        parent_command = command_info
        invoked_subcommands = []

        while isinstance(parent_command, Group):
            if parts and parts[0] in parent_command.subcommands:
                subcommand_name = parts.pop(0)
                invoked_subcommands.append(subcommand_name)
                parent_command = parent_command.subcommands[subcommand_name]
            else:
                break

        ctx.invoked_subcommands = invoked_subcommands
        ctx.invoked_with = command_name

        if isinstance(parent_command, Group):
            if parent_command.invoke_without_command:
                command_func = parent_command.func
            else:
                return await self.run_error(f"Unknown subcommand for group '{parent_command.name}'", "process_command")
        else:
            command_func = parent_command.func

        command_signature = inspect.signature(command_func)
        params = list(command_signature.parameters.values())[1:]

        required = sum(1 for p in params if p.default is inspect._empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))

        if len(parts) < required:
            await self.run_error(f"Missing arguments for command '{command_name}'", "process_command")
            return

        final_args = []
        final_kwargs = {}
        idx = 0
        remaining_text = " ".join(parts)

        for p in params:
            if p.kind == p.VAR_POSITIONAL:
                final_args.extend(convert_type(raw_arg, p.annotation, p) for raw_arg in parts[idx:])
                break
            elif p.kind == p.POSITIONAL_ONLY or p.kind == p.POSITIONAL_OR_KEYWORD:
                if idx < len(parts):
                    raw_arg = parts[idx]
                    idx += 1
                else:
                    raw_arg = p.default
                final_args.append(convert_type(raw_arg, p.annotation, p))
            elif p.kind == p.KEYWORD_ONLY:
                match = next((part for part in parts[idx:] if part.startswith(f"{p.name}=")), None)
                if match:
                    raw_value = match.split("=", 1)[1]
                    final_kwargs[p.name] = convert_type(raw_value, p.annotation, p)
                    parts.remove(match)
                else:
                    if remaining_text:
                        final_kwargs[p.name] = convert_type(remaining_text, p.annotation, p)
                        remaining_text = ""
                    elif p.default is not inspect._empty:
                        final_kwargs[p.name] = p.default
                    else:
                        return await self.run_error(f"Missing required keyword-only argument '{p.name}'", "process_command")
        try:
            await command_func(ctx, *final_args, **final_kwargs)
        except Exception as e:
            await self.run_error(e, f"Command: {command_name}")

    async def on_socket_message_change(self, data, chat_id: str):
        if "on_message_edit" in self.events or "on_message_delete" in self.events:
            if 'owner' in data:
                data['owner'] = self.get_user(data['owner'])
                if "bot" in data['owner'].badges:
                    return

            if data["text"]:
                data['text'] = html.unescape(data['text'])
                if data["before"]:
                    data['before'] = html.unescape(data['before'])
                if "on_message_edit" in self.events:
                    context = Context(data, chat_id, self)
                    await self.events["on_message_edit"](context)
            elif "on_message_delete" in self.events:
                if data["before"]:
                    data['before'] = html.unescape(data['before'])
                context = Context(data, chat_id, self)
                await self.events["on_message_delete"](context)


    async def send(self, text, chat_id: str, embed: Embed = None):
        text = str(text)
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
                self._pending_temps[temp_id] = future

                parts = []
                if text:
                    parts.append(text)
                if embed:
                    parts.append(embed.build())
                text = "\n".join(parts)

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

    async def edit(self, text, message_id: str, chat_id: str, embed = None):
        if chat_id not in self.sio_instances:
            await self.run_error(f"Bot is not in server [{chat_id}]", "edit")
            return
        try:
            parts = []
            if text:
                parts.append(str(text))
            if embed:
                parts.append(embed.build())
            text = "\n".join(parts)
            await self.sio_instances[chat_id].emit('message_edit', {"id": message_id, "action": "edit", "text": text}, namespace='/chat')
        except Exception as e:
            await self.run_error(e, "edit")

    async def delete(self, message_id: str, chat_id):
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

    async def change(self, key: str, value: str):
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

    def get_user(self, user_id: str):
        if user_id in self._users:
            return self._users[user_id]
        return None

    def get_server(self, server_id: str):
        if server_id in self._servers:
            return self._servers[server_id]
        return None

    def get_dm(self, dm_id: str):
        if dm_id in self._dms:
            return self._dms[dm_id]
        return None

    async def fetch_user(self, user_id):
        user = self.get_user(user_id)
        if user:
            return user
        else:
            try:
                async with self.session.get(f"https://{domain}/api/user/{user_id}", cookies={"token": self.token, "op": self.user.id}) as response:
                    response.raise_for_status()
                    json = await response.json()
                    user = Struct(**json)
                    self._users[user_id] = user
                    return user
            except Exception:
                return None

    async def fetch_server(self, server_id):
        server = self.get_server(server_id)
        if server:
            return server
        else:
            try:
                async with self.session.get(f"https://{domain}/api/server/{server_id}", cookies={"token": self.token, "op": self.user.id}) as response:
                    response.raise_for_status()
                    json = await response.json()
                    json["type"] = "server"
                    json["id"] = server_id
                    server = Struct(**json)
                    self._servers[server_id] = server
                    return server
            except Exception:
                return None