from flask import (Flask, render_template, request, redirect, url_for, session,
                   flash, jsonify, abort, g)
import functools
import hmac
import ipaddress
import os
import pickle
import re
import secrets
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import pandas as pd
from flask_bcrypt import Bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.utils import secure_filename

import ats_scorer
import db
import interview
import job_matcher
import live_jobs
import llm
import mailer
import market_trends
import project_recommender
import resume_improver
import resume_parser
import semantic
import skill_gap
from config import env

# ---------------- APP SETUP ----------------

app = Flask(__name__)

_secret = env("SECRET_KEY")
if not _secret:
    raise RuntimeError("SECRET_KEY environment variable is required.")

app.secret_key = _secret
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
bcrypt = Bcrypt(app)

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB resume cap

# ---- ADMIN ACCOUNT (hard-coded on purpose) ----------------------------------
# The admin is NOT stored in the database and cannot be created by registering.
# Change these two values, then restart the app. The admin can only open:
#   /admin (admin panel), /market-trends, /logout
ADMIN_EMAIL = env("ADMIN_EMAIL", "")
ADMIN_PASSWORD = env("ADMIN_PASSWORD", "")
REQUIRE_VERIFICATION = (env("REQUIRE_EMAIL_VERIFICATION", "true") or "true").lower() != "false"

VERIFY_MAX_AGE = 48 * 3600
RESET_MAX_AGE = 3600

_serializer = URLSafeTimedSerializer(app.secret_key)

# ---------------- LOAD MODEL ----------------

model = pickle.load(open("model.pkl", "rb"))
encoders = pickle.load(open("encoders.pkl", "rb"))
target_encoder = pickle.load(open("target_encoder.pkl", "rb"))

# Skills the encoder actually understands as a single value. The dataset
# encodes skills as comma-joined combinations, but most of those combos
# are never picked exactly by a user, so we fall back to the first
# selected skill that the encoder recognises on its own.
KNOWN_SKILLS = set(encoders["Skills"].classes_)

# The certification dropdown offers "None", but the model was trained
# with missing certifications stored as the literal string "nan".
CERTIFICATION_ALIASES = {"None": "nan", "none": "nan", "": "nan"}

# ---------------- CAREER ROADMAPS ----------------
# One roadmap per career the model can predict, organised as four stages.
# Used by /roadmap, driven by the person's most recent prediction.

