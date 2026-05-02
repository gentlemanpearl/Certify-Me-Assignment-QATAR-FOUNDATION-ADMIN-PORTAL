from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask import Blueprint, current_app, jsonify, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from models import Admin, Opportunity, db

api_bp = Blueprint("api", __name__, url_prefix="/api")

ALLOWED_CATEGORIES = {
    "technology",
    "business",
    "design",
    "marketing",
    "data",
    "other",
}


def _json():
    return request.get_json(silent=True) or {}


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def _validate_opportunity_payload(payload):
    required_fields = [
        "name",
        "duration",
        "start_date",
        "description",
        "skills",
        "category",
        "future_opportunities",
    ]
    for field in required_fields:
        value = payload.get(field)
        if value is None or str(value).strip() == "":
            return f"{field} is required."

    category = str(payload.get("category", "")).strip().lower()
    if category not in ALLOWED_CATEGORIES:
        return "Invalid category."

    skills_value = payload.get("skills")
    if isinstance(skills_value, list):
        cleaned = [s.strip() for s in skills_value if str(s).strip()]
        if not cleaned:
            return "skills is required."
    else:
        if not str(skills_value).strip():
            return "skills is required."
    return None


@api_bp.route("/auth/signup", methods=["POST"])
def signup():
    data = _json()
    full_name = str(data.get("full_name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    confirm_password = str(data.get("confirm_password", ""))

    if not full_name or not email or not password or not confirm_password:
        return jsonify({"status": "error", "message": "All fields are required."}), 400
    if "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"status": "error", "message": "Please enter a valid email address."}), 400
    if len(password) < 8:
        return jsonify({"status": "error", "message": "Password must be at least 8 characters."}), 400
    if password != confirm_password:
        return jsonify({"status": "error", "message": "Passwords do not match."}), 400
    if Admin.query.filter_by(email=email).first():
        return jsonify({"status": "error", "message": "An account with this email already exists."}), 409

    admin = Admin(
        full_name=full_name,
        email=email,
        password_hash=generate_password_hash(password),
    )
    db.session.add(admin)
    db.session.commit()
    return jsonify({"status": "success", "message": "Account created successfully."}), 201


@api_bp.route("/auth/login", methods=["POST"])
def login():
    data = _json()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    remember = bool(data.get("remember", False))

    admin = Admin.query.filter_by(email=email).first()
    if not admin or not check_password_hash(admin.password_hash, password):
        return jsonify({"status": "error", "message": "Invalid email or password"}), 401

    login_user(admin, remember=remember)
    return jsonify(
        {
            "status": "success",
            "message": "Login successful",
            "admin": {"id": admin.id, "full_name": admin.full_name, "email": admin.email},
        }
    )


@api_bp.route("/auth/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"status": "success", "message": "Signed out successfully."})


@api_bp.route("/auth/forgot-password", methods=["POST"])
def forgot_password():
    data = _json()
    email = str(data.get("email", "")).strip().lower()
    response_msg = "If the account exists, a password reset link has been generated."

    admin = Admin.query.filter_by(email=email).first()
    if admin:
        token = _serializer().dumps({"admin_id": admin.id}, salt="password-reset")
        reset_link = url_for("api.reset_password", token=token, _external=True)
        print(f"[PASSWORD RESET] {email}: {reset_link}")

    return jsonify({"status": "success", "message": response_msg})


def _verify_reset_token(token):
    try:
        return _serializer().loads(
            token,
            salt="password-reset",
            max_age=current_app.config["RESET_TOKEN_MAX_AGE_SECONDS"],
        )
    except SignatureExpired:
        return None, jsonify({"status": "error", "message": "Reset link has expired."}), 400
    except BadSignature:
        return None, jsonify({"status": "error", "message": "Invalid reset link."}), 400


@api_bp.route("/auth/reset-password/<token>", methods=["GET"])
def verify_reset_link(token):
    verified = _verify_reset_token(token)
    if isinstance(verified, tuple):
        return verified[1], verified[2]
    return jsonify({"status": "success", "message": "Reset link is valid."})


@api_bp.route("/auth/reset-password/<token>", methods=["POST"])
def reset_password(token):
    data = _json()
    password = str(data.get("password", ""))
    confirm_password = str(data.get("confirm_password", ""))

    if len(password) < 8:
        return jsonify({"status": "error", "message": "Password must be at least 8 characters."}), 400
    if password != confirm_password:
        return jsonify({"status": "error", "message": "Passwords do not match."}), 400

    verified = _verify_reset_token(token)
    if isinstance(verified, tuple):
        return verified[1], verified[2]

    payload = verified

    admin = db.session.get(Admin, payload.get("admin_id"))
    if not admin:
        return jsonify({"status": "error", "message": "Invalid reset link."}), 400

    admin.password_hash = generate_password_hash(password)
    db.session.commit()
    return jsonify({"status": "success", "message": "Password updated successfully."})


@api_bp.route("/auth/session", methods=["GET"])
def session_info():
    if not current_user.is_authenticated:
        return jsonify({"authenticated": False}), 401
    return jsonify(
        {
            "authenticated": True,
            "admin": {
                "id": current_user.id,
                "full_name": current_user.full_name,
                "email": current_user.email,
            },
        }
    )


@api_bp.route("/opportunities", methods=["GET"])
@login_required
def list_opportunities():
    records = (
        Opportunity.query.filter_by(admin_id=current_user.id)
        .order_by(Opportunity.id.desc())
        .all()
    )
    return jsonify({"status": "success", "data": [item.to_dict() for item in records]})


@api_bp.route("/opportunities", methods=["POST"])
@login_required
def create_opportunity():
    data = _json()
    validation_error = _validate_opportunity_payload(data)
    if validation_error:
        return jsonify({"status": "error", "message": validation_error}), 400

    max_applicants = data.get("max_applicants")
    if max_applicants in ("", None):
        max_applicants = None
    else:
        try:
            max_applicants = int(max_applicants)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "Maximum applicants must be a number."}), 400

    opportunity = Opportunity(
        name=str(data["name"]).strip(),
        duration=str(data["duration"]).strip(),
        start_date=str(data["start_date"]).strip(),
        description=str(data["description"]).strip(),
        skills=", ".join([s.strip() for s in data["skills"] if s.strip()])
        if isinstance(data["skills"], list)
        else str(data["skills"]).strip(),
        category=str(data["category"]).strip().lower(),
        future_opportunities=str(data["future_opportunities"]).strip(),
        max_applicants=max_applicants,
        admin_id=current_user.id,
    )
    db.session.add(opportunity)
    db.session.commit()
    return jsonify({"status": "success", "data": opportunity.to_dict()}), 201


def _load_owned_opportunity(opportunity_id):
    opportunity = Opportunity.query.get_or_404(opportunity_id)
    if opportunity.admin_id != current_user.id:
        return None
    return opportunity


@api_bp.route("/opportunities/<int:opportunity_id>", methods=["GET"])
@login_required
def get_opportunity(opportunity_id):
    opportunity = _load_owned_opportunity(opportunity_id)
    if not opportunity:
        return jsonify({"status": "error", "message": "Not found."}), 404
    return jsonify({"status": "success", "data": opportunity.to_dict()})


@api_bp.route("/opportunities/<int:opportunity_id>", methods=["PUT"])
@login_required
def update_opportunity(opportunity_id):
    opportunity = _load_owned_opportunity(opportunity_id)
    if not opportunity:
        return jsonify({"status": "error", "message": "Not found."}), 404

    data = _json()
    validation_error = _validate_opportunity_payload(data)
    if validation_error:
        return jsonify({"status": "error", "message": validation_error}), 400

    max_applicants = data.get("max_applicants")
    if max_applicants in ("", None):
        max_applicants = None
    else:
        try:
            max_applicants = int(max_applicants)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "Maximum applicants must be a number."}), 400

    opportunity.name = str(data["name"]).strip()
    opportunity.duration = str(data["duration"]).strip()
    opportunity.start_date = str(data["start_date"]).strip()
    opportunity.description = str(data["description"]).strip()
    opportunity.skills = (
        ", ".join([s.strip() for s in data["skills"] if s.strip()])
        if isinstance(data["skills"], list)
        else str(data["skills"]).strip()
    )
    opportunity.category = str(data["category"]).strip().lower()
    opportunity.future_opportunities = str(data["future_opportunities"]).strip()
    opportunity.max_applicants = max_applicants
    db.session.commit()

    return jsonify({"status": "success", "data": opportunity.to_dict()})


@api_bp.route("/opportunities/<int:opportunity_id>", methods=["DELETE"])
@login_required
def delete_opportunity(opportunity_id):
    opportunity = _load_owned_opportunity(opportunity_id)
    if not opportunity:
        return jsonify({"status": "error", "message": "Not found."}), 404

    db.session.delete(opportunity)
    db.session.commit()
    return jsonify({"status": "success", "message": "Opportunity deleted successfully."})
