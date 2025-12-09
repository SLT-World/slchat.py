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