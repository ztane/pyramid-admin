# -*- coding: utf-8 -*-
"""
    tet_admin.json
    ~~~~~~~~~~~~~~

    Based on flask.jsonimpl:

    Implementation helpers for the JSON support in Flask.
    :copyright: (c) 2015 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.

    Modified for use in Tet-Admin in 2015 by
    Antti Haapala.
"""
import io
import uuid
from datetime import date
from ._compat import text_type, PY2

from werkzeug.http import http_date
from jinja2 import Markup

import json as _json


__all__ = ['dump', 'dumps', 'load', 'loads', 'htmlsafe_dump',
           'htmlsafe_dumps', 'JSONDecoder', 'JSONEncoder',
           'jsonify']


def _wrap_reader_for_text(fp, encoding):
    if isinstance(fp.read(0), bytes):
        fp = io.TextIOWrapper(io.BufferedReader(fp), encoding)
    return fp


def _wrap_writer_for_text(fp, encoding):
    try:
        fp.write('')
    except TypeError:
        fp = io.TextIOWrapper(fp, encoding)
    return fp


class JSONEncoder(_json.JSONEncoder):
    """The default Flask JSON encoder.  This one extends the default simplejson
    encoder by also supporting ``datetime`` objects, ``UUID`` as well as
    ``Markup`` objects which are serialized as RFC 822 datetime strings (same
    as the HTTP date format).  In order to support more data types override the
    :meth:`default` method.
    """

    def default(self, o):
        """Implement this method in a subclass such that it returns a
        serializable object for ``o``, or calls the base implementation (to
        raise a :exc:`TypeError`).
        For example, to support arbitrary iterators, you could implement
        default like this::
            def default(self, o):
                try:
                    iterable = iter(o)
                except TypeError:
                    pass
                else:
                    return list(iterable)
                return JSONEncoder.default(self, o)
        """
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, uuid.UUID):
            return str(o)
        if hasattr(o, '__html__'):
            return text_type(o.__html__())
        return _json.JSONEncoder.default(self, o)


class JSONDecoder(_json.JSONDecoder):
    """The default JSON decoder.  This one does not change the behavior from
    the default simplejson decoder.  Consult the :mod:`json` documentation
    for more information.  This decoder is not only used for the load
    functions of this module but also :attr:`~flask.Request`.
    """


def _dump_arg_defaults(kwargs):
    """Inject default arguments for dump functions."""
    kwargs.setdefault('sort_keys', True)
    kwargs.setdefault('cls', JSONEncoder)


def _load_arg_defaults(kwargs):
    """Inject default arguments for load functions."""
    kwargs.setdefault('cls', JSONDecoder)


def dumps(obj, **kwargs):
    """Serialize ``obj`` to a JSON formatted ``str``.

    This function can return ``unicode`` strings or ascii-only bytestrings by
    default which coerce into unicode strings automatically.
    """
    _dump_arg_defaults(kwargs)
    encoding = kwargs.pop('encoding', None)
    rv = _json.dumps(obj, **kwargs)
    if encoding is not None and isinstance(rv, text_type):
        rv = rv.encode(encoding)
    return rv


def dump(obj, fp, **kwargs):
    """Like :func:`dumps` but writes into a file object."""
    _dump_arg_defaults(kwargs)
    encoding = kwargs.pop('encoding', None)
    if encoding is not None:
        fp = _wrap_writer_for_text(fp, encoding)
    _json.dump(obj, fp, **kwargs)


def loads(s, **kwargs):
    """Unserialize a JSON object from a string ``s`` by using the application's
    configured decoder (:attr:`~flask.Flask.json_decoder`) if there is an
    application on the stack.
    """
    _load_arg_defaults(kwargs)
    if isinstance(s, bytes):
        s = s.decode(kwargs.pop('encoding', None) or 'utf-8')
    return _json.loads(s, **kwargs)


def load(fp, **kwargs):
    """Like :func:`loads` but reads from a file object.
    """
    _load_arg_defaults(kwargs)
    if not PY2:
        fp = _wrap_reader_for_text(fp, kwargs.pop('encoding', None) or 'utf-8')
    return _json.load(fp, **kwargs)


_translation_table = {
    ord(u'<'): u'\\u003c',
    ord(u'>'): u'\\u003e',
    ord(u'&'): u'\\u0026',
    ord(u"'"): u'\\u0027',
#    ord(u'"'): u'\\u0022',
    ord(u'\u2028'): u'\\u2028',
    ord(u'\u2029'): u'\\u2029',
}

def htmlsafe_dumps(obj, **kwargs):
    """Works exactly like :func:`dumps` but is safe for use in ``<script>``
    tags.  It accepts the same arguments and returns a JSON string.  Note that
    this is available in templates through the ``|tojson`` filter which will
    also mark the result as safe.  Due to how this function escapes certain
    characters this is safe even if used outside of ``<script>`` tags.
    The following characters are escaped in strings:
    -   ``<``
    -   ``>``
    -   ``&``
    -   ``'``
    This makes it safe to embed such strings in any place in HTML with the
    notable exception of double quoted attributes.  In that case single
    quote your attributes or HTML escape it in addition.
    .. versionchanged:: 0.10
       This function's return value is now always safe for HTML usage, even
       if outside of script tags or if used in XHTML.  This rule does not
       hold true when using this function in HTML attributes that are double
       quoted.  Always single quote attributes if you use the ``|tojson``
       filter.  Alternatively use ``|tojson|forceescape``.
    """
    rv = dumps(obj, **kwargs) \
        .translate(_translation_table)

    return rv


def htmlsafe_dump(obj, fp, **kwargs):
    """Like :func:`htmlsafe_dumps` but writes into a file object."""
    fp.write(text_type(htmlsafe_dumps(obj, **kwargs)))


def tojson_filter(obj, **kwargs):
    return Markup(htmlsafe_dumps(obj, **kwargs))