ROADMAPS = {
    "Software Engineer": [
        ("Foundation", ["Programming basics (Python or Java)", "Data structures & algorithms", "Git & version control"]),
        ("Core Skills", ["Object-oriented design", "SQL & databases", "REST APIs"]),
        ("Tools & Certifications", ["Docker basics", "AWS Certified Cloud Practitioner", "CI/CD fundamentals"]),
        ("Next Step", ["Build 2-3 portfolio projects", "Contribute to an open-source repo", "Apply for internships"]),
    ],
    "ML Engineer": [
        ("Foundation", ["Python & NumPy/Pandas", "Statistics & linear algebra", "SQL basics"]),
        ("Core Skills", ["Scikit-learn & model evaluation", "Feature engineering", "Deep learning fundamentals"]),
        ("Tools & Certifications", ["Google Data Analytics", "MLOps basics (MLflow, Docker)", "Cloud ML (AWS/GCP)"]),
        ("Next Step", ["Ship an end-to-end ML project", "Enter a Kaggle competition", "Apply for ML internships"]),
    ],
    "Data Entry Operator": [
        ("Foundation", ["Typing speed & accuracy", "MS Office fundamentals", "Basic data hygiene"]),
        ("Core Skills", ["Advanced Excel (formulas, pivot tables)", "Data validation techniques", "Attention to detail practice"]),
        ("Tools & Certifications", ["Tally ERP", "MS Office Specialist", "Google Workspace basics"]),
        ("Next Step", ["Take on a data-cleanup project", "Learn basic SQL for reporting", "Apply for entry-level roles"]),
    ],
    "Business Analyst": [
        ("Foundation", ["Business fundamentals", "Excel & data analysis", "Communication skills"]),
        ("Core Skills", ["SQL for reporting", "Requirements gathering", "Process mapping"]),
        ("Tools & Certifications", ["Google Data Analytics", "Power BI or Tableau", "Agile/Scrum basics"]),
        ("Next Step", ["Build a case-study portfolio", "Shadow a live project", "Apply for analyst roles"]),
    ],
    "Financial Analyst": [
        ("Foundation", ["Accounting fundamentals", "Excel modelling", "Financial statements"]),
        ("Core Skills", ["Financial analysis & ratios", "Forecasting & budgeting", "Valuation basics"]),
        ("Tools & Certifications", ["CFA Level 1", "Advanced Excel", "Bloomberg/Reuters basics"]),
        ("Next Step", ["Build a financial model portfolio", "Internship at a finance firm", "Apply for analyst roles"]),
    ],
    "Junior Accountant": [
        ("Foundation", ["Bookkeeping basics", "Accounting principles", "MS Excel"]),
        ("Core Skills", ["Ledgers & reconciliation", "Tax basics", "Payroll processing"]),
        ("Tools & Certifications", ["Tally ERP", "GST/Tax filing basics", "QuickBooks basics"]),
        ("Next Step", ["Assist on live audits", "Apply for articleship/internship", "Apply for junior accountant roles"]),
    ],
    "Marketing Executive": [
        ("Foundation", ["Marketing fundamentals", "Communication & copywriting", "Consumer behaviour basics"]),
        ("Core Skills", ["Digital marketing channels", "Content strategy", "Campaign analytics"]),
        ("Tools & Certifications", ["Digital Marketing certification", "Google Analytics basics", "Canva/design basics"]),
        ("Next Step", ["Run a small campaign end-to-end", "Build a marketing portfolio", "Apply for executive roles"]),
    ],
    "Sales Assistant": [
        ("Foundation", ["Product knowledge basics", "Communication skills", "Customer service fundamentals"]),
        ("Core Skills", ["Negotiation techniques", "CRM tools", "Objection handling"]),
        ("Tools & Certifications", ["MS Office", "Basic CRM certification", "Retail/POS systems"]),
        ("Next Step", ["Practice mock sales pitches", "Take a retail/sales internship", "Apply for sales assistant roles"]),
    ],
    "Clerk": [
        ("Foundation", ["MS Office basics", "Record keeping", "Communication skills"]),
        ("Core Skills", ["Filing & documentation systems", "Basic accounting entries", "Correspondence handling"]),
        ("Tools & Certifications", ["MS Office Specialist", "Typing certification", "Basic Tally"]),
        ("Next Step", ["Volunteer for admin work", "Apply for clerical internships", "Apply for clerk roles"]),
    ],
    "School Counselor": [
        ("Foundation", ["Psychology fundamentals", "Communication & empathy", "Child/adolescent development"]),
        ("Core Skills", ["Counselling techniques", "Conflict resolution", "Career guidance methods"]),
        ("Tools & Certifications", ["Mental Health Basics", "Counselling certification", "Crisis-response training"]),
        ("Next Step", ["Intern at a school counselling office", "Shadow a licensed counselor", "Apply for counselor roles"]),
    ],
    "Professor": [
        ("Foundation", ["Subject mastery (Bachelor's/Master's)", "Research methodology", "Academic writing"]),
        ("Core Skills", ["Curriculum design", "Public speaking & teaching", "Peer-reviewed publishing"]),
        ("Tools & Certifications", ["PhD / higher qualification", "Teaching certification (NET/SET where applicable)", "Research tools (LaTeX, citation managers)"]),
        ("Next Step", ["Publish or co-author a paper", "Teach as a guest lecturer/TA", "Apply for faculty positions"]),
    ],
    "Research Scientist": [
        ("Foundation", ["Strong subject fundamentals", "Statistics & research design", "Scientific writing"]),
        ("Core Skills", ["Experimental design", "Data analysis (Python/R)", "Literature review skills"]),
        ("Tools & Certifications", ["Google Data Analytics", "Domain-specific lab certifications", "Research software (R, MATLAB, or Python)"]),
        ("Next Step", ["Assist on a research project", "Publish or present findings", "Apply for research positions"]),
    ],
}

GENERIC_ROADMAP = [
    ("Foundation", ["Complete your profile with real skills and certifications", "Identify 2-3 careers that interest you", "Brush up on core communication skills"]),
    ("Core Skills", ["Pick one technical or domain skill and go deep", "Practice with small real projects", "Learn the tools your target roles expect"]),
    ("Tools & Certifications", ["Take one recognised certification", "Build a simple portfolio or resume", "Get comfortable with MS Office / Google Workspace"]),
    ("Next Step", ["Run the Career Prediction to get a personalised roadmap", "Apply what you learn to an internship", "Revisit this roadmap as your skills grow"]),
]

# ---------------- HELPERS ----------------

def init_db():
    db.init_db()


def _csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = _csrf_token


@app.before_request
def _csrf_protect():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("_csrf", "")
        if not expected or not hmac.compare_digest(sent, expected):
            if request.path.startswith("/api/"):
                return jsonify(error="Session expired - reload the page."), 400
            flash("Your session expired. Please try again.")
            return redirect(request.referrer or url_for("login"))


@app.context_processor
def _inject_globals():
    return {"is_admin": session.get("role") == "admin"}


def login_required(view):
    """Regular-user pages. The admin has no user account, so any attempt to
    open a user feature is bounced back to the admin panel."""
    @functools.wraps(view)
    def wrapped(*a, **kw):
        if session.get("role") == "admin":
            flash("The admin account can only use the Admin Panel and Market Trends.")
            return redirect(url_for("admin_panel"))
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*a, **kw)
    return wrapped


def user_or_admin_required(view):
    """Pages that both signed-in users and the admin may open (Market Trends)."""
    @functools.wraps(view)
    def wrapped(*a, **kw):
        if session.get("role") != "admin" and "user_id" not in session:
            return redirect(url_for("login"))
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    @functools.wraps(view)
    def wrapped(*a, **kw):
        if session.get("role") != "admin":
            if "user_id" in session:
                abort(403)
            return redirect(url_for("login"))
        return view(*a, **kw)
    return wrapped


