"""Terminals and colors.

From: https://github.com/celery/celery/blob/master/celery/utils/term.py
"""
from __future__ import annotations

import base64
import codecs
import os
import platform
import sys
import traceback
from functools import reduce

__all__ = ('colored',)

BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)
OP_SEQ = '\033[%dm'
RESET_SEQ = '\033[0m'
COLOR_SEQ = '\033[1;%dm'

IS_WINDOWS = platform.system() == 'Windows'

ITERM_PROFILE = os.environ.get('ITERM_PROFILE')
TERM = os.environ.get('TERM')
TERM_IS_SCREEN = TERM and TERM.startswith('screen')

# tmux requires unrecognized OSC sequences to be wrapped with DCS tmux;
# <sequence> ST, and for all ESCs in <sequence> to be replaced with ESC ESC.
# It only accepts ESC backslash for ST.
_IMG_PRE = '\033Ptmux;\033\033]' if TERM_IS_SCREEN else '\033]'
_IMG_POST = '\a\033\\' if TERM_IS_SCREEN else '\a'


def fg(s):
    return COLOR_SEQ % s


class colored:
    """Terminal colored text.
    Example:
        >>> c = colored(enabled=True)
        >>> print(str(c.red('the quick '), c.blue('brown ', c.bold('fox ')),
        ...       c.magenta(c.underline('jumps over')),
        ...       c.yellow(' the lazy '),
        ...       c.green('dog ')))
    """

    def __init__(self, *s, **kwargs):
        self.s = s
        self.enabled = not IS_WINDOWS and kwargs.get('enabled', True)
        self.op = kwargs.get('op', '')
        self.names = {
            'black': self.black,
            'red': self.red,
            'green': self.green,
            'yellow': self.yellow,
            'blue': self.blue,
            'magenta': self.magenta,
            'cyan': self.cyan,
            'white': self.white,
        }

    def _add(self, a, b):
        return str(a) + str(b)

    def _fold_no_color(self, a, b):
        try:
            A = a.no_color()
        except AttributeError:
            A = str(a)
        try:
            B = b.no_color()
        except AttributeError:
            B = str(b)

        return ''.join((str(A), str(B)))

    def no_color(self):
        if self.s:
            return str(reduce(self._fold_no_color, self.s))
        return ''

    def embed(self):
        prefix = ''
        if self.enabled:
            prefix = self.op
        return ''.join((str(prefix), str(reduce(self._add, self.s))))

    def __str__(self):
        suffix = ''
        if self.enabled:
            suffix = RESET_SEQ
        return str(''.join((self.embed(), str(suffix))))

    def node(self, s, op):
        return self.__class__(enabled=self.enabled, op=op, *s)

    def black(self, *s):
        return self.node(s, fg(30 + BLACK))

    def red(self, *s):
        return self.node(s, fg(30 + RED))

    def green(self, *s):
        return self.node(s, fg(30 + GREEN))

    def yellow(self, *s):
        return self.node(s, fg(30 + YELLOW))

    def blue(self, *s):
        return self.node(s, fg(30 + BLUE))

    def magenta(self, *s):
        return self.node(s, fg(30 + MAGENTA))

    def cyan(self, *s):
        return self.node(s, fg(30 + CYAN))

    def white(self, *s):
        return self.node(s, fg(30 + WHITE))

    def __repr__(self):
        return repr(self.no_color())

    def bold(self, *s):
        return self.node(s, OP_SEQ % 1)

    def underline(self, *s):
        return self.node(s, OP_SEQ % 4)

    def blink(self, *s):
        return self.node(s, OP_SEQ % 5)

    def reverse(self, *s):
        return self.node(s, OP_SEQ % 7)

    def bright(self, *s):
        return self.node(s, OP_SEQ % 8)

    def ired(self, *s):
        return self.node(s, fg(40 + RED))

    def igreen(self, *s):
        return self.node(s, fg(40 + GREEN))

    def iyellow(self, *s):
        return self.node(s, fg(40 + YELLOW))

    def iblue(self, *s):
        return self.node(s, fg(40 + BLUE))

    def imagenta(self, *s):
        return self.node(s, fg(40 + MAGENTA))

    def icyan(self, *s):
        return self.node(s, fg(40 + CYAN))

    def iwhite(self, *s):
        return self.node(s, fg(40 + WHITE))

    def reset(self, *s):
        return self.node(s or [''], RESET_SEQ)

    def __add__(self, other):
        return str(self) + str(other)


def isatty(fh):
    """Return true if the process has a controlling terminal. 
    From: https://github.com/celery/celery/blob/8570b1658a1842c3e3534b93a5ad167ca3ec6673/celery/platforms.py#L101"""
    try:
        return fh.isatty()
    except AttributeError:
        pass


def supports_images():
    return isatty(sys.stdin) and ITERM_PROFILE


def _read_as_base64(path):
    with codecs.open(path, mode='rb') as fh:
        encoded = base64.b64encode(fh.read())
        return encoded if type(encoded) == 'str' else encoded.decode('ascii')


def imgcat(path, inline=1, preserve_aspect_ratio=0, **kwargs):
    return '\n%s1337;File=inline=%d;preserveAspectRatio=%d:%s%s' % (
        _IMG_PRE, inline, preserve_aspect_ratio,
        _read_as_base64(path), _IMG_POST)


# from https://github.com/celery/kombu/blob/master/kombu/utils/encoding.py
#: safe_str takes encoding from this file by default.
#: :func:`set_default_encoding_file` can used to set the
#: default output file.
default_encoding_file = None


def set_default_encoding_file(file):
    """Set file used to get codec information."""
    global default_encoding_file
    default_encoding_file = file


def get_default_encoding_file():
    """Get file used to get codec information."""
    return default_encoding_file


if sys.platform.startswith('java'):  # pragma: no cover

    def default_encoding(file=None):
        """Get default encoding."""
        return 'utf-8'
else:

    def default_encoding(file=None):
        """Get default encoding."""
        file = file or get_default_encoding_file()
        return getattr(file, 'encoding', None) or sys.getfilesystemencoding()


def str_to_bytes(s):
    """Convert str to bytes."""
    if isinstance(s, str):
        return s.encode()
    return s


def bytes_to_str(s):
    """Convert bytes to str."""
    if isinstance(s, bytes):
        return s.decode(errors='replace')
    return s


def from_utf8(s, *args, **kwargs):
    """Get str from utf-8 encoding."""
    return s


def ensure_bytes(s):
    """Ensure s is bytes, not str."""
    if not isinstance(s, bytes):
        return str_to_bytes(s)
    return s


def default_encode(obj):
    """Encode using default encoding."""
    return obj


def safe_str(s, errors='replace'):
    """Safe form of str(), void of unicode errors."""
    s = bytes_to_str(s)
    if not isinstance(s, (str, bytes)):
        return safe_repr(s, errors)
    return _safe_str(s, errors)


def _safe_str(s, errors='replace', file=None):
    if isinstance(s, str):
        return s
    try:
        return str(s)
    except Exception as exc:
        return '<Unrepresentable {!r}: {!r} {!r}>'.format(
            type(s), exc, '\n'.join(traceback.format_stack()))


def safe_repr(o, errors='replace'):
    """Safe form of repr, void of Unicode errors."""
    try:
        return repr(o)
    except Exception:
        return _safe_str(o, errors)
