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

    # Register Global Error Handlers for SEO/Indexation and user experience
    from flask import render_template, send_from_directory
    import os

    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(os.path.join(app.root_path, 'static'),
                                   'favicon.ico', mimetype='image/vnd.microsoft.icon')

    @app.errorhandler(400)
    def bad_request(e):
        return render_template(
            'errors/error.html',
            code=400,
            title="Bad Request",
            description="The request could not be understood by the server due to malformed syntax.",
            action_url="/",
            action_text="Back to Sweet Shop"
        ), 400

    @app.errorhandler(403)
    def forbidden(e):
        return render_template(
            'errors/error.html',
            code=403,
            title="Access Forbidden",
            description="This exclusive area is restricted. You do not have permission to view this resource.",
            action_url="/",
            action_text="Back to Sweet Shop"
        ), 403

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template(
            'errors/error.html',
            code=404,
            title="Page Not Found",
            description="Oops! This bite-sized page doesn't exist. Maybe it was devoured?",
            action_url="/",
            action_text="Back to Sweet Shop"
        ), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return render_template(
            'errors/error.html',
            code=405,
            title="Method Not Allowed",
            description="The request method is not supported for the requested URL.",
            action_url="/",
            action_text="Back to Sweet Shop"
        ), 405

    @app.errorhandler(500)
    def internal_server_error(e):
        db.session.rollback()
        return render_template(
            'errors/error.html',
            code=500,
            title="Internal Server Error",
            description="Melted! Something went wrong on our end. We're whipping up a fix right now.",
            action_url="/",
            action_text="Back to Sweet Shop"
        ), 500

    return app

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        # db.create_all() # Will handle migrations/creation manually or on startup
        pass
    app.run(debug=True, port=5001)