def is_admin_credentials(email, password):
    """Constant-time check against the hard-coded admin login."""
    ok_email = hmac.compare_digest(email.strip().lower().encode(), ADMIN_EMAIL.lower().encode())
    ok_pass = hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode())
    return ok_email and ok_pass


def login_admin():
    session.clear()
    session["role"] = "admin"
    session["user_name"] = "Admin"
    session["user_email"] = ADMIN_EMAIL


def uid():
    return session["user_id"]


def login_user(u):
    session.clear()
    session["user_id"] = u["id"]
    session["user_name"] = u["name"]
    session["user_email"] = u["email"]
    session["role"] = "user"
    # restore the most recent prediction so the dashboard survives logouts
    lp = db.latest_prediction(u["id"])
    if lp:
        session["last_prediction"] = lp["career"]
        session["last_skills"] = lp["skills"]
        session["last_education"] = lp["education"]


def resume_text():
    return db.get_state(uid(), "resume_text")


# ---- tiny in-memory rate limiter (per process; fine for a project demo) ----
_hits = defaultdict(list)


def rate_limited(key, limit, window):
    now_ = time.time()
    _hits[key] = [t for t in _hits[key] if now_ - t < window]
    if len(_hits[key]) >= limit:
        return True
    _hits[key].append(now_)
    return False


def _is_local_request():
    try:
        return ipaddress.ip_address(request.remote_addr or "").is_loopback
    except ValueError:
        return False


def _external_url(endpoint, **values):
    base = env("APP_BASE_URL")
    path = url_for(endpoint, **values)
    return (base.rstrip("/") + path) if base else url_for(endpoint, _external=True, **values)


def send_verification(u):
    token = _serializer.dumps({"id": u["id"], "email": u["email"]}, salt="verify")
    link = _external_url("verify_email", token=token)
    sent = mailer.send(
        u["email"], "Verify your CareerAI account",
        f"Hi {u['name']},\n\nConfirm your email to activate your CareerAI account:\n{link}\n\n"
        "This link expires in 48 hours. If you didn't sign up, ignore this email.")
    return link, sent


def send_reset(u):
    token = _serializer.dumps({"id": u["id"], "pw": u["password"][-16:]}, salt="reset")
    link = _external_url("reset_password", token=token)
    sent = mailer.send(
        u["email"], "Reset your CareerAI password",
        f"Hi {u['name']},\n\nUse this link to choose a new password:\n{link}\n\n"
        "It expires in 1 hour and works once. If you didn't ask for this, ignore this email.")
    return link, sent


def learned_skill_set(user_id, career):
    """Skills counted as learned = ones the user marked manually on the Skill
    Gap page + skills linked to roadmap items they've ticked."""
    manual = db.get_learned(user_id)
    ticked = db.get_progress(user_id, career)
    linked = []
    for item in ticked:
        linked += roadmap_item_skills(career, item)
    return sorted(set(manual) | set(linked)), manual


def roadmap_item_skills(career, item):
    req = skill_gap.SKILL_REQUIREMENTS.get(career)
    if not req:
        return []
    required = req.get("core_skills", []) + req.get("supporting_skills", [])
    found = semantic.find_in_text(item, required, literal_only=True)
    return [s for s in required if s in found]


def current_gap(user_id, career, skills):
    learned, _ = learned_skill_set(user_id, career)
    return skill_gap.compute_skill_gap(skills, career, learned)


def roadmap_progress(user_id, career):
    stages = ROADMAPS.get(career, GENERIC_ROADMAP)
    total = sum(len(items) for _, items in stages)
    done = db.get_progress(user_id, career) if career else set()
    valid = {i for _, items in stages for i in items}
    done = done & valid
    pct = round(len(done) / total * 100) if total else 0
    return stages, done, total, pct


# ---------------- HOME ----------------

@app.route('/')
def index():
    return render_template("index.html")


# ---------------- REGISTER ----------------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.route('/register', methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"].strip()[:80]
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        confirm = request.form["confirm_password"]

        if not name or not EMAIL_RE.match(email):
            flash("Please enter your name and a valid email address.")
            return redirect(url_for("register"))

        if password != confirm:
            flash("Passwords do not match.")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash("Password must be at least 8 characters.")
            return redirect(url_for("register"))

        if email == ADMIN_EMAIL.lower():
            flash("Email already exists.")
            return redirect(url_for("register"))

        hashed = bcrypt.generate_password_hash(password).decode("utf-8")
        is_admin = 0
        verified = 0 if REQUIRE_VERIFICATION else 1

        try:
            with db.get_db() as conn:
                conn.execute(
                    "INSERT INTO users(name,email,password,is_admin,is_verified,created_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s)",
                    (name, email, hashed, is_admin, verified, db.now()))
        except db.IntegrityError:
            flash("Email already exists.")
            return redirect(url_for("register"))

        if not REQUIRE_VERIFICATION:
            flash("Registration successful. You can log in now.")
            return redirect(url_for("login"))

        u = db.get_user_by_email(email)
        link, sent = send_verification(u)
        return render_template(
            "check_email.html", email=email, purpose="verify", sent=sent,
            dev_link=link if (not sent and _is_local_request()) else None)

    return render_template("register.html")


