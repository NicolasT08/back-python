from flask import Flask
from .models import db
from .routes import api_blueprint

def create_app():
    app = Flask(__name__)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://usuario:password@localhost:3306/ancianato_db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    
    app.register_blueprint(api_blueprint)

    return app