"""Blueprint registration for the Flask app."""

# Keep imports inside the function to avoid circulars during app creation.
def register_blueprints(app):
    from blueprints.accounting import accounting_bp
    from blueprints.admin import admin_bp
    from blueprints.auth import auth_bp
    from blueprints.journal import journal_bp
    from blueprints.money_schedule import bp as money_schedule_bp
    from blueprints.transactions import transactions_bp
    from blueprints.user import user_bp
    from routes import forecast_bp  # legacy module outside package

    from finance_app.controllers.core import core_bp

    core_bp.app = app

    app.register_blueprint(forecast_bp)
    app.register_blueprint(money_schedule_bp)
    app.register_blueprint(accounting_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(journal_bp)
    app.register_blueprint(core_bp)
