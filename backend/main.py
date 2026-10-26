import os
import re
import logging
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from google import genai
from google.genai import types

import mysql.connector
from mysql.connector import Error, IntegrityError
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
)
from dotenv import load_dotenv
from google import genai


# ============================================================
# 1. PROJECT CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"

TEMPLATES_DIR = FRONTEND_DIR / "Templates"
STATICS_DIR = FRONTEND_DIR / "Statics"
CSS_DIR = STATICS_DIR 
JS_DIR = STATICS_DIR / "js"

load_dotenv(PROJECT_DIR / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    template_folder=str(TEMPLATES_DIR),
    static_folder=str(STATICS_DIR),
    static_url_path="/static",
)

app.config["SECRET_KEY"] = (
    os.getenv("FLASK_SECRET_KEY") or os.urandom(32).hex()
)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024


# ============================================================
# 2. DATABASE CONFIGURATION
# ============================================================

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "ai_health_prediction"),
    "connection_timeout": 10,
}


def get_db_connection():
    """Create a connection to the configured MySQL database."""
    return mysql.connector.connect(**DB_CONFIG)


def initialize_database():
    """Create the database and patients table when necessary."""
    connection = None
    cursor = None

    try:
        database_name = DB_CONFIG["database"]

        if not re.fullmatch(r"[A-Za-z0-9_]+", database_name):
            raise ValueError("Invalid database name in configuration.")

        server_config = {
            key: value
            for key, value in DB_CONFIG.items()
            if key != "database"
        }

        connection = mysql.connector.connect(**server_config)
        cursor = connection.cursor()

        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{database_name}`"
        )
        cursor.execute(f"USE `{database_name}`")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS patients (
                id INT AUTO_INCREMENT PRIMARY KEY,
                full_name VARCHAR(150) NOT NULL,
                date_of_birth DATE NOT NULL,
                email VARCHAR(254) NOT NULL,
                glucose DECIMAL(10, 2) NOT NULL,
                haemoglobin DECIMAL(10, 2) NOT NULL,
                cholesterol DECIMAL(10, 2) NOT NULL,
                remarks TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY unique_patient (
                    full_name,
                    date_of_birth,
                    email
                )
            )
            """
        )

        connection.commit()
        logger.info("Database and patients table are ready.")

    except Exception:
        logger.exception("Database initialization failed.")
        raise

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


# ============================================================
# 3. INPUT VALIDATION
# ============================================================

def parse_date(value):
    """Accept DD.MM.YYYY, DD/MM/YYYY or YYYY-MM-DD."""
    value = (value or "").strip()

    if not value:
        raise ValueError("Date of birth is required.")

    parsed_date = None

    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            parsed_date = datetime.strptime(value, fmt).date()
            break
        except ValueError:
            continue

    if parsed_date is None:
        raise ValueError(
            "Invalid date. Use DD/MM/YYYY or DD.MM.YYYY."
        )

    if parsed_date > date.today():
        raise ValueError("Date of birth cannot be in the future.")

    return parsed_date


def validate_email(email):
    """Validate a basic email address format."""
    email = (email or "").strip()

    if len(email) > 254:
        raise ValueError("Email address is too long.")

    pattern = (
        r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
        r"@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$"
    )

    if not re.fullmatch(pattern, email):
        raise ValueError("Please enter a valid email address.")

    return email


def validate_number(value, field_name, maximum=100000):
    """Validate a finite, non-negative numeric value."""
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        raise ValueError(f"{field_name} must be numeric.")

    if not number.is_finite():
        raise ValueError(f"{field_name} must be a finite number.")

    if number < 0 or number > maximum:
        raise ValueError(
            f"{field_name} must be between 0 and {maximum}."
        )

    return number.quantize(Decimal("0.01"))


def validate_patient_form(form):
    """Validate patient fields from a form or JSON dictionary."""
    full_name = str(form.get("full_name") or "").strip()

    if not full_name:
        raise ValueError("Full name is required.")

    if len(full_name) > 150:
        raise ValueError("Full name cannot exceed 150 characters.")

    if any(ord(char) < 32 for char in full_name):
        raise ValueError("Full name contains invalid characters.")

    dob = parse_date(form.get("date_of_birth"))
    email = validate_email(form.get("email"))

    glucose = validate_number(form.get("glucose"), "Glucose")
    haemoglobin = validate_number(
        form.get("haemoglobin"), "Haemoglobin"
    )
    cholesterol = validate_number(
        form.get("cholesterol"), "Cholesterol"
    )

    return {
        "full_name": full_name,
        "date_of_birth": dob,
        "email": email,
        "glucose": glucose,
        "haemoglobin": haemoglobin,
        "cholesterol": cholesterol,
    }


# ============================================================
# 4. GEMINI AI INTEGRATION
# ============================================================

def generate_health_remarks(patient):
    """Generate concise educational remarks using Gemini AI."""

    api_key = os.getenv("GEMINI_API_KEY")
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is missing from the .env file."
        )

    client = genai.Client(api_key=api_key)

    prompt = f"""
Write three short educational sentences about these blood-test values.

Glucose: {patient['glucose']}
Haemoglobin: {patient['haemoglobin']}
Cholesterol: {patient['cholesterol']}

Rules:
- Explain these measurements in simple language.
- Do not diagnose any disease.
- Do not prescribe medicine or treatment.
- Units and laboratory reference ranges are unknown.
- Explain that a qualified healthcare professional should interpret
  the results using the correct units, reference ranges and history.
- Return plain text only.
"""

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                http_options=types.HttpOptions(
                    timeout=60000
                ),
                temperature=0.2,
                max_output_tokens=200,
            ),
        )

        remarks = (response.text or "").strip()

        if not remarks:
            raise RuntimeError(
                "Gemini returned an empty response."
            )

        logger.info("Gemini generated health remarks successfully.")

        return remarks[:5000]

    except Exception as exc:
        logger.exception("Gemini health-remarks generation failed.")
        raise RuntimeError(
            "Gemini could not generate remarks. "
            "Please retry after checking the server logs."
        ) from exc

# ============================================================
# 5. DATABASE OPERATIONS
# ============================================================

def get_all_patients():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT id, full_name, date_of_birth, email,
                   glucose, haemoglobin, cholesterol, remarks,
                   created_at, updated_at
            FROM patients
            ORDER BY id ASC
            """
        )
        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


def get_patient(patient_id):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT id, full_name, date_of_birth, email,
                   glucose, haemoglobin, cholesterol, remarks,
                   created_at, updated_at
            FROM patients
            WHERE id = %s
            """,
            (patient_id,),
        )
        return cursor.fetchone()

    finally:
        cursor.close()
        connection.close()


def insert_patient(patient, remarks):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO patients (
                full_name, date_of_birth, email,
                glucose, haemoglobin, cholesterol, remarks
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                patient["full_name"],
                patient["date_of_birth"],
                patient["email"],
                patient["glucose"],
                patient["haemoglobin"],
                patient["cholesterol"],
                remarks,
            ),
        )

        connection.commit()
        return cursor.lastrowid

    except IntegrityError as exc:
        connection.rollback()

        if exc.errno == 1062:
            raise ValueError(
                "This patient record already exists."
            ) from exc

        raise

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


def update_patient(patient_id, patient, remarks=None):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        if remarks is None:
            cursor.execute(
                """
                UPDATE patients
                SET full_name = %s,
                    date_of_birth = %s,
                    email = %s,
                    glucose = %s,
                    haemoglobin = %s,
                    cholesterol = %s
                WHERE id = %s
                """,
                (
                    patient["full_name"],
                    patient["date_of_birth"],
                    patient["email"],
                    patient["glucose"],
                    patient["haemoglobin"],
                    patient["cholesterol"],
                    patient_id,
                ),
            )
        else:
            cursor.execute(
                """
                UPDATE patients
                SET full_name = %s,
                    date_of_birth = %s,
                    email = %s,
                    glucose = %s,
                    haemoglobin = %s,
                    cholesterol = %s,
                    remarks = %s
                WHERE id = %s
                """,
                (
                    patient["full_name"],
                    patient["date_of_birth"],
                    patient["email"],
                    patient["glucose"],
                    patient["haemoglobin"],
                    patient["cholesterol"],
                    remarks,
                    patient_id,
                ),
            )

        if cursor.rowcount == 0:
            cursor.execute(
                "SELECT id FROM patients WHERE id = %s",
                (patient_id,),
            )
            if cursor.fetchone() is None:
                raise LookupError("Patient record not found.")

        connection.commit()

    except IntegrityError as exc:
        connection.rollback()

        if exc.errno == 1062:
            raise ValueError(
                "Updating this record would create a duplicate."
            ) from exc

        raise

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


def delete_patient(patient_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "DELETE FROM patients WHERE id = %s",
            (patient_id,),
        )
        deleted = cursor.rowcount > 0
        connection.commit()
        return deleted

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


def json_safe_patient(patient):
    """Convert MySQL date, decimal and timestamp values to JSON types."""
    if not patient:
        return patient

    result = dict(patient)

    if result.get("date_of_birth"):
        result["date_of_birth"] = (
            result["date_of_birth"].isoformat()
        )

    for field in ("glucose", "haemoglobin", "cholesterol"):
        result[field] = float(result[field])

    for field in ("created_at", "updated_at"):
        if result.get(field):
            result[field] = result[field].isoformat()

    return result


# ============================================================
# 6. WEB ROUTES
# ============================================================

@app.route("/")
def index():
    """Show all patient records."""
    try:
        patients = get_all_patients()
        return render_template("index.html", patients=patients)

    except Error:
        logger.exception("Unable to load patient records.")
        flash("Unable to connect to the database.", "error")
        return render_template("index.html", patients=[]), 503


@app.route("/patients/add", methods=["GET", "POST"])
def add_patient():
    """Display the form and create a patient record."""
    if request.method == "GET":
        return render_template("add_patient.html")

    try:
        # Step 1: Validate patient details
        patient = validate_patient_form(request.form)

        # Step 2: Generate AI remarks.
        # If Gemini fails, continue saving the patient.
        try:
            remarks = generate_health_remarks(patient)

        except Exception:
            logger.exception(
                "Gemini AI failed. Saving patient with fallback remarks."
            )

            remarks = (
                "AI remarks are temporarily unavailable. "
                "Please try again later. These test values should "
                "be interpreted by a qualified healthcare professional."
            )

        # Step 3: Save patient details and remarks to MySQL
        patient_id = insert_patient(patient, remarks)

        # Step 4: Show success message and redirect
        flash(
            f"Patient record #{patient_id} created successfully.",
            "success",
        )

        return redirect(url_for("index"))

    except ValueError as exc:
        # Validation errors or duplicate-record errors
        flash(str(exc), "error")

    except Error as exc:
        # MySQL database errors
        logger.exception("Database error while adding patient.")

        if getattr(exc, "errno", None) == 1062:
            flash(
                "This patient record already exists.",
                "error",
            )
        else:
            flash(
                "Database error while saving the record.",
                "error",
            )

    except Exception:
        # Any other unexpected errors
        logger.exception("Unexpected error while adding patient.")

        flash(
            "An unexpected error occurred while saving the patient.",
            "error",
        )

    # Return the form if validation or database saving fails
    return render_template(
        "add_patient.html",
        form_data=request.form,
    ), 400

@app.route("/patients/edit/<int:patient_id>", methods=["GET", "POST"])
def edit_patient(patient_id):
    """Display the edit form and update a patient record."""
    try:
        patient = get_patient(patient_id)

        if patient is None:
            flash("Patient record not found.", "error")
            return redirect(url_for("index"))

        if request.method == "GET":
            return render_template(
                "edit_patient.html",
                patient=patient,
            )

        updated_data = validate_patient_form(request.form)

        blood_fields = (
            "glucose", "haemoglobin", "cholesterol"
        )

        blood_values_changed = any(
            updated_data[field] != patient[field]
            for field in blood_fields
        )

        remarks = None

        if blood_values_changed:
            remarks = generate_health_remarks(updated_data)

        update_patient(patient_id, updated_data, remarks)

        flash("Patient record updated successfully.", "success")
        return redirect(url_for("index"))

    except ValueError as exc:
        flash(str(exc), "error")

    except RuntimeError as exc:
        flash(f"AI integration error: {exc}", "error")

    except LookupError:
        flash("Patient record not found.", "error")
        return redirect(url_for("index"))

    except Error:
        logger.exception("Database error while editing patient.")
        flash("Database error while updating the record.", "error")

    except Exception:
        logger.exception("Unexpected error while editing patient.")
        flash("An unexpected error occurred.", "error")

    try:
        current_patient = get_patient(patient_id)
    except Error:
        current_patient = None

    if current_patient is None:
        return redirect(url_for("index"))

    return render_template(
        "edit_patient.html",
        patient=current_patient,
        form_data=request.form,
    ), 400


@app.route("/patients/delete/<int:patient_id>", methods=["POST"])
def remove_patient(patient_id):
    """Delete a patient record."""
    try:
        deleted = delete_patient(patient_id)

        if deleted:
            flash("Patient record deleted successfully.", "success")
        else:
            flash("Patient record not found.", "error")

    except Error:
        logger.exception("Database error while deleting patient.")
        flash("Unable to delete the record.", "error")

    return redirect(url_for("index"))


# ============================================================
# 7. JSON API ENDPOINTS
# ============================================================

@app.route("/api/patients", methods=["GET"])
def api_list_patients():
    """Return all patient records as JSON."""
    try:
        return jsonify([
            json_safe_patient(patient)
            for patient in get_all_patients()
        ]), 200

    except Error:
        logger.exception("API could not fetch patients.")
        return jsonify({"error": "Database unavailable."}), 503


@app.route("/api/patients/<int:patient_id>", methods=["GET"])
def api_get_patient(patient_id):
    """Return one patient record as JSON."""
    try:
        patient = get_patient(patient_id)

        if patient is None:
            return jsonify({"error": "Patient not found."}), 404

        return jsonify(json_safe_patient(patient)), 200

    except Error:
        logger.exception("API could not fetch patient.")
        return jsonify({"error": "Database unavailable."}), 503


@app.route("/api/patients", methods=["POST"])
def api_create_patient():
    """Create a patient using a JSON request."""
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "error": "A valid JSON object is required."
        }), 400

    try:
        patient = validate_patient_form(data)
        remarks = generate_health_remarks(patient)
        patient_id = insert_patient(patient, remarks)

        return jsonify({
            "message": "Patient created successfully.",
            "id": patient_id,
            "remarks": remarks,
        }), 201

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502

    except Error:
        logger.exception("API database error.")
        return jsonify({
            "error": "Database operation failed."
        }), 500


@app.route("/api/patients/<int:patient_id>", methods=["PUT"])
def api_update_patient(patient_id):
    """Update a patient using JSON."""
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "error": "A valid JSON object is required."
        }), 400

    try:
        existing = get_patient(patient_id)

        if existing is None:
            return jsonify({"error": "Patient not found."}), 404

        patient = validate_patient_form(data)

        blood_fields = (
            "glucose", "haemoglobin", "cholesterol"
        )

        changed = any(
            patient[field] != existing[field]
            for field in blood_fields
        )

        remarks = (
            generate_health_remarks(patient) if changed else None
        )

        update_patient(patient_id, patient, remarks)

        return jsonify({
            "message": "Patient updated successfully."
        }), 200

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502

    except LookupError:
        return jsonify({"error": "Patient not found."}), 404

    except Error:
        logger.exception("API update failed.")
        return jsonify({
            "error": "Database operation failed."
        }), 500


@app.route("/api/patients/<int:patient_id>", methods=["DELETE"])
def api_delete_patient(patient_id):
    """Delete a patient using JSON API."""
    try:
        if not delete_patient(patient_id):
            return jsonify({"error": "Patient not found."}), 404

        return jsonify({
            "message": "Patient deleted successfully."
        }), 200

    except Error:
        logger.exception("API delete failed.")
        return jsonify({
            "error": "Database operation failed."
        }), 500


# ============================================================
# 8. DIAGNOSTIC AND HEALTH ROUTES
# ============================================================

@app.route("/health")
def health_check():
    return jsonify({
        "status": "running",
        "application": "AI Health Prediction App",
    }), 200


@app.route("/debug/paths")
def debug_paths():
    """Diagnose template and static-file path issues."""
    return jsonify({
        "project_directory": str(PROJECT_DIR),
        "templates_directory": str(TEMPLATES_DIR),
        "templates_directory_exists": TEMPLATES_DIR.is_dir(),
        "static_directory": str(STATICS_DIR),
        "static_directory_exists": STATICS_DIR.is_dir(),
        "css_file_exists": (CSS_DIR / "style.css").is_file(),
        "javascript_file_exists": (JS_DIR / "script.js").is_file(),
        "css_url": url_for(
            "static", filename="css/style.css"
        ),
        "javascript_url": url_for(
            "static", filename="js/script.js"
        ),
    })


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Resource not found."}), 404

    return "Page not found.", 404


@app.errorhandler(413)
def file_too_large(_error):
    return jsonify({
        "error": "Request too large. Maximum size is 2 MB."
    }), 413


# ============================================================
# 9. APPLICATION ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        initialize_database()
    except Exception:
        logger.exception(
            "Application startup failed. Check MySQL and .env."
        )
        raise SystemExit(1)

    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
