class Struct:
    def __init__(self, **entries):
        for key, value in entries.items():
            self.__dict__[key] = self._convert(value)

    def __contains__(self, item):
        return item in self.__dict__

    def __repr__(self):
        return f"Struct({self.__dict__})"

    def _convert(self, value):
        if isinstance(value, dict):
            return Struct(**value)
        if isinstance(value, list):
            return [self._convert(v) for v in value]
        if isinstance(value, tuple):
            return tuple(self._convert(v) for v in value)
        if isinstance(value, set):
            return {self._convert(v) for v in value}
        return value

    def items(self):
        return self.__dict__.items()

    def keys(self):
        return self.__dict__.keys()

    def values(self):
        return self.__dict__.values()