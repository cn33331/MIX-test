import logging
from logging import handlers
from queue import SimpleQueue
import re
import sys

try:
    import zmq
    from zmq.log.handlers import PUBHandler
    ZMQ_AVAILABLE = True
except ImportError:
    zmq = None
    PUBHandler = None
    ZMQ_AVAILABLE = False
import threading
import time
import sys
from functools import wraps
import os
from pathlib import Path
from .misc import short_id
from logging import LoggerAdapter

DEFAULT_LOG_FORMAT = '%(asctime)s, %(levelname)s, %(name)s, %(filename)s:%(lineno)s | %(message)s'
MIX_LOG_DIRECTORY = '/var/tmp/mix'


def create_pub_handler(topic, url, fmt='#%(filename)s:%(lineno)s > %(message)s'):
    """
    after you add the handler to the logger, to get the log message, do
    python -m zmq.log -t [topic] --align [end_point]
    where topic is the name you give it
    """
    if ZMQ_AVAILABLE and PUBHandler:
        zmq_log_handler = PUBHandler(url)
        zmq_log_handler.setFormatter(logging.Formatter(fmt))
        zmq_log_handler.setRootTopic(topic)
        return zmq_log_handler
    else:
        # ZMQ not available, return a null handler
        return logging.NullHandler()

# TODO: make this decorator usable with or without params.
# https://stackoverflow.com/questions/653368/how-to-create-a-python-decorator-that-can-be-used-either-with-or-without-paramet


def log_entry(level=logging.DEBUG):
    """
    decorator to log the function call. The decorated method has to be the method
    of an instance with a logger property, because it assumes the frist argument is self
    and will proceed to use self.logger
    level is the log level of the message, default to DEBUG
    IMPORTANT: when using this decorator you must supply the level parameter
    """
    def wrap_f(func):
        @wraps(func)
        def wrapped(self, *args, **kwargs):
            msg = 'call {0} with {1} {2}'.format(func.__name__, args, kwargs)
            self.logger.log(level, msg)
            return func(self, *args, **kwargs)
        return wrapped
    return wrap_f


class PubListener(threading.Thread):

    def __init__(self, pub_url, topic, poll_interval=10):
        super(PubListener, self).__init__()
        self.subscribers = []
        self.listening = False
        self.pub_url = pub_url
        self.poll_interval = poll_interval
        self.topic = topic

    def run(self):
        # TODO: can this be aysncio compliant?
        # poll_interval is in milliseconds
        if not ZMQ_AVAILABLE or not zmq:
            # ZMQ not available, do nothing
            return
        
        self.listening = True
        try:
            ctx = zmq.Context()
            sub = ctx.socket(zmq.SUB)
            sub.subscribe(self.topic)
            sub.connect(self.pub_url)
            while self.listening:
                if sub.poll(self.poll_interval, zmq.POLLIN):
                    topic, msg = sub.recv_multipart()
                    # we are not sending multiple topics from the same publisher
                    # so just ignore the topic
                    # print('there are {0} subscribers'.format(len(self.subscribers)))
                    for s in self.subscribers:
                        s.got_message(msg.decode('utf8'))
            sub.disconnect(self.pub_url)
        except Exception as e:
            print(f"PubListener error: {e}")

    def stop(self):
        time.sleep(0.1)  # give it some time to get all the messages.
        self.listening = False


def safe_file_name(identity):
    """
    we create teh log name based on object's identity. mkae sure that's sa valid file name
    """
    return re.sub(r':|/|\\|\.', '_', identity)


class ContextFilter(logging.Filter):

    def __init__(self, id):
        super().__init__()
        self.id = id

    def filter(self, record):
        record.identity = self.id
        return True


def create_null_logger():
    logger = logging.getLogger('nothing')
    logger.addHandler(logging.NullHandler())
    return logger


def get_mix_logger(identity):
    '''
    get a logger that is in the current server namespace, so the log messages
    to this logger will show up in the server log file.
    The identity argument is something for you to distinguish your onw logger instance
    For instance, if you are trying to get a logger in teh server process "mix.server",
    get_mix_logger('foo') will return a logger with name "mix.server.foo"
    If you are running in a process without a mix server, meaning not a logger whose name starts
    with "mix" in the logger namespace, you will get the logger from DebugLogMaster
    '''
    server_logger_name = None
    for name, logger in logging.root.manager.loggerDict.items():
        if name.startswith("mix."):
            if isinstance(logger, logging.PlaceHolder):
                continue
            parts = name.split('.')
            if len(parts) == 2:  # this is the logger for the local server
                server_logger_name = name
                break

    if server_logger_name:
        return logging.getLogger(server_logger_name).getChild(identity)
    else:  # we are not running in a mix process
        dl = DebugLogMaster(identity)
        return dl.logger


def create_stdout_logger(id='terminal', level=logging.DEBUG):
    logger = logging.getLogger(id)
    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(DEFAULT_LOG_FORMAT)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

# QueueHandler doesn't need a format


def create_queue_logger(logger_name, q=None):
    """
    queue logger is very good for when you want to get to the log messages,
    like during testing
    """
    queue = q or SimpleQueue()
    h = handlers.QueueHandler(queue)
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.addHandler(h)
    return logger


