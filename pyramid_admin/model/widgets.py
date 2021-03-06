from wtforms.widgets import HTMLString, html_params
from pyramid_admin import json

from pyramid_admin._compat import as_unicode
from pyramid_admin.babel import gettext
from pyramid_admin.helpers import get_url
from pyramid_admin.form import RenderTemplateWidget


class InlineFieldListWidget(RenderTemplateWidget):
    def __init__(self):
        super(InlineFieldListWidget, self).__init__('admin/model/inline_field_list.jinja2')


class InlineFormWidget(RenderTemplateWidget):
    def __init__(self):
        super(InlineFormWidget, self).__init__('admin/model/inline_form.jinja2')

    def __call__(self, field, **kwargs):
        kwargs.setdefault('form_opts', getattr(field, 'form_opts', None))
        return super(InlineFormWidget, self).__call__(field, **kwargs)


class AjaxSelect2Widget(object):
    def __init__(self, multiple=False):
        self.multiple = multiple

    def __call__(self, field, **kwargs):
        kwargs.setdefault('data-role', 'select2-ajax')
        kwargs.setdefault('data-url', get_url('.ajax_lookup', name=field.loader.name))

        allow_blank = getattr(field, 'allow_blank', False)
        if allow_blank and not self.multiple:
            kwargs['data-allow-blank'] = u'1'

        kwargs.setdefault('id', field.id)
        kwargs.setdefault('type', 'hidden')

        if self.multiple:
            result = []
            ids = []

            for value in field.data:
                data = field.loader.format(value)
                result.append(data)
                ids.append(as_unicode(data[0]))

            separator = getattr(field, 'separator', ',')

            kwargs['value'] = separator.join(ids)
            kwargs['data-json'] = json.dumps(result)
            kwargs['data-multiple'] = u'1'
        else:
            data = field.loader.format(field.data)

            if data:
                kwargs['value'] = data[0]
                kwargs['data-json'] = json.dumps(data)

        placeholder = gettext(field.loader.options.get('placeholder', 'Please select model'))
        kwargs.setdefault('data-placeholder', placeholder)

        return HTMLString('<input %s>' % html_params(name=field.name, **kwargs))


class XEditableWidget(object):
    """
        WTForms widget that provides in-line editing for the list view.

        Determines how to display the x-editable/ajax form based on the
        field inside of the FieldList (StringField, IntegerField, etc).
    """
    def __call__(self, field, **kwargs):
        kwargs.setdefault('data-value', kwargs.pop('value', ''))

        kwargs.setdefault('data-role', 'x-editable')
        kwargs.setdefault('data-url', './ajax/update/')

        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        kwargs.setdefault('href', '#')

        if not kwargs.get('pk'):
            raise Exception('pk required')
        kwargs['data-pk'] = str(kwargs.pop("pk"))

        kwargs['data-csrf'] = kwargs.pop("csrf", "")

        # subfield is the first entry (subfield) from FieldList (field)
        subfield = field.entries[0]

        kwargs = self.get_kwargs(subfield, kwargs)

        return HTMLString(
            '<a %s>%s</a>' % (html_params(**kwargs), kwargs['data-value'])
        )

    def get_kwargs(self, subfield, kwargs):
        """
            Return extra kwargs based on the subfield type.
        """
        if subfield.type == 'StringField':
            kwargs['data-type'] = 'text'
        elif subfield.type == 'TextAreaField':
            kwargs['data-type'] = 'textarea'
            kwargs['data-rows'] = '5'
        elif subfield.type == 'BooleanField':
            kwargs['data-type'] = 'select'
            # data-source = dropdown options
            kwargs['data-source'] = {'': 'False', '1': 'True'}
            kwargs['data-role'] = 'x-editable-boolean'
        elif subfield.type == 'Select2Field':
            kwargs['data-type'] = 'select'
            kwargs['data-source'] = dict(subfield.choices)
        elif subfield.type == 'DateField':
            kwargs['data-type'] = 'combodate'
            kwargs['data-format'] = 'YYYY-MM-DD'
            kwargs['data-template'] = 'YYYY-MM-DD'
        elif subfield.type == 'DateTimeField':
            kwargs['data-type'] = 'combodate'
            kwargs['data-format'] = 'YYYY-MM-DD HH:mm:ss'
            kwargs['data-template'] = 'YYYY-MM-DD  HH:mm:ss'
            # x-editable-combodate uses 1 minute increments
            kwargs['data-role'] = 'x-editable-combodate'
        elif subfield.type == 'TimeField':
            kwargs['data-type'] = 'combodate'
            kwargs['data-format'] = 'HH:mm:ss'
            kwargs['data-template'] = 'HH:mm:ss'
            kwargs['data-role'] = 'x-editable-combodate'
        elif subfield.type == 'IntegerField':
            kwargs['data-type'] = 'number'
        elif subfield.type in ['FloatField', 'DecimalField']:
            kwargs['data-type'] = 'number'
            kwargs['data-step'] = 'any'
        elif subfield.type in ['QuerySelectField', 'ModelSelectField']:
            kwargs['data-type'] = 'select'

            choices = {}
            for choice in subfield:
                try:
                    choices[str(choice._value())] = str(choice.label.text)
                except TypeError:
                    choices[str(choice._value())] = ""
            kwargs['data-source'] = choices
        else:
            raise Exception('Unsupported field type: %s' % (type(subfield),))

        return kwargs
