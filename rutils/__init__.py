"""
Contains useful functions and utilities that are not neccessarily only useful
for this module. But are also used in differing modules insidide the same
project, and so do not belong to anything specific.
"""

from __future__ import absolute_import, unicode_literals

import ast
import importlib
import inspect
import json
import logging
import os
import socket
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from logging import Formatter
from multiprocessing.util import register_after_fork

import requests
import unidecode
from concurrent_log_handler import ConcurrentRotatingFileHandler
from dateutil import parser, tz
from past.builtins import basestring
from pythonjsonlogger import jsonlogger
from sqlalchemy import TIMESTAMP, create_engine, types
from sqlalchemy.orm import scoped_session, sessionmaker

from .exceptions import UnicodeHandlerError
from .term import colored, safe_str

local_zone = tz.tzlocal()
utc_zone = tz.tzutc()

TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _set_json_formatter(logger, colorize=False):
    """
    Replace the default formatters by the json formatter
    """
    for handler in logger.handlers:
        handler.formatter = get_json_formatter(use_color=colorize)


def _get_proj_home(extra_frames=0):
    """Get the location of the caller module; then go up max_levels until
    finding requirements.txt"""

    def swimup(start):
        x = start
        max_level = 3
        while max_level:
            f = os.path.abspath(os.path.join(x, "requirements.txt"))
            p = os.path.abspath(os.path.join(x, "pyproject.toml"))
            if os.path.exists(f) or os.path.exists(p):
                return x
            x = os.path.abspath(os.path.join(x, ".."))
            max_level -= 1

    # first try with the current cwd
    proj_home = swimup(os.getcwd())
    if proj_home:
        return proj_home
    else:
        sys.stderr.write(
            "Couldn't identify project root from: {}. Going to inspect stackframe next".format(
                os.getcwd()
            )
        )

    frame = inspect.stack()[2 + extra_frames]
    module = inspect.getsourcefile(frame[0])
    if not module:
        raise Exception(
            "Sorry, wasnt able to guess your location. Let devs know about this issue."
        )

    d = os.path.dirname(module)
    proj_home = swimup(d)

    if proj_home:
        return proj_home
    else:
        sys.stderr.write(
            "Sorry, cant find the proj home; returning the location of the caller: %s\n" % d
        )
    return d


def get_date(timestr=None):
    """
    Always parses the time to be in the UTC time zone; or returns
    the current date (with UTC timezone specified)

    :param: timestr
    :type: str or None

    :return: datetime object with tzinfo=tzutc()
    """
    if timestr is None:
        return datetime.utcnow().replace(tzinfo=utc_zone)

    if isinstance(timestr, datetime):
        date = timestr
    else:
        date = parser.parse(timestr)

    if "tzinfo" in repr(date):  # hack, around silly None.encode()...
        date = date.astimezone(utc_zone)
    else:
        # this depends on current locale, for the moment when not
        # timezone specified, I'll treat them as UTC (however, it
        # is probably not correct and should work with an offset
        # but to that we would have to know which timezone the
        # was created)

        # local_date = date.replace(tzinfo=local_zone)
        # date = date.astimezone(utc_zone)

        date = date.replace(tzinfo=utc_zone)

    return date


def date2solrstamp(t):
    """
    Received datetime object and returns it formatted the way that
    SOLR likes (variation on the ISO format).

    @param t: datetime object (we expect it to be in UTC)
    @return: string
    """

    return t.strftime(TIMESTAMP_FMT)


def load_config(proj_home=None, extra_frames=0, app_name=None):
    """
    Loads configuration from config.py and also from local_config.py

    :param: proj_home - str, location of the home - we'll always try
        to load config files from there. If the location is empty,
        we'll inspect the caller and derive the location of its parent
        folder.
    :param: extra_frames - int, number of frames to look back; default
        is 2, which is good when the load_config() is called directly,
        but when called from inside classes, we need to add extra more

    :return dictionary
    """
    conf = {}

    if proj_home is not None:
        proj_home = os.path.abspath(proj_home)
        if not os.path.exists(proj_home):
            raise Exception("{proj_home} doesnt exist".format(proj_home=proj_home))
    else:
        proj_home = _get_proj_home(extra_frames=extra_frames)

    if proj_home not in sys.path:
        sys.path.append(proj_home)

    conf["PROJ_HOME"] = proj_home

    conf.update(load_module(os.path.join(proj_home, "config.py")))
    conf.update(load_module(os.path.join(proj_home, "local_config.py")))
    conf_update_from_env(app_name or conf.get("SERVICE", ""), conf)

    return conf


