# -*- coding: utf-8 -*-
"""
    pyramid_admin._compat
    ~~~~~~~~~~~~~~~~~~~~~~~

    Some py2/py3 compatibility support based on a stripped down
    version of six so we don't have to depend on a specific version
    of it.

    :copyright: (c) 2013 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""
from itertools import count
import os
import sys
from pyramid.httpexceptions import HTTPFound
import re
from types import SimpleNamespace
from pyramid.interfaces import IRoutesMapper
from pyramid.threadlocal import get_current_registry, get_current_request

PY2 = sys.version_info[0] == 2
VER = sys.version_info

if not PY2:
    text_type = str
    string_types = (str,)
    integer_types = (int, )

    iterkeys = lambda d: iter(d.keys())
    itervalues = lambda d: iter(d.values())
    iteritems = lambda d: iter(d.items())
    filter_list = lambda f, l: list(filter(f, l))

    def as_unicode(s):
        if isinstance(s, bytes):
            return s.decode('utf-8')

        return str(s)

    # Various tools
    from functools import reduce
    from urllib.parse import urljoin, urlparse
else:
    text_type = unicode
    string_types = (str, unicode)
    integer_types = (int, long)

    iterkeys = lambda d: d.iterkeys()
    itervalues = lambda d: d.itervalues()
    iteritems = lambda d: d.iteritems()
    filter_list = filter

    def as_unicode(s):
        if isinstance(s, str):
            return s.decode('utf-8')

        return unicode(s)

    # Helpers
    reduce = __builtins__['reduce'] if isinstance(__builtins__, dict) else __builtins__.reduce
    from urlparse import urljoin, urlparse


def with_metaclass(meta, *bases):
    # This requires a bit of explanation: the basic idea is to make a
    # dummy metaclass for one level of class instantiation that replaces
    # itself with the actual metaclass.  Because of internal type checks
    # we also need to make sure that we downgrade the custom metaclass
    # for one level to something closer to type (that's why __call__ and
    # __init__ comes back from type etc.).
    #
    # This has the advantage over six.with_metaclass in that it does not
    # introduce dummy classes into the final MRO.
    class MetaClass(meta):
        __call__ = type.__call__
        __init__ = type.__init__

        def __new__(cls, name, this_bases, d):
            if this_bases is None:
                return type.__new__(cls, name, (), d)
            return meta(name, bases, d)

    return MetaClass('temporary_class', None, {})


try:
    from collections import OrderedDict

except ImportError:
    # Bare-bones OrderedDict implementation for Python2.6 compatibility
    class OrderedDict(dict):
        def __init__(self, *args, **kwargs):
            dict.__init__(self, *args, **kwargs)
            self.ordered_keys = []

        def __setitem__(self, key, value):
            self.ordered_keys.append(key)
            dict.__setitem__(self, key, value)

        def __iter__(self):
            return (k for k in self.ordered_keys)

        def iteritems(self):
            return ((k, self[k]) for k in self.ordered_keys)

        def items(self):
            return list(self.iteritems())

class Globals(object):
    def __getitem__(self, name):
        objects = [get_current_request(), get_current_registry()]
        for i in objects:
            if i:
                if not hasattr(i, 'globals'):
                    i.globals = SimpleNamespace()

                if hasattr(i.globals, name):
                    return getattr(i.globals, name)

        raise AttributeError

    def __setitem__(self, name, value):
        objects = [get_current_request(), get_current_registry()]
        for i in objects:
            if i:
                if not hasattr(i, 'globals'):
                    i.globals = SimpleNamespace()

                setattr(i.globals, name, value)

    def __delitem__(self, name):
        objects = [get_current_request(), get_current_registry()]
        for i in objects:
            if i:
                if not hasattr(i, 'globals'):
                    i.globals = SimpleNamespace()

                if hasattr(i.globals, name):
                    delattr(i.globals, name)
                    return

        raise AttributeError

def url_for(route_name, **kw):
    request = get_current_request()
    mapper = request.registry.getUtility(IRoutesMapper)
    if route_name == 'admin.static':
        return request.static_url('pyramid_admin:static/' + kw['filename'])

    if route_name.startswith('.'):
        route_name = get_current_view().endpoint + route_name

    for i in count(1):
        rname = '%s--%d' % (route_name, i)
        route = mapper.get_route(rname)

        if route is None:
            print("Failed to look up", rname)
            return '/42'
            raise KeyError("No such route: %s" % route_name)

        return request.route_url(rname, _query=kw)


def flash(message, *a, **kw):
    get_current_request().session.flash(message)


def redirect(to):
    return HTTPFound(location=to)


def get_flashed_messages(with_categories=False):
    if with_categories:
        return [(None, message) for message in get_current_request().session.pop_flash()]

    return get_current_request().session.pop_flash()


_filename_ascii_strip_re = re.compile(r'[^A-Za-z0-9_.-]')
_windows_device_files = ('CON', 'AUX', 'COM1', 'COM2', 'COM3', 'COM4', 'LPT1',
                         'LPT2', 'LPT3', 'PRN', 'NUL')


def secure_filename(filename):
    r"""Pass it a filename and it will return a secure version of it.  This
    filename can then safely be stored on a regular file system and passed
    to :func:`os.path.join`.  The filename returned is an ASCII only string
    for maximum portability.

    On windows systems the function also makes sure that the file is not
    named after one of the special device files.

    >>> secure_filename("My cool movie.mov")
    'My_cool_movie.mov'
    >>> secure_filename("../../../etc/passwd")
    'etc_passwd'
    >>> secure_filename(u'i contain cool \xfcml\xe4uts.txt')
    'i_contain_cool_umlauts.txt'

    The function might return an empty filename.  It's your responsibility
    to ensure that the filename is unique and that you generate random
    filename if the function returned an empty one.

    .. versionadded:: 0.5

    :param filename: the filename to secure
    """
    if isinstance(filename, text_type):
        from unicodedata import normalize
        filename = normalize('NFKD', filename).encode('ascii', 'ignore')
        if not PY2:
            filename = filename.decode('ascii')
    for sep in os.path.sep, os.path.altsep:
        if sep:
            filename = filename.replace(sep, ' ')
    filename = str(_filename_ascii_strip_re.sub('', '_'.join(
                   filename.split()))).strip('._')

    # on nt a couple of special files are present in each folder.  We
    # have to ensure that the target file is not such a filename.  In
    # this case we prepend an underline
    if os.name == 'nt' and filename and \
       filename.split('.')[0].upper() in _windows_device_files:
        filename = '_' + filename

    return filename


g = Globals()

from .helpers import get_current_view
from . import json
