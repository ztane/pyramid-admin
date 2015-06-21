def setup():
    import warnings
    warnings.warn('Flask-Admin peewee integration module was renamed as pyramid_admin.contrib.peewee, please use it instead.')

    from pyramid_admin._backwards import import_redirect
    import_redirect(__name__, 'pyramid_admin.contrib.peewee')

setup()
del setup

from ..peewee.view import ModelView