@app.route('/verify/<token>')
def verify_email(token):
    try:
        data = _serializer.loads(token, salt="verify", max_age=VERIFY_MAX_AGE)
    except SignatureExpired:
        flash("That verification link has expired. Log in to request a new one.")
        return redirect(url_for("login"))
    except BadSignature:
        flash("That verification link is not valid.")
        return redirect(url_for("login"))

    u = db.get_user(data["id"])
    if not u or u["email"] != data["email"]:
        flash("That verification link is not valid.")
        return redirect(url_for("login"))

    with db.get_db() as conn:
        conn.execute("UPDATE users SET is_verified=1 WHERE id=%s", (u["id"],))
    flash("Email verified! You can log in now.")
    return redirect(url_for("login"))


@app.route('/resend-verification', methods=["POST"])
def resend_verification():
    email = request.form.get("email", "").strip().lower()
    generic = "If that account exists and isn't verified yet, a new verification email has been sent."
    if rate_limited(f"resend:{request.remote_addr}", 5, 3600) or rate_limited(f"resend:{email}", 3, 3600):
        flash("Too many requests. Please try again later.")
        return redirect(url_for("login"))
    u = db.get_user_by_email(email) if email else None
    if u and not u["is_verified"]:
        link, sent = send_verification(u)
        if not sent and _is_local_request():
            return render_template("check_email.html", email=email, purpose="verify", sent=False, dev_link=link)
    flash(generic)
    return redirect(url_for("login"))


# ---------------- LOGIN ----------------

@app.route('/login', methods=["GET", "POST"])
def login():

    unverified_email = None

    if request.method == "POST":

        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if rate_limited(f"login:{request.remote_addr}:{email}", 8, 600):
            flash("Too many login attempts. Please wait a few minutes and try again.")
            return render_template("login.html"), 429

        # hard-coded admin account (never looked up in the database)
        if email == ADMIN_EMAIL.lower():
            if is_admin_credentials(email, password):
                login_admin()
                return redirect(url_for("admin_panel"))
            flash("Invalid Email or Password")
            return render_template("login.html")

        user = db.get_user_by_email(email)

        if user and bcrypt.check_password_hash(user["password"], password):

            if REQUIRE_VERIFICATION and not user["is_verified"]:
                unverified_email = email
                flash("Please verify your email before logging in.")
                return render_template("login.html", unverified_email=unverified_email)

            login_user(user)
            return redirect(url_for("dashboard"))

        flash("Invalid Email or Password")

    return render_template("login.html", unverified_email=unverified_email)


# ---------------- FORGOT / RESET PASSWORD ----------------