def conf_update_from_env(app_name, conf):
    app_name = app_name.replace(".", "_").upper()
    for key in list(conf.keys()):
        specific_app_key = "_".join((app_name, key))
        if specific_app_key in os.environ:
            # Highest priority: variables with app_name as prefix
            _replace_value(conf, key, os.environ[specific_app_key])
        elif key in os.environ:
            _replace_value(conf, key, os.environ[key])


def _replace_value(conf, key, new_value):
    logging.info(
        "Overwriting constant '%s' old value '%s' with new value '%s' from environment",
        key,
        conf[key],
        new_value,
    )
    try:
        w = json.loads(new_value)
        conf[key] = w
    except:  # noqa: E722
        try:
            # Interpret numbers, booleans, etc...
            conf[key] = ast.literal_eval(new_value)
        except:  # noqa: E722
            # String
            conf[key] = new_value


def load_module(filename):
    """
    Loads module, first from config.py then from local_config.py

    :return dictionary
    """

    filename = os.path.join(filename)
    module_spec = importlib.machinery.ModuleSpec("config", None)
    d = importlib.util.module_from_spec(module_spec)
    d.__file__ = filename
    try:
        with open(filename) as config_file:
            exec(compile(config_file.read(), filename, "exec"), d.__dict__)
    except IOError as e:  # noqa: F841
        pass
    res = {}
    from_object(d, res)
    return res


def setup_logging(name_, level=None, proj_home=None, attach_stdout=False):
    """
    Sets up generic logging to file with rotating files on disk

    :param: name_: the name of the logfile (not the destination!)
    :param: level: the level of the logging DEBUG, INFO, WARN
    :param: proj_home: optional, starting dir in which we'll
            check for (and create) 'logs' folder and set the
            logger there
    :return: logging instance
    """

    if level is None:
        config = load_config(extra_frames=1, proj_home=proj_home, app_name=name_)
        level = config.get("LOGGING_LEVEL", "INFO")

    level = getattr(logging, level)

    # formatter = logging.Formatter(fmt=logfmt, datefmt=datefmt)
    # formatter = MultilineMessagesFormatter(fmt=logfmt, datefmt=datefmt)
    formatter = get_json_formatter()

    formatter.multiline_marker = ""
    formatter.multiline_fmt = "     %(message)s"

    formatter.converter = time.gmtime
    logging_instance = logging.getLogger(name_)

    if proj_home:
        proj_home = os.path.abspath(proj_home)
        fn_path = os.path.join(proj_home, "logs")
    else:
        fn_path = os.path.join(_get_proj_home(), "logs")

    if not os.path.exists(fn_path):
        os.makedirs(fn_path)

    fn = os.path.join(fn_path, "{0}.log".format(name_.split(".log")[0]))
    rfh = ConcurrentRotatingFileHandler(
        filename=fn, maxBytes=10485760, backupCount=10, mode="a", encoding="UTF-8"
    )  # 10MB file
    rfh.setFormatter(formatter)
    logging_instance.handlers = []
    logging_instance.addHandler(rfh)
    logging_instance.setLevel(level)

    if attach_stdout:
        stdout = logging.StreamHandler(sys.stdout)
        stdout.formatter = get_json_formatter()
        logging_instance.addHandler(stdout)

    # Do not propagate to the parent logger to avoid double logging with different formatters
    logging_instance.propagate = False

    return logging_instance


def from_object(from_obj, to_obj):
    """Updates the values from the given object.  An object can be of one
    of the following two types:

    Objects are usually either modules or classes.
    Just the uppercase variables in that object are stored in the config.

    :param obj: an import name or object
    """
    for key in dir(from_obj):
        if key.isupper():
            to_obj[key] = getattr(from_obj, key)


def overrides(interface_class):
    """
    To be used as a decorator, it allows the explicit declaration you are
    overriding the method of class from the one it has inherited. It checks that
     the name you have used matches that in the parent class and returns an
     assertion error if not
    """

    def overrider(method):
        """
        Makes a check that the overrided method now exists in the given class
        :param method: method to override
        :return: the class with the overriden method
        """
        assert method.__name__ in dir(interface_class)
        return method

    return overrider


