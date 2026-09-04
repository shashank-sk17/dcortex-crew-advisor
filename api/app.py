from flask import Flask
from flask_cors import CORS

from .summary_routes import summary_bp
from .crew_routes import crew_bp


app = Flask(__name__)
CORS(app)

app.register_blueprint(summary_bp)
app.register_blueprint(crew_bp)


if __name__ == "__main__":
    app.run(debug=True)