@app.route('/forgot-password', methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        if rate_limited(f"forgot:{request.remote_addr}", 5, 3600) or rate_limited(f"forgot:{email}", 3, 3600):
            flash("Too many requests. Please try again later.")
            return redirect(url_for("forgot_password"))

        u = db.get_user_by_email(email) if email else None
        link, sent = (send_reset(u) if u else (None, False))

        # same response whether or not the account exists (no user enumeration)
        return render_template(
            "check_email.html", email=email, purpose="reset", sent=sent,
            dev_link=link if (link and not sent and _is_local_request()) else None)

    return render_template("forgot_password.html")


@app.route('/reset-password/<token>', methods=["GET", "POST"])
def reset_password(token):
    try:
        data = _serializer.loads(token, salt="reset", max_age=RESET_MAX_AGE)
    except SignatureExpired:
        flash("That reset link has expired. Please request a new one.")
        return redirect(url_for("forgot_password"))
    except BadSignature:
        flash("That reset link is not valid.")
        return redirect(url_for("forgot_password"))

    u = db.get_user(data["id"])
    # the token embeds part of the current password hash, so it stops working
    # as soon as the password has been changed (single use)
    if not u or u["password"][-16:] != data["pw"]:
        flash("That reset link has already been used or is no longer valid.")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        pw = request.form.get("password", "")
        if len(pw) < 8:
            flash("Password must be at least 8 characters.")
            return render_template("reset_password.html", token=token)
        if pw != request.form.get("confirm_password", ""):
            flash("Passwords do not match.")
            return render_template("reset_password.html", token=token)
        hashed = bcrypt.generate_password_hash(pw).decode("utf-8")
        with db.get_db() as conn:
            # a successful reset also proves the mailbox is theirs
            conn.execute("UPDATE users SET password=%s, is_verified=1 WHERE id=%s", (hashed, u["id"]))
        flash("Password updated. You can log in with your new password.")
        return redirect(url_for("login"))

    return render_template("reset_password.html", token=token)


# ---------------- DASHBOARD ----------------

def _sparkline(values, w=260, h=60, pad=6):
    pts = [v for v in values if v is not None]
    if len(pts) < 2:
        return None
    step = (w - 2 * pad) / (len(pts) - 1)
    coords = []
    for i, v in enumerate(pts):
        x = pad + i * step
        y = h - pad - (v / 100) * (h - 2 * pad)
        coords.append((round(x, 1), round(y, 1)))
    return {"points": " ".join(f"{x},{y}" for x, y in coords), "last": coords[-1], "w": w, "h": h}


@app.route('/dashboard')
@login_required
def dashboard():

    history = db.list_predictions(uid())
    timeline = list(reversed(history))[:8]  # newest first

    career = session.get("last_prediction")
    gap = None
    rm_pct = None
    if career:
        gap = current_gap(uid(), career, session.get("last_skills", []))
        _, _, _, rm_pct = roadmap_progress(uid(), career)

    return render_template(
        "dashboard.html",
        user_name=session["user_name"],
        last_prediction=career,
        last_skills=session.get("last_skills", []),
        last_education=session.get("last_education"),
        resume_uploaded=bool(resume_text()),
        timeline=timeline,
        history_count=len(history),
        spark=_sparkline([h["readiness"] for h in history]),
        gap=gap,
        roadmap_pct=rm_pct,
    )


# ---------------- RESUME UPLOAD ----------------

@app.route('/resume-upload', methods=["GET", "POST"])
@login_required
def resume_upload():

    error = None

    if request.method == "POST":

        file = request.files.get("resume")

        if not file or file.filename == "":
            error = "Please choose a PDF or DOCX resume to upload."

        elif not resume_parser.allowed_file(file.filename):
            error = "Only PDF or DOCX files are supported."

        else:

            # unique temp name so two users uploading "resume.pdf" never collide
            filename = f"{uid()}_{secrets.token_hex(4)}_{secure_filename(file.filename)}"
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)

            try:
                parsed = resume_parser.parse_resume(filepath)

                # Extracted fields pre-fill /predict. The form stays editable.
                # Stored in the database (not the cookie session - resume text
                # is far bigger than the ~4 KB a cookie can hold).
                db.set_state(uid(), "resume_data", {
                    "education": parsed["education"],
                    "specialization": parsed["specialization"],
                    "skills": parsed["skills"],
                    "certification": parsed["certification"],
                    "cgpa": parsed["cgpa"],
                    "projects": parsed["projects"],
                    "internships": parsed["internships"],
                })
                db.set_state(uid(), "resume_text", parsed["raw_text"][:20000])

                flash("Resume analyzed! Review and edit the pre-filled details below before predicting.")
                return redirect(url_for("predict"))

            except Exception as e:
                print("Resume Parse Error:", e)
                error = "We couldn't read that resume. Please try a different PDF/DOCX file."

            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)

    return render_template(
        "resume_upload.html",
        error=error,
        user_name=session["user_name"]
    )


# ---------------- PREDICT ----------------

@app.route('/predict', methods=["GET", "POST"])
@login_required
def predict():

    prediction = None
    confidence = None
    error = None
    selected_skills = []

    resume_data = db.get_state(uid(), "resume_data")

    if request.method == "POST":

        education = request.form["education"]
        specialization = request.form["specialization"]

        # Get multiple selected skills
        selected_skills = request.form.getlist("skills")

        certification_label = request.form["certification"]
        certification = CERTIFICATION_ALIASES.get(certification_label, certification_label)

        cgpa_raw = request.form["cgpa"]

        try:
            cgpa = float(cgpa_raw)
        except ValueError:
            cgpa = None

        if cgpa is None:
            error = "Please enter a valid CGPA / Percentage."

        elif not selected_skills:
            error = "Please select at least one skill."

        else:

            try:

                # Use the first selected skill the model actually recognises.
                # (The dataset encodes skills as combinations, so an
                # unrecognised single skill would otherwise crash the model.)
                skill = next((s for s in selected_skills if s in KNOWN_SKILLS), None)

                if skill is None:
                    skill = "Python"

                enc_education = encoders["Education Level"].transform([education])[0]
                enc_specialization = encoders["Specialization"].transform([specialization])[0]
                enc_skill = encoders["Skills"].transform([skill])[0]
                enc_certification = encoders["Certifications"].transform([certification])[0]

                sample = pd.DataFrame([{
                    "Education Level": enc_education,
                    "Specialization": enc_specialization,
                    "Skills": enc_skill,
                    "Certifications": enc_certification,
                    "CGPA/Percentage": cgpa
                }])

                pred = model.predict(sample)
                prediction = target_encoder.inverse_transform(pred)[0]

                try:
                    proba = model.predict_proba(sample)[0]
                    confidence = round(float(proba[list(model.classes_).index(pred[0])]) * 100, 1)
                except Exception:
                    confidence = None

                # Remember this prediction so the Dashboard, Roadmap and
                # Skill Gap pages can build on it.
                session["last_prediction"] = prediction
                session["last_skills"] = selected_skills
                session["last_education"] = education

                # History: one row per prediction, with the readiness score at
                # that moment so the dashboard timeline can show the trend.
                readiness = current_gap(uid(), prediction, selected_skills)["readiness"]
                db.add_prediction(uid(), prediction, confidence, education, specialization,
                                  selected_skills, certification_label, cgpa, readiness)

                # The prediction form has now been confirmed by the user,
                # so the pre-fill data has served its purpose.
                db.del_state(uid(), "resume_data")

            except Exception as e:

                print("Prediction Error:", e)
                error = "We couldn't generate a prediction from those details. Please check your inputs and try again."

    return render_template(
        "predict.html",
        prediction=prediction,
        confidence=confidence,
        error=error,
        selected_skills=selected_skills,
        user_name=session["user_name"],
        resume_data=resume_data,
        resume_uploaded=bool(resume_text())
    )


