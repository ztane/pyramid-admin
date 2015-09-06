from flask import Flask

import pyramid_admin as admin


# Create custom admin view
class MyAdminView(admin.BaseView):
    @admin.expose('/')
    def index(self):
        return self.render('myadmin.jinja2')


class AnotherAdminView(admin.BaseView):
    @admin.expose('/')
    def index(self):
        return self.render('anotheradmin.jinja2')

    @admin.expose('/test/')
    def test(self):
        return self.render('test.jinja2')


# Create flask app
app = Flask(__name__, template_folder='templates')
app.debug = True

# Flask views
@app.route('/')
def index():
    return '<a href="/admin/">Click me to get to Admin!</a>'

# Create admin interface
admin = admin.Admin(name="Example: Simple Views", template_mode='bootstrap3')
admin.add_view(MyAdminView(name="view1", category='Test'))
admin.add_view(AnotherAdminView(name="view2", category='Test'))
admin.init_app(app)

if __name__ == '__main__':

    # Start app
    app.run()
