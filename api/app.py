from flask import Flask
from flask_cors import CORS

from .summary_routes import summary_bp
from .crew_routes import crew_bp
from .flight_routes import flight_bp
from .pairing_routes import pairing_bp
from .reserve_routes import reserve_bp
from .alert_routes import alert_bp
from .risk_signal_routes import risk_signal_bp
from .decision_routes import decision_bp
from .meta_routes import meta_bp
from .rule_routes import rule_bp
from .cost_routes import cost_bp

app = Flask(__name__)
CORS(app)

app.register_blueprint(summary_bp)
app.register_blueprint(crew_bp)
app.register_blueprint(flight_bp)
app.register_blueprint(pairing_bp)
app.register_blueprint(reserve_bp)
app.register_blueprint(alert_bp)
app.register_blueprint(risk_signal_bp)
app.register_blueprint(decision_bp)
app.register_blueprint(meta_bp)
app.register_blueprint(rule_bp)
app.register_blueprint(cost_bp)

if __name__ == "__main__":
    app.run(debug=True)