class ProjectWorker(object):
    """ProjectWorker - a generic class for applications


    This class should be instantiated inside tasks.py:

    class MyWorker(ProjectWorker)
       pass
    app = MyWorker()
    """

    def __init__(self, app_name, *args, **kwargs):
        """
        :param: app_name - string, name of the application (can be anything)
        :keyword: local_config - dict, configuration that should be applied
            over the default config (that is loaded from config.py and local_config.py)
        """
        proj_home = None
        if "proj_home" in kwargs:
            proj_home = kwargs.pop("proj_home")
        self._config = load_config(extra_frames=1, proj_home=proj_home, app_name=app_name)

        local_config = None
        if "local_config" in kwargs and kwargs["local_config"]:
            local_config = kwargs.pop("local_config")
            self._config.update(local_config)  # our config
        if not proj_home:
            proj_home = self._config.get("PROJ_HOME", None)
        self.logger = setup_logging(
            app_name,
            proj_home=proj_home,
            level=self._config.get("LOGGING_LEVEL", "INFO"),
            attach_stdout=self._config.get("LOG_STDOUT", False),
        )

        self._engine = self._session = None
        if self._config.get("SQLALCHEMY_URL", None):
            self._engine = create_engine(
                self._config.get("SQLALCHEMY_URL", "sqlite:///"),
                echo=self._config.get("SQLALCHEMY_ECHO", False),
            )
            self._session_factory = sessionmaker()
            self._session = scoped_session(self._session_factory)
            self._session.configure(bind=self._engine)
            register_after_fork(self._engine, self._engine.dispose)

        # HTTP connection pool
        # - The maximum number of retries each connection should attempt: this
        #   applies only to failed DNS lookups, socket connections and connection timeouts,
        #   never to requests where data has made it to the server. By default,
        #   requests does not retry failed connections.
        # http://docs.python-requests.org/en/latest/api/?highlight=max_retries#requests.adapters.HTTPAdapter
        self.client = requests.Session()
        http_adapter = requests.adapters.HTTPAdapter(
            pool_connections=self._config.get("REQUESTS_POOL_CONNECTIONS", 10),
            pool_maxsize=self._config.get("REQUESTS_POOL_MAXSIZE", 1000),
            max_retries=self._config.get("REQUESTS_POOL_RETRIES", 3),
            pool_block=False,
        )
        self.client.mount("http://", http_adapter)

    @property
    def config(self):
        return self._config

    def _get_callers_module(self):
        frame = inspect.stack()[2]
        m = inspect.getmodule(frame[0])
        if m.__name__ == "__main__":
            parts = m.__file__.split(os.path.sep)
            return "%s.%s" % (parts[-2], parts[-1].split(".")[0])
        return m.__name__

    def close_app(self):
        """Closes the app"""
        self._session = self._engine = self._session_factory = None
        self.logger = None

    @contextmanager
    def db_session(self):
        """Provides a transactional session - ie. the session for the
        current thread/work of unit.

        Use as:

            with app.db_session() as session:
                o = ModelObject(...)
                session.add(o)
        """

        if self._session is None:
            raise Exception("DB not initialized properly, check: SQLALCHEMY_URL")

        # create local session (optional step)
        s = self._session()

        try:
            yield s
            s.commit()
        except Exception as e:
            s.rollback()
            raise (e)
        finally:
            s.close()


class MultilineMessagesFormatter(Formatter):
    converter = time.gmtime

    def format(self, record):
        """
        This is mostly the same as logging.Formatter.format except for adding spaces in front
        of the multiline messages.
        """
        s = Formatter.format(self, record)

        if "\n" in s:
            return "\n     ".join(s.split("\n"))
        else:
            return s

    def formatTime(self, record, datefmt=None):
        """logging uses time.strftime which doesn't understand
        how to add microsecs. datetime understands that. so we
        have to work around the old time.strftime here."""
        if datefmt:
            datefmt = datefmt.replace("%f", "%03d" % record.msecs)
            return Formatter.formatTime(self, record, datefmt)
        else:
            return Formatter.formatTime(self, record, datefmt)  # default ISO8601