def pop_queue_logger(queue_logger):
    """
    this doesn't return the last log item. It actually returns the
    first log item that hasn't been read
    """
    queue = queue_logger.handlers[0].queue
    if queue.empty():
        return None
    else:
        s = queue.get()
        return s.msg


def drain_queue_logger(queue_logger):
    q = queue_logger.handlers[0].queue
    items = []
    while not q.empty():
        record = q.get()
        items.append(record.msg)
    return items


def create_file_handler(topic, fmt, path=MIX_LOG_DIRECTORY):
    """
    to monitor the log real time use "tail -F [path_to_log_file]"
    """

    # make sure we have this path
    p = Path(path)
    p.mkdir(exist_ok=True)

    fn_topic = safe_file_name(topic)

    log_file_path = os.path.join(path, fn_topic + '_lynx.log')
    '''
    For now I am using WatchedFileHandler to help my debugging. Before deployment
    this should be changed to a WatchedRotatingFileHandler
    '''
    h = handlers.RotatingFileHandler(
        log_file_path, maxBytes=10e6, backupCount=2)
    h.setFormatter(logging.Formatter(fmt))
    return h


def create_log_publisher(queue, topic, fmt=DEFAULT_LOG_FORMAT, end_point=None):
    """
    the log publisher is acutally a QueueListener, it adds a file handler to the queue.
    If an end_point is specified, it also adds a ZMQPubHandler. So all log items will be
    written to a file, and optionally broadcast on a socket.
    """
    hh = [create_file_handler(topic, fmt)]
    if end_point:
        hh.append(create_pub_handler(topic, end_point, fmt))

    listener = handlers.QueueListener(queue, *hh)
    return listener


class LogMasterMixin():

    def __init__(self, *args, **kwargs):
        """
        this acts as a marker if setup_logger has every been called
        so that an object can choose nto to call setup_logger if
        it gets a logger from somewhere else, but the code can still
        call stop_logger. An example is ProxyFactory
        """
        self.log_publisher = None
        self._logger = None

        """
        It's best you put the LogMasterMixin as the left most parent class
        in your class definition. Because not every class is a good citizen
        and calls super().__init__(), for instance, the threading.Thread
        class. It that's not called on LogMasterMixin, you
        will not have the instance variables needed by the other methods of
        this class
        """
        super().__init__(*args, **kwargs)  # make sure the next one in the mro is called

    def setup_logger(self, identity, level=logging.DEBUG):
        self.log_queue = SimpleQueue()
        self.logger = create_queue_logger(identity, self.log_queue)
        self.logger.setLevel(level)
        self.log_publisher = create_log_publisher(self.log_queue, identity)
        self.log_publisher.start()

    def stop_logger(self):
        if self.log_publisher:
            self.log_publisher.stop()
            for handler in self.logger.handlers:
                handler.close()
            self.log_publisher = None

    @property
    def logger(self):
        return self._logger

    @logger.setter
    def logger(self, new_logger):
        """
        make sure we clean up the resources held my
        the QueueListener and PubListener if we
        ever switch out the logger
        """
        if self._logger:
            self.stop_logger()
        self._logger = new_logger


class DebugLogMaster(LogMasterMixin):
    """
    If you just need a plain logger, use this

    >>> from mix.tools.util.logfactory import DebugLogMaster
    >>> m = DebugLogMaster('mlog')
    >>> m.logger.info('something')
    >>> del m
    """

    def __init__(self, identity, level=logging.DEBUG):
        super().__init__()
        self.setup_logger(identity, level)

    def __del__(self):
        self.stop_logger()


class QueueLogger(LoggerAdapter):
    """A logger that saves all message in a queue.

    >>> import logging
    >>> from mix.tools.util.logfactory import QueueLogger
    >>> logger = QueueLogger('mylog', logging.DEBUG)
    >>> logger.getEffectiveLevel()
    10
    >>> logger.setLevel(logging.INFO)
    >>> logger.getEffectiveLevel()
    20
    >>> logger.info('msg1')
    >>> logger.debug('msg2')
    >>> logger.info('msg3')
    >>> logger.pop()
    'mylog_d3cad9 -> msg1  [<stdin>:1], [2021-06-19 21:34:49,983]'
    >>> logger.drain()
    ['mylog_d3cad9 -> msg3  [<stdin>:1], [2021-06-19 21:36:27,443]']
    >>>

    """

    def __init__(self, identity='', level=logging.INFO, fmt=DEFAULT_LOG_FORMAT):
        name = f'{identity}_{short_id(4)}'
        self.logger = self._make_logger(name, level, fmt)
        self.extra = None  # LoggerAdapter needs this

    def _make_logger(self, name, level=logging.INFO, fmt=DEFAULT_LOG_FORMAT):
        queue = SimpleQueue()
        h = handlers.QueueHandler(queue)
        h.setFormatter(logging.Formatter(fmt))
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.addHandler(h)
        return logger

    def getChild(self, name):
        lg = QueueLogger('')
        lg.logger = self._make_logger(f"{self.name}.{name}")
        # inherit the logging level
        lg.logger.setLevel(self.getEffectiveLevel())
        return lg

    def pop(self):
        """get the first unread message"""
        queue = self.logger.handlers[0].queue
        if queue.empty():
            return None
        else:
            s = queue.get()
            return s.msg

    def drain(self):
        q = self.logger.handlers[0].queue
        items = []
        while not q.empty():
            record = q.get()
            items.append(record.msg)
        return items
