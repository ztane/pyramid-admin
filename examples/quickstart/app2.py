from flask import Flask
from pyramid_admin import Admin, BaseView, expose


class MyView(BaseView):
    @expose('/')
    def index(self):
        return self.render('index.jinja2')

app = Flask(__name__)
app.debug = True

admin = Admin(app, name="Example: Quickstart2")
admin.add_view(MyView(name='Hello'))

if __name__ == '__main__':

    # Start app
    app.run()
