import logging
import transaction
import warnings
import inspect

from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.orm import joinedload, aliased
from sqlalchemy.sql.expression import desc
from sqlalchemy import Boolean, Table, func, or_
from sqlalchemy.exc import IntegrityError

from ..._compat import flash

from pyramid_admin._compat import string_types, text_type
from pyramid_admin.babel import gettext, ngettext, lazy_gettext
from pyramid_admin.model import BaseModelView
from pyramid_admin.model.form import wrap_fields_in_fieldlist
from pyramid_admin.model.fields import ListEditableFieldList

from pyramid_admin.actions import action
from pyramid_admin._backwards import ObsoleteAttr

from pyramid_admin.contrib.sqla import form, filters as sqla_filters, tools
from .typefmt import DEFAULT_FORMATTERS
from .tools import get_query_for_ids
from .ajax import create_ajax_loader

# Set up logger
log = logging.getLogger("pyramid-admin.sqla")


class ModelView(BaseModelView):
    """
        SQLAlchemy model view

        Usage sample::

            admin = Admin()
            admin.add_view(ModelView(User, db.session))
    """

    column_auto_select_related = ObsoleteAttr('column_auto_select_related',
                                              'auto_select_related',
                                              True)
    """
        Enable automatic detection of displayed foreign keys in this view
        and perform automatic joined loading for related models to improve
        query performance.

        Please note that detection is not recursive: if `__unicode__` method
        of related model uses another model to generate string representation, it
        will still make separate database call.
    """

    column_select_related_list = ObsoleteAttr('column_select_related',
                                             'list_select_related',
                                              None)
    """
        List of parameters for SQLAlchemy `subqueryload`. Overrides `column_auto_select_related`
        property.

        For example::

            class PostAdmin(ModelView):
                column_select_related_list = ('user', 'city')

        You can also use properties::

            class PostAdmin(ModelView):
                column_select_related_list = (Post.user, Post.city)

        Please refer to the `subqueryload` on list of possible values.
    """

    column_display_all_relations = ObsoleteAttr('column_display_all_relations',
                                                'list_display_all_relations',
                                                False)
    """
        Controls if list view should display all relations, not only many-to-one.
    """

    column_searchable_list = ObsoleteAttr('column_searchable_list',
                                          'searchable_columns',
                                          None)
    """
        Collection of the searchable columns.

        Example::

            class MyModelView(ModelView):
                column_searchable_list = ('name', 'email')

        You can also pass columns::

            class MyModelView(ModelView):
                column_searchable_list = (User.name, User.email)

        The following search rules apply:

        - If you enter *ZZZ* in the UI search field, it will generate *ILIKE '%ZZZ%'*
          statement against searchable columns.

        - If you enter multiple words, each word will be searched separately, but
          only rows that contain all words will be displayed. For example, searching
          for 'abc def' will find all rows that contain 'abc' and 'def' in one or
          more columns.

        - If you prefix your search term with ^, it will find all rows
          that start with ^. So, if you entered *^ZZZ*, *ILIKE 'ZZZ%'* will be used.

        - If you prefix your search term with =, it will perform an exact match.
          For example, if you entered *=ZZZ*, the statement *ILIKE 'ZZZ'* will be used.
    """

    column_filters = None
    """
        Collection of the column filters.

        Can contain either field names or instances of :class:`pyramid_admin.contrib.sqla.filters.BaseFilter` classes.

        For example::

            class MyModelView(BaseModelView):
                column_filters = ('user', 'email')

        or::

            class MyModelView(BaseModelView):
                column_filters = (BooleanEqualFilter(User.name, 'Name'))
    """

    model_form_converter = form.AdminModelConverter
    """
        Model form conversion class. Use this to implement custom field conversion logic.

        For example::

            class MyModelConverter(AdminModelConverter):
                pass


            class MyAdminView(ModelView):
                model_form_converter = MyModelConverter
    """

    inline_model_form_converter = form.InlineModelConverter
    """
        Inline model conversion class. If you need some kind of post-processing for inline
        forms, you can customize behavior by doing something like this::

            class MyInlineModelConverter(AdminModelConverter):
                def post_process(self, form_class, info):
                    form_class.value = wtf.StringField('value')
                    return form_class

            class MyAdminView(ModelView):
                inline_model_form_converter = MyInlineModelConverter
    """

    filter_converter = sqla_filters.FilterConverter()
    """
        Field to filter converter.

        Override this attribute to use non-default converter.
    """

    fast_mass_delete = False
    """
        If set to `False` and user deletes more than one model using built in action,
        all models will be read from the database and then deleted one by one
        giving SQLAlchemy a chance to manually cleanup any dependencies (many-to-many
        relationships, etc).

        If set to `True`, will run a `DELETE` statement which is somewhat faster,
        but may leave corrupted data if you forget to configure `DELETE
        CASCADE` for your model.
    """

    inline_models = None
    """
        Inline related-model editing for models with parent-child relations.

        Accepts enumerable with one of the following possible values:

        1. Child model class::

            class MyModelView(ModelView):
                inline_models = (Post,)

        2. Child model class and additional options::

            class MyModelView(ModelView):
                inline_models = [(Post, dict(form_columns=['title']))]

        3. Django-like ``InlineFormAdmin`` class instance::

            class MyInlineModelForm(InlineFormAdmin):
                form_columns = ('title', 'date')

            class MyModelView(ModelView):
                inline_models = (MyInlineModelForm(MyInlineModel),)

        You can customize the generated field name by:

        1. Using the `form_name` property as a key to the options dictionary:

            class MyModelView(ModelView):
                inline_models = ((Post, dict(form_label='Hello')))

        2. Using forward relation name and `column_labels` property:

            class Model1(Base):
                pass

            class Model2(Base):
                # ...
                model1 = relation(Model1, backref='models')

            class MyModel1View(Base):
                inline_models = (Model2,)
                column_labels = {'models': 'Hello'}
    """

    column_type_formatters = DEFAULT_FORMATTERS

    form_choices = None
    """
        Map choices to form fields

        Example::

            class MyModelView(BaseModelView):
                form_choices = {'my_form_field': [
                    ('db_value', 'display_value'),
                ]
    """

    form_optional_types = (Boolean,)
    """
        List of field types that should be optional if column is not nullable.

        Example::

            class MyModelView(BaseModelView):
                form_optional_types = (Boolean, Unicode)
    """

    def __init__(self, model, session,
                 name=None, category=None, endpoint=None, url=None, static_folder=None,
                 menu_class_name=None, menu_icon_type=None, menu_icon_value=None):
        """
            Constructor.

            :param model:
                Model class
            :param session:
                SQLAlchemy session
            :param name:
                View name. If not set, defaults to the model name
            :param category:
                Category name
            :param endpoint:
                Endpoint name. If not set, defaults to the model name
            :param url:
                Base URL. If not set, defaults to '/admin/' + endpoint
            :param menu_class_name:
                Optional class name for the menu item.
            :param menu_icon_type:
                Optional icon. Possible icon types:

                 - `pyramid_admin.consts.ICON_TYPE_GLYPH` - Bootstrap glyph icon
                 - `pyramid_admin.consts.ICON_TYPE_FONT_AWESOME` - Font Awesome icon
                 - `pyramid_admin.consts.ICON_TYPE_IMAGE` - Image relative to Flask static directory
                 - `pyramid_admin.consts.ICON_TYPE_IMAGE_URL` - Image with full URL
            :param menu_icon_value:
                Icon glyph name or URL, depending on `menu_icon_type` setting
        """
        self.session = session

        self._search_fields = None

        self._filter_joins = dict()

        self._sortable_joins = dict()

        if self.form_choices is None:
            self.form_choices = {}

        super(ModelView, self).__init__(model, name, category, endpoint, url, static_folder,
                                        menu_class_name=menu_class_name,
                                        menu_icon_type=menu_icon_type,
                                        menu_icon_value=menu_icon_value)

        # Primary key
        self._primary_key = self.scaffold_pk()

        if self._primary_key is None:
            raise Exception('Model %s does not have primary key.' % self.model.__name__)

        # Configuration
        if not self.column_select_related_list:
            self._auto_joins = self.scaffold_auto_joins()
        else:
            self._auto_joins = self.column_select_related_list

    # Internal API
    def _get_model_iterator(self, model=None):
        """
            Return property iterator for the model
        """
        if model is None:
            model = self.model

        return model._sa_class_manager.mapper.iterate_properties

    def _get_columns_for_field(self, field):
        if (not field or
            not hasattr(field, 'property') or
            not hasattr(field.property, 'columns') or
            not field.property.columns):
                raise Exception('Invalid field %s: does not contains any columns.' % field)

        return field.property.columns

    def _get_field_with_path(self, name):
        """
            Resolve property by name and figure out its join path.

            Join path might contain both properties and tables.
        """
        path = []

        model = self.model

        # For strings, resolve path
        if isinstance(name, string_types):
            for attribute in name.split('.'):
                value = getattr(model, attribute)

                if (hasattr(value, 'property') and
                        hasattr(value.property, 'direction')):
                    model = value.property.mapper.class_

                    table = model.__table__

                    if self._need_join(table):
                        path.append(value)

                attr = value
        else:
            attr = name

            # Determine joins if table.column (relation object) is provided
            if isinstance(attr, InstrumentedAttribute):
                columns = self._get_columns_for_field(attr)

                if len(columns) > 1:
                    raise Exception('Can only handle one column for %s' % name)

                column = columns[0]

                # TODO: Use SQLAlchemy "path-finder" to find exact join path to the target property
                if self._need_join(column.table):
                    path.append(column.table)

        return attr, path

    def _need_join(self, table):
        """
            Check if join to a table is necessary.
        """
        return table not in self.model._sa_class_manager.mapper.tables

    def _apply_path_joins(self, query, joins, path, inner_join=True):
        """
            Apply join path to the query.

            :param query:
                Query to add joins to
            :param joins:
                List of current joins. Used to avoid joining on same relationship more than once
            :param path:
                Path to be joined
            :param fn:
                Join function
        """
        last = None

        if path:
            for item in path:
                key = (inner_join, item)
                alias = joins.get(key)

                if key not in joins:
                    if not isinstance(item, Table):
                        alias = aliased(item.property.mapper.class_)

                    fn = query.join if inner_join else query.outerjoin

                    if last is None:
                        query = fn(item) if alias is None else fn(alias, item)
                    else:
                        prop = getattr(last, item.key)
                        query = fn(prop) if alias is None else fn(alias, prop)

                    joins[key] = alias

                last = alias

        return query, joins, last

    # Scaffolding
    def scaffold_pk(self):
        """
            Return the primary key name(s) from a model
            If model has single primary key, will return a string and tuple otherwise
        """
        return tools.get_primary_key(self.model)

    def get_pk_value(self, model):
        """
            Return the primary key value from a model object.
            If there are multiple primary keys, they're encoded into string representation.
        """
        if isinstance(self._primary_key, tuple):
            return tools.iterencode(getattr(model, attr) for attr in self._primary_key)
        else:
            return tools.escape(getattr(model, self._primary_key))

    def scaffold_list_columns(self):
        """
            Return a list of columns from the model.
        """
        columns = []

        for p in self._get_model_iterator():
            if hasattr(p, 'direction'):
                if self.column_display_all_relations or p.direction.name == 'MANYTOONE':
                    columns.append(p.key)
            elif hasattr(p, 'columns'):
                if len(p.columns) > 1:
                    filtered = tools.filter_foreign_columns(self.model.__table__, p.columns)

                    if len(filtered) > 1:
                        warnings.warn('Can not convert multiple-column properties (%s.%s)' % (self.model, p.key))
                        continue

                    column = filtered[0]
                else:
                    column = p.columns[0]

                if column.foreign_keys:
                    continue

                if not self.column_display_pk and column.primary_key:
                    continue

                columns.append(p.key)

        return columns

    def scaffold_sortable_columns(self):
        """
            Return a dictionary of sortable columns.
            Key is column name, value is sort column/field.
        """
        columns = dict()

        for p in self._get_model_iterator():
            if hasattr(p, 'columns'):
                # Sanity check
                if len(p.columns) > 1:
                    # Multi-column properties are not supported
                    continue

                column = p.columns[0]

                # Can't sort on primary or foreign keys by default
                if column.foreign_keys:
                    continue

                if not self.column_display_pk and column.primary_key:
                    continue

                columns[p.key] = column

        return columns

    def get_sortable_columns(self):
        """
            Returns a dictionary of the sortable columns. Key is a model
            field name and value is sort column (for example - attribute).

            If `column_sortable_list` is set, will use it. Otherwise, will call
            `scaffold_sortable_columns` to get them from the model.
        """
        self._sortable_joins = dict()

        if self.column_sortable_list is None:
            return self.scaffold_sortable_columns()
        else:
            result = dict()

            for c in self.column_sortable_list:
                if isinstance(c, tuple):
                    column, path = self._get_field_with_path(c[1])
                    column_name = c[0]
                elif isinstance(c, InstrumentedAttribute):
                    column, path = self._get_field_with_path(c)
                    column_name = str(c)
                else:
                    column, path = self._get_field_with_path(c)
                    column_name = c

                result[column_name] = column

                if path:
                    self._sortable_joins[column_name] = path

            return result

    def init_search(self):
        """
            Initialize search. Returns `True` if search is supported for this
            view.

            For SQLAlchemy, this will initialize internal fields: list of
            column objects used for filtering, etc.
        """
        if self.column_searchable_list:
            self._search_fields = []

            for p in self.column_searchable_list:
                attr, joins = self._get_field_with_path(p)

                if not attr:
                    raise Exception('Failed to find field for search field: %s' % p)

                for column in self._get_columns_for_field(attr):
                    self._search_fields.append((column, joins))

        return bool(self.column_searchable_list)

    def scaffold_filters(self, name):
        """
            Return list of enabled filters
        """

        attr, joins = self._get_field_with_path(name)

        if attr is None:
            raise Exception('Failed to find field for filter: %s' % name)

        # Figure out filters for related column
        if hasattr(attr, 'property') and hasattr(attr.property, 'direction'):
            filters = []

            for p in self._get_model_iterator(attr.property.mapper.class_):
                if hasattr(p, 'columns'):
                    # TODO: Check for multiple columns
                    column = p.columns[0]

                    if column.foreign_keys or column.primary_key:
                        continue

                    visible_name = '%s / %s' % (self.get_column_name(attr.prop.table.name),
                                                self.get_column_name(p.key))

                    type_name = type(column.type).__name__
                    flt = self.filter_converter.convert(type_name,
                                                        column,
                                                        visible_name)

                    if flt:
                        table = column.table

                        if joins:
                            self._filter_joins[column] = joins
                        elif self._need_join(table):
                            self._filter_joins[column] = [table]

                        filters.extend(flt)

            return filters
        else:
            columns = self._get_columns_for_field(attr)

            if len(columns) > 1:
                raise Exception('Can not filter more than on one column for %s' % name)

            column = columns[0]

            if self._need_join(column.table) and name not in self.column_labels:
                visible_name = '%s / %s' % (
                    self.get_column_name(column.table.name),
                    self.get_column_name(column.name)
                )
            else:
                if not isinstance(name, string_types):
                    visible_name = self.get_column_name(name.property.key)
                else:
                    visible_name = self.get_column_name(name)

            type_name = type(column.type).__name__

            flt = self.filter_converter.convert(
                type_name,
                column,
                visible_name,
                options=self.column_choices.get(name),
            )

            if joins:
                self._filter_joins[column] = joins
            elif self._need_join(column.table):
                self._filter_joins[column] = [column.table]

            return flt

    def handle_filter(self, filter):
        if isinstance(filter, sqla_filters.BaseSQLAFilter):
            column = filter.column

            if self._need_join(column.table):
                self._filter_joins[column] = [column.table]

        return filter

    def scaffold_form(self):
        """
            Create form from the model.
        """
        converter = self.model_form_converter(self.session, self)
        form_class = form.get_form(self.model, converter,
                                   base_class=self.form_base_class,
                                   only=self.form_columns,
                                   exclude=self.form_excluded_columns,
                                   field_args=self.form_args,
                                   extra_fields=self.form_extra_fields)

        if self.inline_models:
            form_class = self.scaffold_inline_form_models(form_class)

        return form_class

    def scaffold_list_form(self, custom_fieldlist=ListEditableFieldList,
                           validators=None):
        """
            Create form for the `index_view` using only the columns from
            `self.column_editable_list`.

            :param validators:
                `form_args` dict with only validators
                {'name': {'validators': [required()]}}
            :param custom_fieldlist:
                A WTForm FieldList class. By default, `ListEditableFieldList`.
        """
        converter = self.model_form_converter(self.session, self)
        form_class = form.get_form(self.model, converter,
                                   base_class=self.form_base_class,
                                   only=self.column_editable_list,
                                   field_args=validators)

        return wrap_fields_in_fieldlist(self.form_base_class,
                                        form_class,
                                        custom_fieldlist)

    def scaffold_inline_form_models(self, form_class):
        """
            Contribute inline models to the form

            :param form_class:
                Form class
        """
        inline_converter = self.inline_model_form_converter(self.session,
                                                            self,
                                                            self.model_form_converter)

        for m in self.inline_models:
            form_class = inline_converter.contribute(self.model, form_class, m)

        return form_class

    def scaffold_auto_joins(self):
        """
            Return a list of joined tables by going through the
            displayed columns.
        """
        if not self.column_auto_select_related:
            return []

        relations = set()

        for p in self._get_model_iterator():
            if hasattr(p, 'direction'):
                # Check if it is pointing to same model
                if p.mapper.class_ == self.model:
                    continue

                if p.direction.name in ['MANYTOONE', 'MANYTOMANY']:
                    relations.add(p.key)

        joined = []

        for prop, name in self._list_columns:
            if prop in relations:
                joined.append(getattr(self.model, prop))

        return joined

    # AJAX foreignkey support
    def _create_ajax_loader(self, name, options):
        return create_ajax_loader(self.model, self.session, name, name, options)

    # Database-related API
    def get_query(self):
        """
            Return a query for the model type.

            If you override this method, don't forget to override `get_count_query` as well.

            This method can be used to set a "persistent filter" on an index_view.

            Example::

                class MyView(ModelView):
                    def get_query(self):
                        return super(MyView, self).get_query().filter(User.username == current_user.username)
        """
        return self.session.query(self.model)

    def get_count_query(self):
        """
            Return a the count query for the model type

            A query(self.model).count() approach produces an excessive
            subquery, so query(func.count('*')) should be used instead.

            See #45a2723 commit message for details.
        """
        return self.session.query(func.count('*')).select_from(self.model)

    def _order_by(self, query, joins, sort_joins, sort_field, sort_desc):
        """
            Apply order_by to the query

            :param query:
                Query
            :pram joins:
                Current joins
            :param sort_joins:
                Sort joins (properties or tables)
            :param sort_field:
                Sort field
            :param sort_desc:
                Ascending or descending
        """
        if sort_field is not None:
            # Handle joins
            query, joins, alias = self._apply_path_joins(query, joins, sort_joins, inner_join=False)

            column = sort_field if alias is None else getattr(alias, sort_field.key)

            if sort_desc:
                query = query.order_by(desc(column))
            else:
                query = query.order_by(column)

        return query, joins

    def _get_default_order(self):
        order = super(ModelView, self)._get_default_order()

        if order is not None:
            field, direction = order

            attr, joins = self._get_field_with_path(field)

            return attr, joins, direction

        return None

    def _apply_sorting(self, query, joins, sort_column, sort_desc):
        if sort_column is not None:
            if sort_column in self._sortable_columns:
                sort_field = self._sortable_columns[sort_column]
                sort_joins = self._sortable_joins.get(sort_column)

                query, joins = self._order_by(query, joins, sort_joins, sort_field, sort_desc)
        else:
            order = self._get_default_order()

            if order:
                sort_field, sort_joins, sort_desc = order

                query, joins = self._order_by(query, joins, sort_joins, sort_field, sort_desc)

        return query, joins

    def _apply_search(self, query, count_query, joins, count_joins, search):
        """
            Apply search to a query.
        """
        terms = search.split(' ')

        for term in terms:
            if not term:
                continue

            stmt = tools.parse_like_term(term)

            filter_stmt = []
            count_filter_stmt = []

            for field, path in self._search_fields:
                query, joins, alias = self._apply_path_joins(query, joins, path, inner_join=False)

                count_alias = None

                if count_query is not None:
                    count_query, count_joins, count_alias = self._apply_path_joins(count_query,
                                                                                   count_joins,
                                                                                   path,
                                                                                   inner_join=False)

                column = field if alias is None else getattr(alias, field.key)
                filter_stmt.append(column.ilike(stmt))

                if count_filter_stmt is not None:
                    column = field if count_alias is None else getattr(count_alias, field.key)
                    count_filter_stmt.append(column.ilike(stmt))

            query = query.filter(or_(*filter_stmt))

            if count_query is not None:
                count_query = count_query.filter(or_(*count_filter_stmt))

        return query, count_query, joins, count_joins

    def _apply_filters(self, query, count_query, joins, count_joins, filters):
        for idx, flt_name, value in filters:
            flt = self._filters[idx]

            alias = None
            count_alias = None

            # Figure out joins
            if isinstance(flt, sqla_filters.BaseSQLAFilter):
                path = self._filter_joins.get(flt.column, [])

                query, joins, alias = self._apply_path_joins(query, joins, path, inner_join=False)

                if count_query is not None:
                    count_query, count_joins, count_alias = self._apply_path_joins(
                        count_query,
                        count_joins,
                        path,
                        inner_join=False)

            # Clean value .clean() and apply the filter
            clean_value = flt.clean(value)

            try:
                query = flt.apply(query, clean_value, alias)
            except TypeError:
                spec = inspect.getargspec(flt.apply)

                if len(spec.args) == 2:
                    warnings.warn('Please update your custom filter %s to include additional `alias` parameter.' % repr(flt))
                else:
                    raise

                query = flt.apply(query, clean_value)

            if count_query is not None:
                try:
                    count_query = flt.apply(count_query, clean_value, count_alias)
                except TypeError:
                    count_query = flt.apply(count_query, clean_value)

        return query, count_query, joins, count_joins

    def get_list(self, page, sort_column, sort_desc, search, filters, execute=True):
        """
            Return models from the database.

            :param page:
                Page number
            :param sort_column:
                Sort column name
            :param sort_desc:
                Descending or ascending sort
            :param search:
                Search query
            :param execute:
                Execute query immediately? Default is `True`
            :param filters:
                List of filter tuples
        """

        # Will contain join paths with optional aliased object
        joins = {}
        count_joins = {}

        query = self.get_query()
        count_query = self.get_count_query() if not self.simple_list_pager else None

        # Ignore eager-loaded relations (prevent unnecessary joins)
        # TODO: Separate join detection for query and count query?
        if hasattr(query, '_join_entities'):
            for entity in query._join_entities:
                for table in entity.tables:
                    joins[table] = None

        # Apply search criteria
        if self._search_supported and search:
            query, count_query, joins, count_joins = self._apply_search(query,
                                                                        count_query,
                                                                        joins,
                                                                        count_joins,
                                                                        search)

        # Apply filters
        if filters and self._filters:
            query, count_query, joins, count_joins = self._apply_filters(query,
                                                                         count_query,
                                                                         joins,
                                                                         count_joins,
                                                                         filters)

        # Calculate number of rows if necessary
        count = count_query.scalar() if count_query else None

        # Auto join
        for j in self._auto_joins:
            query = query.options(joinedload(j))

        # Sorting
        query, joins = self._apply_sorting(query, joins, sort_column, sort_desc)

        # Pagination
        if page is not None:
            query = query.offset(page * self.page_size)

        query = query.limit(self.page_size)

        # Execute if needed
        if execute:
            query = query.all()

        return count, query

    def get_one(self, id):
        """
            Return a single model by its id.

            :param id:
                Model id
        """
        return self.session.query(self.model).get(tools.iterdecode(id))

    # Error handler
    def handle_view_exception(self, exc):
        if isinstance(exc, IntegrityError):
            flash(gettext('Integrity error. %(message)s', message=text_type(exc)), 'error')
            return True

        return super(ModelView, self).handle_view_exception(exc)

    # Model handlers
    def create_model(self, form):
        """
            Create model from form.

            :param form:
                Form instance
        """
        try:
            with self.session.begin_nested():
                model = self.model()
                form.populate_obj(model)
                self.session.add(model)
                self._on_model_change(form, model, True)
                self.session.flush()

        except Exception as ex:
            if not self.handle_view_exception(ex):
                flash(gettext('Failed to create record. %(error)s', error=str(ex)), 'error')
                log.exception('Failed to create record.')

            transaction.doom()
            return False
        else:
            self.after_model_change(form, model, True)

        return model

    def update_model(self, form, model):
        """
            Update model from form.

            :param form:
                Form instance
            :param model:
                Model instance
        """
        try:
            with self.session.begin_nested():
                form.populate_obj(model)
                self._on_model_change(form, model, False)

        except Exception as ex:
            if not self.handle_view_exception(ex):
                flash(gettext('Failed to update record. %(error)s', error=str(ex)), 'error')
                log.exception('Failed to update record.')

            transaction.doom()

            return False
        else:
            self.after_model_change(form, model, False)

        return True

    def delete_model(self, model):
        """
            Delete model.

            :param model:
                Model to delete
        """
        try:
            with self.session.begin_nested():
                self.on_model_delete(model)
                self.session.delete(model)
                self.session.flush()

        except Exception as ex:
            if not self.handle_view_exception(ex):
                flash(gettext('Failed to delete record. %(error)s', error=str(ex)), 'error')
                log.exception('Failed to delete record.')

            transaction.doom()
            return False
        else:
            self.after_model_delete(model)

        return True

    # Default model actions
    def is_action_allowed(self, name):
        # Check delete action permission
        if name == 'delete' and not self.can_delete:
            return False

        return super(ModelView, self).is_action_allowed(name)

    @action('delete',
            lazy_gettext('Delete'),
            lazy_gettext('Are you sure you want to delete selected records?'))
    def action_delete(self, ids):
        try:
            query = get_query_for_ids(self.get_query(), self.model, ids)

            if self.fast_mass_delete:
                count = query.delete(synchronize_session=False)
            else:
                count = 0

                for m in query.all():
                    if self.delete_model(m):
                        count += 1

            self.session.flush()

            flash(ngettext('Record was successfully deleted.',
                           '%(count)s records were successfully deleted.',
                           count,
                           count=count))

        except Exception as ex:
            if not self.handle_view_exception(ex):
                raise

            transaction.doom()
            flash(gettext('Failed to delete records. %(error)s', error=str(ex)), 'error')