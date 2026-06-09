from flask import Flask
from config import Config
from extensions import db, login_manager
from werkzeug.middleware.proxy_fix import ProxyFix

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Configure ProxyFix to support Cloud Run reverse proxies / load balancers
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

    db.init_app(app)
    login_manager.init_app(app)

    from routes.customer import customer_bp
    from routes.admin import admin_bp
    from routes.auth import auth_bp
    from models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    app.register_blueprint(customer_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(auth_bp, url_prefix='/auth')

    return app

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        # db.create_all() # Will handle migrations/creation manually or on startup
        pass
    app.run(debug=True, port=5001)
