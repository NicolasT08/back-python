from flask import Flask
from flask_caching import Cache
from .models import db

cache = Cache()

from .routes import api_blueprint

def create_app():
    app = Flask(__name__)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://usuario:password@localhost:3306/ancianato_db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Configuración de la caché
    app.config['CACHE_TYPE'] = 'SimpleCache'
    app.config['CACHE_DEFAULT_TIMEOUT'] = 60

    db.init_app(app)
    cache.init_app(app)
    
    app.register_blueprint(api_blueprint)

    return app