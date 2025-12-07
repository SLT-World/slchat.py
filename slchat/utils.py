from slchat.models import Struct


def find(predicate, iterable):
    for item in iterable:
        if isinstance(item, dict):
            item = Struct(**item)
        if predicate(item):
            return item
    return None


def get(iterable, **attrs):
    for item in iterable:
        if isinstance(item, dict):
            item = Struct(**item)
        if all(getattr(item, attr, None) == value for attr, value in attrs.items()):
            return Struct(**item)
    return None