# ---------------- ROADMAP + PROGRESS TRACKER ----------------

@app.route('/roadmap')
@login_required
def roadmap():

    career = session.get("last_prediction")
    stages, done, total, pct = roadmap_progress(uid(), career)

    linked = {}
    gap = None
    if career:
        for _, items in stages:
            for it in items:
                sk = roadmap_item_skills(career, it)
                if sk:
                    linked[it] = sk
        gap = current_gap(uid(), career, session.get("last_skills", []))

    return render_template(
        "roadmap.html",
        user_name=session["user_name"],
        career=career,
        stages=stages,
        done=done,
        total=total,
        pct=pct,
        linked=linked,
        readiness=gap["readiness"] if gap else None,
    )


@app.route('/api/progress/toggle', methods=["POST"])
@login_required
def api_progress_toggle():
    career = session.get("last_prediction")
    if not career:
        return jsonify(error="Run a prediction first."), 400

    data = request.get_json(silent=True) or {}
    item = data.get("item", "")
    done = bool(data.get("done"))

    stages = ROADMAPS.get(career, GENERIC_ROADMAP)
    if item not in {i for _, items in stages for i in items}:
        return jsonify(error="Unknown roadmap item."), 400

    db.set_progress(uid(), career, item, done)

    _, ticked, total, pct = roadmap_progress(uid(), career)
    gap = current_gap(uid(), career, session.get("last_skills", []))
    return jsonify(done=len(ticked), total=total, pct=pct,
                   readiness=gap["readiness"], base_readiness=gap["base_readiness"],
                   skills=roadmap_item_skills(career, item))


# ---------------- SKILL GAP ANALYSIS ----------------

@app.route('/skill-gap')
@login_required
def skill_gap_view():

    career = session.get("last_prediction")

    if not career:
        flash("Run a Career Prediction first to see your Skill Gap Analysis.")
        return redirect(url_for("predict"))

    user_skills = session.get("last_skills", [])
    learned, manual = learned_skill_set(uid(), career)
    gap = skill_gap.compute_skill_gap(user_skills, career, learned)

    return render_template(
        "skill_gap.html",
        user_name=session["user_name"],
        gap=gap,
        manual_learned=set(manual),
    )


@app.route('/skill-gap/learn', methods=["POST"])
@login_required
def skill_gap_learn():
    skill = request.form.get("skill", "").strip()
    action = request.form.get("action", "learn")
    career = session.get("last_prediction")
    req = skill_gap.SKILL_REQUIREMENTS.get(career, skill_gap.GENERIC_REQUIREMENTS) if career else {}
    allowed = set(req.get("core_skills", []) + req.get("supporting_skills", []))
    if skill and skill in allowed:
        db.set_learned(uid(), skill, action == "learn")
        flash(f"Marked {skill} as learned." if action == "learn" else f"Removed {skill} from learned skills.")
    return redirect(url_for("skill_gap_view"))


# ---------------- ATS RESUME SCORE ----------------

@app.route('/ats-score')
@login_required
def ats_score_view():

    career = session.get("last_prediction")
    text = resume_text()

    if not career:
        flash("Run a Career Prediction first to see your ATS Resume Score.")
        return redirect(url_for("predict"))

    if not text:
        flash("Upload your resume first so we can score it against this career.")
        return redirect(url_for("resume_upload"))

    result = ats_scorer.score_resume(text, career)

    return render_template(
        "ats_score.html",
        user_name=session["user_name"],
        result=result
    )


# ---------------- JOB DESCRIPTION MATCHER ----------------

@app.route('/jd-match', methods=["GET", "POST"])
@login_required
def jd_match():

    text = resume_text()
    if not text:
        flash("Upload your resume first so we can compare it with a job description.")
        return redirect(url_for("resume_upload"))

    result, error, jd = None, None, ""

    if request.method == "POST":
        jd = request.form.get("jd", "").strip()
        if len(jd) < 40:
            error = "Paste the full job description (at least a few lines) so we can extract its keywords."
        else:
            jd = jd[:8000]
            result = ats_scorer.score_against_jd(text, jd)

    return render_template("jd_match.html", user_name=session["user_name"],
                           result=result, error=error, jd=jd)


# ---------------- RESUME IMPROVER ----------------

