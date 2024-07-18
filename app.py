# app.py

# app.py

import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import matplotlib.pyplot as plt
import io
import base64
from datetime import datetime
from data import get_mock_stock_data, get_mock_recommendations, get_mock_profile

# Configuration
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'you-will-never-guess'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL') or 'sqlite:///stock_portfolio.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['ALPHA_VANTAGE_API_KEY'] = os.environ.get('ALPHA_VANTAGE_API_KEY') or 'your_api_key_here'

# Extensions
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Logging setup
if not app.debug:
    if not os.path.exists('logs'):
        os.mkdir('logs')
    file_handler = RotatingFileHandler('logs/portfolio_tracker.log', maxBytes=10240, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info('Portfolio Tracker startup')

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(128))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Forms
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, ValidationError

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Sign In')

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    password2 = PasswordField(
        'Repeat Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user is not None:
            raise ValidationError('Please use a different username.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user is not None:
            raise ValidationError('Please use a different email address.')

class StockForm(FlaskForm):
    ticker = StringField('Ticker', validators=[DataRequired()])
    submit = SubmitField('Add Stock')

# Routes
@app.route('/')
@app.route('/index')
def index():
    return render_template('index.html', title='Home')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password')
            return redirect(url_for('login'))
        login_user(user, remember=form.remember_me.data)
        return redirect(url_for('index'))
    return render_template('login.html', title='Sign In', form=form)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Congratulations, you are now a registered user!')
        return redirect(url_for('login'))
    return render_template('register.html', title='Register', form=form)

@app.route('/dashboard')
@login_required
def dashboard():
    preferred_stocks = get_mock_profile(current_user)['preferred_stocks']
    stock_data = {ticker: get_stock_data(ticker) for ticker in preferred_stocks}
    return render_template('dashboard.html', title='Dashboard', stock_data=stock_data)

@app.route('/profile')
@login_required
def profile():
    profile_info = get_mock_profile(current_user)
    return render_template('profile.html', title='Profile', user=current_user, profile_info=profile_info)

@app.route('/stock_tracker', methods=['GET', 'POST'])
@login_required
def stock_tracker():
    form = StockForm()
    stock_data = None
    graph_url = None
    ticker = None

    if form.validate_on_submit():
        ticker = form.ticker.data
        stock_data = get_stock_data(ticker)
        if stock_data:
            graph_url = create_stock_graph(ticker, stock_data)
        else:
            flash('Error retrieving stock data. Displaying mock data.', 'danger')

    return render_template('stock_tracker.html', title='Stock Tracker', form=form, stock_data=stock_data, graph_url=graph_url, ticker=ticker)

@app.route('/recommendations')
@login_required
def recommendations():
    recommendations = get_mock_recommendations()
    return render_template('recommendations.html', title='Recommendations', recommendations=recommendations)

# Error handling
@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

# Stock Data with error handling and mock data fallback
def get_stock_data(ticker):
    api_key = app.config['ALPHA_VANTAGE_API_KEY']
    base_url = 'https://www.alphavantage.co/query?'
    function = 'TIME_SERIES_DAILY'
    url = f'{base_url}function={function}&symbol={ticker}&apikey={api_key}'
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        if 'Error Message' in data:
            app.logger.error(f"Error retrieving data for {ticker}")
            return get_mock_stock_data(ticker)
        
        time_series = data.get('Time Series (Daily)')
        if not time_series:
            return get_mock_stock_data(ticker)
        
        return time_series

    except requests.RequestException as e:
        app.logger.error(f"Request failed for {ticker}: {e}")
        return get_mock_stock_data(ticker)

# Dynamic graph creation
def create_stock_graph(ticker, time_series):
    dates = list(time_series.keys())
    close_prices = [float(time_series[date]['4. close']) for date in dates]

    plt.figure(figsize=(10, 5))
    plt.plot(dates, close_prices, marker='o', linestyle='-', color='b')
    plt.title(f'Stock Prices for {ticker}')
    plt.xlabel('Date')
    plt.ylabel('Close Price')
    plt.xticks(rotation=45)
    plt.tight_layout()

    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    graph_url = base64.b64encode(img.getvalue()).decode()
    plt.close()
    return f'data:image/png;base64,{graph_url}'

if __name__ == '__main__':
    app.run(debug=True)