class JsonFormatter(jsonlogger.JsonFormatter, object):
    converter = time.gmtime
    #: Loglevel -> Color mapping.
    COLORS = colored().names
    colors = {
        "DEBUG": COLORS["blue"],
        "WARNING": COLORS["yellow"],
        "ERROR": COLORS["red"],
        "CRITICAL": COLORS["magenta"],
    }

    def __init__(
        self,
        fmt="%(asctime) %(name) %(processName) %(filename)  %(funcName) %(levelname) %(lineno) %(module) "
        "%(threadName) %(message)",
        datefmt=TIMESTAMP_FMT,
        use_color=False,
        extra={},
        *args,
        **kwargs
    ):
        self._extra = extra
        self.use_color = use_color
        jsonlogger.JsonFormatter.__init__(self, fmt=fmt, datefmt=datefmt, *args, **kwargs)

    def process_log_record(self, log_record):
        # Enforce the presence of a timestamp
        if "asctime" in log_record:
            log_record["timestamp"] = log_record["asctime"]
        else:
            log_record["timestamp"] = datetime.utcnow().strftime(TIMESTAMP_FMT)
            log_record["asctime"] = log_record["timestamp"]

        if self._extra is not None:
            for key, value in list(self._extra.items()):
                log_record[key] = value
        return super(JsonFormatter, self).process_log_record(log_record)

    def formatException(self, ei):
        if ei and not isinstance(ei, tuple):
            ei = sys.exc_info()
        r = jsonlogger.JsonFormatter.formatException(self, ei)
        return r

    def formatTime(self, record, datefmt=None):
        """logging uses time.strftime which doesn't understand
        how to add microsecs. datetime understands that. so we
        have to work around the old time.strftime here."""
        if datefmt:
            datefmt = datefmt.replace("%f", "%03d" % record.msecs)
            return Formatter.formatTime(self, record, datefmt)
        else:
            return Formatter.formatTime(self, record, datefmt)  # default ISO8601

    def format(self, record):
        msg = jsonlogger.JsonFormatter.format(self, record)
        color = self.colors.get(record.levelname)

        # reset exception info later for other handlers...
        einfo = sys.exc_info() if record.exc_info == 1 else record.exc_info

        if color and self.use_color:
            try:
                # safe_str will repr the color object
                # and color will break on non-string objects
                # so need to reorder calls based on type.
                # Issue #427
                try:
                    if isinstance(msg, str):
                        return str(color(safe_str(msg)))
                    return safe_str(color(msg))
                except UnicodeDecodeError:  # pragma: no cover
                    return safe_str(msg)  # skip colors
            except Exception as exc:  # pylint: disable=broad-except
                prev_msg, record.exc_info, record.msg = (
                    record.msg,
                    1,
                    "<Unrepresentable {0!r}: {1!r}>".format(type(msg), exc),
                )
                try:
                    return logging.Formatter.format(self, record)
                finally:
                    record.msg, record.exc_info = prev_msg, einfo
        else:
            return safe_str(msg)


def get_json_formatter(
    use_color=False,
    logfmt="%(asctime) %(name) %(processName) %(filename)  %(funcName) %(levelname) %(lineno) %(module) "
    "%(threadName) %(message)",
    datefmt=TIMESTAMP_FMT,
):
    return JsonFormatter(
        logfmt, datefmt, extra={"hostname": socket.gethostname()}, use_color=use_color
    )


def u2asc(input):
    """
    Converts/transliterates unicode characters to ASCII, using the unidecode package.
    Functionality is similar to the legacy code in adspy.Unicode, but may treat some characters differently
    (e.g. umlauts). Standard unidecode package only handles Latin-based characters.

    :param input: string to be transliterated. Can be either unicode or encoded in utf-8
    :return output: transliterated string, in either unicode or encoded (to match input)
    """

    # TODO If used on anything but author names, add special handling for math symbols and other special chars
    test_type = str
    if not isinstance(input, test_type):
        try:
            input = input.decode("utf-8")
        except UnicodeDecodeError:
            raise UnicodeHandlerError("Input must be either unicode or encoded in utf8.")

    try:
        output = unidecode.unidecode(input)
    except UnicodeDecodeError:
        raise UnicodeHandlerError("Transliteration failed, check input.")

    if not isinstance(input, test_type):
        output = output.encode("utf-8")

    return output


class UTCDateTime(types.TypeDecorator):
    """Value type for SQLAlachemy to be used for UTC datetime
    example usage (in your models.py)

    from sqlalchemy.ext.declarative import declarative_base
    from adsmutils import get_date, UTCDateTime
    Base = declarative_base()

    class Foo(Base):
        __tablename__ = 'foo'
        id = Column(Integer, primary_key=True)
        created = Column(UTCDateTime, default=get_date)
        updated = Column(UTCDateTime)

    """

    impl = TIMESTAMP(timezone=True)

    def process_bind_param(self, value, engine):
        if isinstance(value, basestring):
            return get_date(value).astimezone(utc_zone)
        elif value is not None:
            if value.tzname() is None:
                return value.replace(tzinfo=local_zone).astimezone(tz=utc_zone)
            return value.astimezone(tz=utc_zone)  # will raise Error if not datetime

    def process_result_value(self, value, engine):
        if value is not None:
            if value.tzname() is None:
                # sqlite seems to save strings and then loads them without local timezone
                if "sqlite" in engine.name:
                    return value.replace(tzinfo=utc_zone)
                return value.replace(tzinfo=local_zone).astimezone(tz=utc_zone)
            return value.astimezone(tz=utc_zone)


class ImmutableAttrDict(dict):
    """Once defined, these attributes cannot be changed. It is used
    for wrapping configuration data struct"""

    def __init__(self, mapping=None):
        super(ImmutableAttrDict, self).__init__()
        if mapping is not None:
            s = super(ImmutableAttrDict, self).__setitem__
            for key, value in list(mapping.items()):
                s(key, value)

    def __setitem__(self, key, value):
        raise RuntimeError("You cannot do that")

    def __getattr__(self, item):
        try:
            return self.__getitem__(item)
        except KeyError:
            raise AttributeError(item)

    __setattr__ = __setitem__