@app.route('/resume-improve', methods=["GET", "POST"])
@login_required
def resume_improve():

    text = resume_text()
    if not text:
        flash("Upload your resume first so we can suggest improvements.")
        return redirect(url_for("resume_upload"))

    result = None
    if request.method == "POST":
        result = resume_improver.improve(text, session.get("last_prediction"))

    return render_template("resume_improve.html", user_name=session["user_name"],
                           result=result, ai_available=llm.is_configured(),
                           ai_label=llm.label(), career=session.get("last_prediction"))


# ---------------- MOCK INTERVIEW ----------------

@app.route('/interview')
@login_required
def interview_page():

    career = session.get("last_prediction")
    if not career:
        flash("Run a Career Prediction first - the mock interview is tailored to your predicted career.")
        return redirect(url_for("predict"))

    state = db.get_state(uid(), "interview")
    return render_template(
        "interview.html", user_name=session["user_name"], career=career, state=state,
        history=db.list_interview_results(uid()), mode=interview.mode_label(),
    )


@app.route('/interview/start', methods=["POST"])
@login_required
def interview_start():
    career = session.get("last_prediction")
    if not career:
        return redirect(url_for("predict"))

    kind = request.form.get("kind", "mixed")
    if kind not in ("technical", "hr", "mixed"):
        kind = "mixed"
    try:
        n = max(3, min(8, int(request.form.get("count", 5))))
    except ValueError:
        n = 5

    questions, source = interview.generate_questions(career, kind, n, session.get("last_skills", []))
    db.set_state(uid(), "interview", {
        "career": career, "kind": kind, "source": source,
        "questions": questions, "answers": [], "finished": False,
    })
    return redirect(url_for("interview_page"))


@app.route('/interview/answer', methods=["POST"])
@login_required
def interview_answer():
    state = db.get_state(uid(), "interview")
    if not state or state.get("finished"):
        return redirect(url_for("interview_page"))

    idx = len(state["answers"])
    if idx >= len(state["questions"]):
        return redirect(url_for("interview_page"))

    answer = request.form.get("answer", "")[:interview.MAX_ANSWER_CHARS]
    q = state["questions"][idx]
    result = interview.evaluate(q, answer, state["career"])
    state["answers"].append({"answer": answer, "result": result})

    if len(state["answers"]) >= len(state["questions"]):
        state["finished"] = True
        scores = [a["result"]["score"] for a in state["answers"]]
        db.add_interview_result(uid(), state["career"], state["kind"],
                                round(sum(scores) / len(scores), 1), len(scores))

    db.set_state(uid(), "interview", state)
    return redirect(url_for("interview_page"))


@app.route('/interview/reset', methods=["POST"])
@login_required
def interview_reset():
    db.del_state(uid(), "interview")
    return redirect(url_for("interview_page"))


# ---------------- PROJECT RECOMMENDATIONS ----------------

@app.route('/projects')
@login_required
def projects_view():

    career = session.get("last_prediction")

    if not career:
        flash("Run a Career Prediction first to see project recommendations.")
        return redirect(url_for("predict"))

    projects = project_recommender.get_projects(career)

    return render_template(
        "projects.html",
        user_name=session["user_name"],
        career=career,
        projects=projects
    )


# ---------------- JOB MATCHING (LIVE) ----------------

@app.route('/jobs')
@login_required
def jobs_view():

    career = session.get("last_prediction")

    if not career:
        flash("Run a Career Prediction first to see matching jobs.")
        return redirect(url_for("predict"))

    location = request.args.get("location", "").strip()[:60]
    user_skills = session.get("last_skills", [])
    learned, _ = learned_skill_set(uid(), career)
    jobs, meta = live_jobs.get_jobs(user_skills + learned, career, location)

    return render_template(
        "jobs.html",
        user_name=session["user_name"],
        career=career,
        jobs=jobs,
        meta=meta,
        location=location,
        adzuna=live_jobs.adzuna_configured(),
    )


# ---------------- MARKET TRENDS ----------------

def _line_chart(values, w=560, h=200, pad=34):
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    step = (w - 2 * pad) / (len(values) - 1)
    pts = []
    for i, v in enumerate(values):
        x = pad + i * step
        y = h - pad - ((v - lo) / span) * (h - 2 * pad)
        pts.append((round(x, 1), round(y, 1), v))
    return {"w": w, "h": h, "pad": pad, "pts": pts, "poly": " ".join(f"{x},{y}" for x, y, _ in pts),
            "lo": lo, "hi": hi}


@app.route('/market-trends')
@user_or_admin_required
def market_trends_view():

    default = session.get("last_prediction")
    career = request.args.get("career") or default or "Software Engineer"
    if career not in market_trends.CAREERS:
        career = default if default in market_trends.CAREERS else "Software Engineer"

    trend = market_trends.get_trend(career)

    return render_template(
        "market_trends.html",
        user_name=session["user_name"],
        career=career,
        trend=trend,
        chart=_line_chart(trend["demand_series"]),
        years=market_trends.YEARS,
        compare=market_trends.compare_all(career),
        careers=list(market_trends.CAREERS),
        note=market_trends.NOTE,
        live_count=market_trends.live_openings(career),
        max_sal=max(trend["salary_lpa"].values()),
    )


