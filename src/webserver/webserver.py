"""
Webserver to handle users requsting telegeam access
"""
import os
import sys
from io import BytesIO
from wtforms import StringField, PasswordField, BooleanField
from wtforms.validators import InputRequired, Length
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, after_this_request, request, Response, redirect, url_for, abort
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user
from flask_bootstrap import Bootstrap
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from flask_wtf import FlaskForm
import gzip
import json
import functools
from sqlalchemy.ext.declarative import declarative_base
from database import TelegramUser


SECRET_LENGTH = 24

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from common import get_config, get_uri


debug = 'DEBUG' in os.environ and os.environ['DEBUG'] == "on"


def gzipped(f):
    @functools.wraps(f)
    def view_func(*args, **kwargs):
        @after_this_request
        def zipper(response):
            accept_encoding = request.headers.get('Accept-Encoding', '')

            if 'gzip' not in accept_encoding.lower():
                return response

            response.direct_passthrough = False

            if response.status_code < 200 or response.status_code >= 300 or 'Content-Encoding' in response.headers:
                return response
            gzip_buffer = BytesIO()
            gzip_file = gzip.GzipFile(mode='wb',
                                      fileobj=gzip_buffer)
            gzip_file.write(response.data)
            gzip_file.close()

            response.data = gzip_buffer.getvalue()
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Vary'] = 'Accept-Encoding'
            response.headers['Content-Length'] = len(response.data)

            return response

        return f(*args, **kwargs)

    return view_func


app = Flask("Telegram bot settings", template_folder=os.path.join(os.path.dirname(__file__), "templates"))


def set_app_db(a):
    settings = get_config()
    a.config["SQLALCHEMY_DATABASE_URI"] = get_uri(settings)
    a.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    return

set_app_db(app)

db = SQLAlchemy(app)


# flask-login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

login_manager.init_app(app)
Bootstrap(app)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), unique=True)
    password = db.Column(db.String(100))

    def __init__(self, id, username, password):
        self.id = id
        self.username = username
        self.password = generate_password_hash(password, method='sha256')

    def __repr__(self):
        return "%d/%s/%s" % (self.id, self.name)


Base = declarative_base()


class AppConfig(Base):
    __tablename__ = "app_config"
    id = db.Column(db.Integer, primary_key=True)
    secret = db.Column(db.BINARY(SECRET_LENGTH), unique=True)

    def __init__(self,id , secret):
        self.id = id
        self.secret = secret

    def __repr__(self):
        return "%d/%s/%s" % (self.id, self.name)

def init_db(uri):
    """
    Checks if db is init, if not inits it

    :return:
    """
    engine = create_engine(uri)
    User.metadata.create_all(engine)
    AppConfig.metadata.create_all(engine)
    TelegramUser.metadata.create_all(engine)

    # Add admin if does not exist

    Session = sessionmaker()
    Session.configure(bind=engine)
    session = Session()

    user = session.query(User).first()
    if user is None:
        settings = get_config()
        entry = User(id=0, username="admin", password=settings["webserver"]["init_password"])
        session.add(entry)
        session.commit()
        print('First run, created database with user admin')

    app_config = session.query(AppConfig).first()
    if app_config is None:
        entry = AppConfig(id=0, secret=os.urandom(SECRET_LENGTH))
        session.add(entry)
        session.commit()
        print('First run, created table with secret key for sessions')

        app_config = session.query(AppConfig).first()

    app.config["SECRET_KEY"] = app_config.secret
    return


class LoginForm(FlaskForm):
    username = StringField('username', validators=[InputRequired(), Length(min=4, max=15)])
    password = PasswordField('password', validators=[InputRequired(), Length(min=4, max=80)])
    remember = BooleanField('remember me')


@app.route("/")
@login_required
def root():
    return render_template("index.jinja2", users=get_telegram_user_list(), row=5)


@app.route("/update_role", methods=['POST'])
@login_required
def update_role():
    content = request.json
    user_id = content["user"]
    role = content["role"]
    update_user_role(user_id, role)
    return json.dumps({'success':True});

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()

    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.strip()).first()
        if user is not None and check_password_hash(user.password, form.password.data):
            login_user(user, remember=form.remember.data)
            return redirect('/')
        else:
            form.password.errors.append('Invalid username or password')

    return render_template('login.jinja2', form=form)


# somewhere to logout
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return Response('<p>Logged out</p>')


# handle login failed
@app.errorhandler(401)
def page_not_found(e):
    return Response('<p>Login failed</p>')


# callback to reload the user object
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
### Login stuff ###

def run():
    settings = get_config()
    app.run(debug=debug, host='0.0.0.0', port=int(settings["webserver"]["port"]), threaded=True)
    return

def get_telegram_user_list():
    engine = create_engine(app.config["SQLALCHEMY_DATABASE_URI"])
    # Add admin if does not exist

    Session = sessionmaker()
    Session.configure(bind=engine)
    session = Session()

    return session.query(TelegramUser)

def update_user_role(telegram_id, role):
    """
    Update the role of a user in the telegram database
    :param telegram_id:
    :param role:
    :return:
    :return:
    """
    engine = create_engine(app.config["SQLALCHEMY_DATABASE_URI"])
    Session = sessionmaker()
    Session.configure(bind=engine)
    session = Session()
    session.query(TelegramUser).filter(TelegramUser.id == telegram_id).update({"role": role})
    session.commit()
    return

if __name__ == "__main__":
    init_db(app)
    run()


