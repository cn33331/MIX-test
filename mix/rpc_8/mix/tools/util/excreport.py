from traceback import format_exception


def get_exc_desc(exc):
    return ''.join(format_exception(exc.__class__, exc, exc.__traceback__))