# ---------------- PROFILE ----------------

@app.route('/profile')
@login_required
def profile():

    return render_template(
        "profile.html",
        user_name=session["user_name"],
        email=session["user_email"],
        last_prediction=session.get("last_prediction")
    )


# ---------------- ADMIN PANEL ----------------

@app.route('/admin')
@admin_required
def admin_panel():

    q = request.args.get("q", "").strip()[:80]

    with db.get_db() as conn:
        total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        verified = conn.execute("SELECT COUNT(*) c FROM users WHERE is_verified=1").fetchone()["c"]
        week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        new_week = conn.execute("SELECT COUNT(*) c FROM users WHERE created_at>=%s", (week_ago,)).fetchone()["c"]
        total_preds = conn.execute("SELECT COUNT(*) c FROM predictions").fetchone()["c"]
        avg_ready = conn.execute("SELECT AVG(readiness) a FROM predictions WHERE readiness IS NOT NULL").fetchone()["a"]
        avg_conf = conn.execute("SELECT AVG(confidence) a FROM predictions WHERE confidence IS NOT NULL").fetchone()["a"]
        interviews = conn.execute("SELECT COUNT(*) c, AVG(avg_score) a FROM interview_results").fetchone()
        resumes = conn.execute("SELECT COUNT(*) c FROM user_state WHERE `key`='resume_text'").fetchone()["c"]

        top_careers = conn.execute(
            "SELECT career, COUNT(*) c FROM predictions GROUP BY career ORDER BY c DESC LIMIT 10").fetchall()

        # most common skills across all predictions
        skill_counter = Counter()
        import json as _json
        for r in conn.execute("SELECT skills FROM predictions").fetchall():
            skill_counter.update(_json.loads(r["skills"] or "[]"))

        # signups per day, last 14 days
        since = (datetime.utcnow() - timedelta(days=13)).strftime("%Y-%m-%d")
        by_day = {r["d"]: r["c"] for r in conn.execute(
            "SELECT substr(created_at,1,10) d, COUNT(*) c FROM users WHERE created_at>=%s GROUP BY d",
            (since,)).fetchall()}

        sql = ("SELECT u.id,u.name,u.email,u.is_verified,u.created_at, "
               "(SELECT COUNT(*) FROM predictions p WHERE p.user_id=u.id) preds, "
               "(SELECT career FROM predictions p WHERE p.user_id=u.id ORDER BY p.id DESC LIMIT 1) last_career "
               "FROM users u")
        args = ()
        if q:
            sql += " WHERE u.name LIKE %s OR u.email LIKE %s"
            args = (f"%{q}%", f"%{q}%")
        sql += " ORDER BY u.id DESC LIMIT 200"
        users = conn.execute(sql, args).fetchall()

        recent = conn.execute(
            "SELECT p.career,p.confidence,p.readiness,p.created_at,u.name FROM predictions p "
            "JOIN users u ON u.id=p.user_id ORDER BY p.id DESC LIMIT 8").fetchall()

    days = [(datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(13, -1, -1)]
    signups = [{"day": d[5:], "n": by_day.get(d, 0)} for d in days]

    return render_template(
        "admin.html",
        user_name=session["user_name"],
        stats={
            "users": total_users, "verified": verified, "unverified": total_users - verified, "new_week": new_week,
            "predictions": total_preds, "resumes": resumes,
            "avg_ready": round(float(avg_ready)) if avg_ready is not None else None,
            "avg_conf": round(float(avg_conf), 1) if avg_conf is not None else None,
            "interviews": interviews["c"],
            "interview_avg": round(float(interviews["a"]), 1) if interviews["a"] is not None else None,
        },
        top_careers=[dict(r) for r in top_careers],
        top_skills=skill_counter.most_common(8),
        signups=signups,
        users=[dict(u) for u in users],
        recent=[dict(r) for r in recent],
        q=q,
    )


@app.route('/admin/users/<int:user_id>/verify', methods=["POST"])
@admin_required
def admin_verify_user(user_id):
    with db.get_db() as conn:
        conn.execute("UPDATE users SET is_verified=1 WHERE id=%s", (user_id,))
    flash("User marked as verified.")
    return redirect(url_for("admin_panel"))


@app.route('/admin/users/<int:user_id>/delete', methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    with db.get_db() as conn:
        conn.execute("DELETE FROM users WHERE id=%s", (user_id,))
    flash("User deleted.")
    return redirect(url_for("admin_panel"))


# ---------------- ERRORS ----------------

@app.errorhandler(403)
def forbidden(_e):
    return render_template("error.html", code=403, message="You don't have permission to view this page."), 403


@app.errorhandler(413)
def too_large(_e):
    flash("That file is too large (5 MB maximum).")
    return redirect(url_for("resume_upload"))


# ---------------- LOGOUT ----------------

@app.route('/logout')
def logout():

    session.clear()

    flash("Logged out successfully.")

    return redirect(url_for("login"))


# ---------------- RUN ----------------

init_db()

if __name__ == "__main__":

    app.run(debug=True)