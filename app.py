from flask import Flask, render_template
from flask_login import LoginManager

from config import Config
from models import Admin, db
from routes import api_bp


def create_app():
    app = Flask(
        __name__,
        template_folder="sky",
        static_folder="sky",
        static_url_path="",
    )
    app.config.from_object(Config)

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "index"

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Admin, int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        return {"status": "error", "message": "Authentication required."}, 401

    app.register_blueprint(api_bp)

    @app.route("/")
    def index():
        return render_template("admin.html")

    with app.app_context():
        db.create_all()

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(debug=True)
