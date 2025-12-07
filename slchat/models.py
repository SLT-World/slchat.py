class Struct:
    def __init__(self, **entries):
        for key, value in entries.items():
            if isinstance(value, dict):
                value = Struct(**value)
            self.__dict__[key] = value