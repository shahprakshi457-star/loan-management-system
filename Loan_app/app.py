import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation

import mysql.connector
from mysql.connector import Error
from flask import (Flask, render_template, render_template_string, request,
                   redirect, url_for, flash, abort, session)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-key")

@app.template_filter("inr")
def inr(value):
    """Format a number the Indian way: 1000000 -> 10,00,000."""
    n = int(value)
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if n < 0 else "") + s

def money(value):
    """Rupees with paise, Indian grouping: 888488.5 -> ₹8,88,488.50"""
    v = Decimal(value).quantize(Decimal("0.01"))
    return "₹" + inr(int(v)) + "." + f"{abs(v) % 1:.2f}"[2:]


DB = dict(
    host=os.environ.get("DB_HOST", "localhost"),
    user=os.environ.get("DB_USER", "loan_app"),
    password=os.environ.get("DB_PASSWORD", "star"),
    database="loan_mang",
)

# Limits that mirror the column sizes in tables.sql, so we can reject bad input
# with a clear message instead of letting MySQL do it.
MAX_NAME, MAX_ADDRESS, MAX_EMAIL, MAX_USERNAME, MAX_REF = 100, 150, 100, 40, 60
MAX_RATE = Decimal("999.999")                 # annual_rate_pct is DECIMAL(6,3)
PHONE_RE = re.compile(r"[0-9]{10}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

# ------------------------------------------------------------------ DB helpers
def connect():
    return mysql.connector.connect(**DB)

def query(sql, params=()):
    """SELECT -> list of dicts. params or None so literal % (e.g. DATE_FORMAT) is safe."""
    conn = connect()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params or None)
        return cur.fetchall()
    finally:
        conn.close()

def execute(sql, params=()):
    """Single INSERT/UPDATE/DELETE -> rows affected."""
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()

def run_tx(statements):
    """Several statements as one all-or-nothing transaction."""
    conn = connect()
    try:
        cur = conn.cursor()
        for sql, params in statements:
            cur.execute(sql, params)
        conn.commit()
    except Error:
        conn.rollback()
        raise
    finally:
        conn.close()

# ------------------------------------------------------------------ error messages
COLUMN_LABELS = {
    "full_name": "Name", "dob": "Date of birth", "line1": "Address",
    "email": "Email", "phone": "Phone number", "username": "Username",
    "p_ref": "Payment reference", "bank_reference": "Payment reference",
    "p_amount": "Amount", "amount": "Amount", "mode": "Payment mode",
    "principal": "Principal", "annual_rate_pct": "Interest rate",
    "tenure_months": "Tenure", "start_date": "Start date",
}

def _grab(pattern, text):
    m = re.search(pattern, text)
    return m.group(1) if m else ""

def friendly(e):
    """Turn a MySQL error into a message a normal user can act on.

    The raw MySQL text is only written to the terminal, never shown on the page.
    """
    msg = e.msg or str(e)
    low = msg.lower()
    n = e.errno

    # Messages we wrote ourselves with SIGNAL in the triggers / procedures
    if n == 1644:
        return msg

    # Foreign key failed while inserting (child row) -> say WHICH rule failed
    if n == 1452 or "cannot add or update a child row" in low:
        target = _grab(r"REFERENCES\s+`(?:[^`]+`\.`)?([^`]+)`", msg)
        return {
            "officer_branch":  "This officer is not assigned to the selected branch.",
            "branch_product":  "The selected branch does not offer this loan product.",
            "officer_product": "This officer is not authorised to handle this loan product.",
            "borrower":        "That borrower no longer exists. Refresh the page and try again.",
            "postal_area":     "That pincode is not in the system. Pick one from the list.",
        }.get(target, "One of the selected items no longer exists. Refresh the page and try again.")

    # Foreign key failed while deleting (parent row)
    if n == 1451 or "cannot delete or update a parent row" in low:
        return "This record can't be deleted because other records depend on it."

    # Duplicates
    if n == 1062 or "duplicate entry" in low:
        key = _grab(r"for key '([^']+)'", msg).lower()
        if "phone" in key:
            return ("This borrower already has that phone number." if key.endswith("primary")
                    else "That phone number is already registered to another borrower.")
        if "email" in key:
            return ("This borrower already has that email address." if key.endswith("primary")
                    else "That email address is already registered to another borrower.")
        if key.endswith("mode"):
            return "That payment reference has already been used. Enter a different one."
        if "staff_login" in key:
            return "That username is already taken."
        return "That value already exists."

    # Text too long / numbers out of range / bad values
    if n == 1406 or "data too long" in low:
        label = COLUMN_LABELS.get(_grab(r"column '([^']+)'", msg), "One of the fields")
        return f"{label} is too long."
    if n in (1264, 1265, 1292, 1366, 1690) or "out of range" in low:
        label = COLUMN_LABELS.get(_grab(r"column '([^']+)'", msg), "One of the values")
        return f"{label} is invalid or outside the allowed range."
    if n == 3819 or "check constraint" in low:
        return "A value is outside the allowed range (amounts, rates and tenure must be above zero)."

    # Setup / connection problems
    if n in (2002, 2003, 2013, 2055):
        return "Can't reach the database. Make sure the MySQL service is running."
    if n == 1045:
        return "Database login failed. Check the DB_USER and DB_PASSWORD settings."
    if n == 1049:
        return f"Database '{DB['database']}' was not found. Run tables.sql first."
    if n in (1146, 1305):
        return "A required table or procedure is missing. Re-run the SQL scripts."

    app.logger.error("Unhandled database error %s: %s", n, msg)
    return "Something went wrong while saving. Please check your input and try again."

@app.errorhandler(Error)
def database_error(e):
    """Safety net: any database error nobody caught shows a friendly page, not a traceback."""
    flash(friendly(e))
    return render_template_string(
        "{% extends 'base.html' %}{% block body %}"
        "<h2>Database problem</h2><p>That page could not be loaded.</p>"
        "<p><a href=\"{{ url_for('borrowers') }}\">Back to Borrowers</a></p>"
        "{% endblock %}"), 500

# ------------------------------------------------------------------ input checks
def borrower_error(f, check_phone=True):
    name = f["full_name"].strip()
    if not name:
        return "Name is required."
    if len(name) > MAX_NAME:
        return f"Name must be {MAX_NAME} characters or fewer."
    try:
        dob = date.fromisoformat(f["dob"])
    except ValueError:
        return "Enter a valid date of birth."
    if dob.year < 1900 or dob > date.today():
        return "Enter a valid date of birth."
    if (date.today() - dob).days < 18 * 365:
        return "Borrower must be at least 18 years old."
    if check_phone and not PHONE_RE.fullmatch(f["phone"].strip()):
        return "Phone must be exactly 10 digits."
    email = f.get("email", "").strip()
    if len(email) > MAX_EMAIL:
        return f"Email must be {MAX_EMAIL} characters or fewer."
    if email and not EMAIL_RE.fullmatch(email):
        return "Enter a valid email address."
    line1 = f["line1"].strip()
    if not line1:
        return "Address is required."
    if len(line1) > MAX_ADDRESS:
        return f"Address must be {MAX_ADDRESS} characters or fewer."
    return None

def loan_problems(f, principal, rate, tenure):
    """Every reason this application would be rejected, in plain words.

    An empty list means it is fine to insert. The trigger and the foreign keys in
    MySQL still enforce the same rules; this just explains them properly first.
    """
    if not (principal.is_finite() and rate.is_finite()):
        return ["Principal and interest rate must be ordinary numbers."]
    if principal <= 0 or rate <= 0 or tenure <= 0:
        return ["Principal, interest rate and tenure must all be greater than zero."]
    if rate > MAX_RATE:
        return [f"Annual interest rate cannot be more than {MAX_RATE}%."]

    problems = []
    oid, brid, pid = f["officer_id"], f["branch_id"], f["product_id"]

    if not query("SELECT 1 FROM borrower WHERE borrower_id=%s", (f["borrower_id"],)):
        problems.append("The selected borrower no longer exists. Refresh the page and try again.")

    info = query("""SELECT o.name AS officer, b.name AS branch, p.*
                    FROM officer o, branch b, loan_product p
                    WHERE o.officer_id=%s AND b.branch_id=%s AND p.product_id=%s""",
                 (oid, brid, pid))
    if not info:
        problems.append("The selected officer, branch or product no longer exists. "
                        "Refresh the page and try again.")
        return problems
    i = info[0]

    # 1. product limits (same rule as the trg_loan_limits trigger)
    if not (i["min_amt"] <= principal <= i["max_amt"]):
        problems.append(f"{i['name']} principal must be between "
                        f"₹{inr(i['min_amt'])} and ₹{inr(i['max_amt'])}.")
    if not (i["min_tenure_months"] <= tenure <= i["max_tenure_months"]):
        problems.append(f"{i['name']} tenure must be between "
                        f"{i['min_tenure_months']} and {i['max_tenure_months']} months.")

    # 2. officer / branch / product rule (same as the three composite foreign keys)
    combo = []
    if not query("SELECT 1 FROM officer_branch WHERE officer_id=%s AND branch_id=%s", (oid, brid)):
        combo.append(f"{i['officer']} is not assigned to {i['branch']}.")
    if not query("SELECT 1 FROM branch_product WHERE branch_id=%s AND product_id=%s", (brid, pid)):
        combo.append(f"{i['branch']} does not offer {i['name']}.")
    if not query("SELECT 1 FROM officer_product WHERE officer_id=%s AND product_id=%s", (oid, pid)):
        combo.append(f"{i['officer']} is not authorised to handle {i['name']}.")
    if combo:
        problems.extend(combo)
        ok = query("""SELECT o.name AS officer, br.name AS branch
                      FROM officer_branch ob
                      JOIN branch_product bp  ON bp.branch_id = ob.branch_id AND bp.product_id = %s
                      JOIN officer_product op ON op.officer_id = ob.officer_id AND op.product_id = %s
                      JOIN officer o  ON o.officer_id = ob.officer_id
                      JOIN branch br  ON br.branch_id = ob.branch_id
                      ORDER BY o.name, br.name""", (pid, pid))
        if ok:
            options = "; ".join(f"{r['officer']} at {r['branch']}" for r in ok)
            problems.append(f"For {i['name']} you can choose: {options}.")
        else:
            problems.append(f"No officer and branch are currently set up for {i['name']}.")
    return problems

# ------------------------------------------------------------------ LOGIN
@app.before_request
def require_login():
    """Every page except login/register needs a logged-in user."""
    if request.endpoint in ("login", "register", "static") or session.get("user"):
        return
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form["username"].strip()
        p = request.form["password"]
        rows = query("SELECT password_hash FROM staff_login WHERE username=%s", (u,))
        if rows and check_password_hash(rows[0]["password_hash"], p):
            session.clear()
            session["user"] = u
            return redirect(url_for("borrowers"))
        flash("Wrong username or password.")
    return render_template("auth.html", mode="login")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        u = f["username"].strip()
        if len(u) < 3:
            flash("Username must be at least 3 characters.")
        elif len(u) > MAX_USERNAME:
            flash(f"Username must be {MAX_USERNAME} characters or fewer.")
        elif len(f["password"]) < 6:
            flash("Password must be at least 6 characters.")
        elif f["password"] != f["confirm"]:
            flash("Passwords do not match.")
        else:
            try:
                execute("INSERT INTO staff_login (username, password_hash) VALUES (%s,%s)",
                        (u, generate_password_hash(f["password"])))
                flash("Account created. Please log in.")
                return redirect(url_for("login"))
            except Error as e:
                flash(friendly(e))
    return render_template("auth.html", mode="register")

@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def home():
    return redirect(url_for("borrowers"))

# ------------------------------------------------------------------ BORROWERS
@app.route("/borrowers", methods=["GET", "POST"])
def borrowers():
    if request.method == "POST":                       # INSERT (4 tables, 1 transaction)
        f = request.form
        err = borrower_error(f)
        if err:
            flash(err)
            return redirect(url_for("borrowers"))
        conn = connect()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO borrower (full_name, dob) VALUES (%s,%s)",
                        (f["full_name"].strip(), f["dob"]))
            bid = cur.lastrowid
            cur.execute("INSERT INTO borrower_phone (borrower_id, phone) VALUES (%s,%s)",
                        (bid, f["phone"].strip()))
            if f["email"].strip():
                cur.execute("INSERT INTO borrower_email (borrower_id, email) VALUES (%s,%s)",
                            (bid, f["email"].strip()))
            cur.execute("INSERT INTO borrower_address (borrower_id, line1, pincode) "
                        "VALUES (%s,%s,%s)", (bid, f["line1"].strip(), f["pincode"]))
            conn.commit()
            flash(f"Borrower added (ID {bid}).")
        except Error as e:
            conn.rollback()
            flash(friendly(e))
        finally:
            conn.close()
        return redirect(url_for("borrowers"))

    q = request.args.get("q", "")                      # SELECT with search
    rows = query("""
        SELECT b.borrower_id, b.full_name, b.dob,
          (SELECT GROUP_CONCAT(phone SEPARATOR ', ') FROM borrower_phone
            WHERE borrower_id = b.borrower_id) AS phones,
          (SELECT GROUP_CONCAT(email SEPARATOR ', ') FROM borrower_email
            WHERE borrower_id = b.borrower_id) AS emails,
          (SELECT CONCAT(a.line1, ', ', pa.city) FROM borrower_address a
             JOIN postal_area pa ON pa.pincode = a.pincode
            WHERE a.borrower_id = b.borrower_id LIMIT 1) AS address
        FROM borrower b
        WHERE b.full_name LIKE %s OR b.borrower_id IN
              (SELECT borrower_id FROM borrower_phone WHERE phone LIKE %s)
        ORDER BY b.borrower_id DESC""", (f"%{q}%", f"%{q}%"))
    areas = query("SELECT * FROM postal_area ORDER BY city")
    return render_template("borrowers.html", rows=rows, areas=areas, q=q)

@app.route("/borrowers/<int:bid>/edit", methods=["GET", "POST"])
def edit_borrower(bid):
    if request.method == "POST":                       # UPDATE
        f = request.form
        err = borrower_error(f, check_phone=False)
        if err:
            flash(err)
            return redirect(url_for("edit_borrower", bid=bid))
        try:
            run_tx([
                ("UPDATE borrower SET full_name=%s, dob=%s WHERE borrower_id=%s",
                 (f["full_name"].strip(), f["dob"], bid)),
                ("UPDATE borrower_address SET line1=%s, pincode=%s WHERE borrower_id=%s",
                 (f["line1"].strip(), f["pincode"], bid)),
            ])
            flash("Borrower updated.")
        except Error as e:
            flash(friendly(e))
        return redirect(url_for("borrowers"))

    b = query("""SELECT b.*, a.line1, a.pincode FROM borrower b
                 LEFT JOIN borrower_address a ON a.borrower_id = b.borrower_id
                 WHERE b.borrower_id = %s""", (bid,))
    if not b:
        abort(404)
    phones = query("SELECT phone AS value FROM borrower_phone WHERE borrower_id=%s", (bid,))
    emails = query("SELECT email AS value FROM borrower_email WHERE borrower_id=%s", (bid,))
    areas = query("SELECT * FROM postal_area ORDER BY city")
    return render_template("edit_borrower.html", b=b[0], phones=phones,
                           emails=emails, areas=areas)

CONTACT = {"phone": ("borrower_phone", "phone"), "email": ("borrower_email", "email")}

@app.post("/borrowers/<int:bid>/contact/<kind>/add")
def contact_add(bid, kind):
    if kind not in CONTACT:
        abort(404)
    table, col = CONTACT[kind]                         # whitelisted, so safe in the f-string
    value = request.form["value"].strip()
    if kind == "phone" and not PHONE_RE.fullmatch(value):
        flash("Phone must be exactly 10 digits.")
    elif kind == "email" and len(value) > MAX_EMAIL:
        flash(f"Email must be {MAX_EMAIL} characters or fewer.")
    elif kind == "email" and not EMAIL_RE.fullmatch(value):
        flash("Enter a valid email address.")
    else:
        try:
            execute(f"INSERT INTO {table} (borrower_id, {col}) VALUES (%s,%s)", (bid, value))
            flash(f"{kind.capitalize()} added.")
        except Error as e:
            flash(friendly(e))
    return redirect(url_for("edit_borrower", bid=bid))

@app.post("/borrowers/<int:bid>/contact/<kind>/delete")
def contact_delete(bid, kind):
    if kind not in CONTACT:
        abort(404)
    table, col = CONTACT[kind]
    if kind == "phone":
        n = query("SELECT COUNT(*) AS n FROM borrower_phone WHERE borrower_id=%s", (bid,))[0]["n"]
        if n <= 1:
            flash("A borrower must keep at least one phone number.")
            return redirect(url_for("edit_borrower", bid=bid))
    try:
        execute(f"DELETE FROM {table} WHERE borrower_id=%s AND {col}=%s",
                (bid, request.form["value"]))
        flash(f"{kind.capitalize()} removed.")
    except Error as e:
        flash(friendly(e))
    return redirect(url_for("edit_borrower", bid=bid))

@app.post("/borrowers/<int:bid>/delete")               # DELETE
def delete_borrower(bid):
    try:
        execute("DELETE FROM borrower WHERE borrower_id=%s", (bid,))
        flash("Borrower deleted.")
    except Error as e:
        if e.errno == 1451 or "parent row" in (e.msg or "").lower():
            flash("Cannot delete: this borrower has loans.")
        else:
            flash(friendly(e))
    return redirect(url_for("borrowers"))

# ------------------------------------------------------------------ LOANS
LOAN_SELECT = """
    SELECT l.loan_id, l.principal, l.annual_rate_pct, l.tenure_months, l.start_date, l.status,
           b.full_name AS borrower, o.name AS officer, br.name AS branch, p.name AS product
    FROM loan l
    JOIN borrower b      ON b.borrower_id = l.borrower_id
    JOIN officer o       ON o.officer_id  = l.officer_id
    JOIN branch br       ON br.branch_id  = l.branch_id
    JOIN loan_product p  ON p.product_id  = l.product_id"""

@app.route("/loans", methods=["GET", "POST"])
def loans():
    if request.method == "POST":
        f = request.form
        if not all(f.get(k) for k in ("borrower_id", "officer_id", "branch_id", "product_id")):
            flash("Choose a borrower, officer, branch and loan product.")
            return redirect(url_for("loans"))
        try:
            principal = Decimal(f["principal"].strip())
            rate = Decimal(f["rate"].strip())
            tenure = int(f["tenure"].strip())
            date.fromisoformat(f["start_date"])
        except (InvalidOperation, ValueError):
            flash("Enter valid numbers for principal, rate and tenure, and a valid start date.")
            return redirect(url_for("loans"))

        problems = loan_problems(f, principal, rate, tenure)
        if problems:
            for p in problems:
                flash(p)
            return redirect(url_for("loans"))

        try:
            execute("""INSERT INTO loan (borrower_id, officer_id, branch_id, product_id,
                         principal, annual_rate_pct, tenure_months, start_date)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (f["borrower_id"], f["officer_id"], f["branch_id"], f["product_id"],
                     principal, rate, tenure, f["start_date"]))
            flash("Loan application created.")
        except Error as e:
            flash(friendly(e))
        return redirect(url_for("loans"))

    rows = query(LOAN_SELECT + " ORDER BY l.loan_id DESC")
    return render_template(
        "loans.html", rows=rows,
        borrowers=query("SELECT borrower_id, full_name FROM borrower ORDER BY full_name"),
        officers=query("SELECT * FROM officer ORDER BY name"),
        branches=query("SELECT * FROM branch ORDER BY name"),
        products=query("SELECT * FROM loan_product ORDER BY name"))

@app.post("/loans/<int:lid>/approve")
def approve(lid):
    try:                       # the trigger on loan builds the EMI schedule
        n = execute("UPDATE loan SET status='ACTIVE' WHERE loan_id=%s AND status='APPLIED'", (lid,))
        flash("Loan approved and EMI schedule generated." if n else "Loan is not awaiting approval.")
    except Error as e:
        flash(friendly(e))
    return redirect(url_for("loan_detail", lid=lid))

@app.post("/loans/<int:lid>/delete")
def delete_loan(lid):
    try:
        n = execute("DELETE FROM loan WHERE loan_id=%s AND status='APPLIED'", (lid,))
        flash("Loan application deleted." if n else "Only applications can be deleted.")
    except Error as e:
        flash(friendly(e))
    return redirect(url_for("loans"))

@app.route("/loans/<int:lid>")
def loan_detail(lid):
    loan = query(LOAN_SELECT + " WHERE l.loan_id = %s", (lid,))
    if not loan:
        abort(404)
    rows = query("SELECT * FROM v_installment_status WHERE loan_id=%s ORDER BY seq_no", (lid,))
    out = query("SELECT outstanding_principal FROM v_loan_outstanding WHERE loan_id=%s", (lid,))
    return render_template("loan_detail.html", loan=loan[0], rows=rows,
                           outstanding=out[0]["outstanding_principal"] if out else None)

@app.post("/installments/<int:iid>/pay")
def pay(iid):
    lid = request.form["loan_id"]
    back = redirect(url_for("loan_detail", lid=lid))

    try:
        amount = Decimal(request.form["amount"].strip()).quantize(Decimal("0.01"))
    except InvalidOperation:
        flash("Enter a valid payment amount.")
        return back
    if not amount.is_finite() or amount <= 0:
        flash("Payment amount must be greater than zero.")
        return back

    ref = (request.form.get("ref") or "").strip() or None
    if ref and len(ref) > MAX_REF:
        flash(f"Payment reference must be {MAX_REF} characters or fewer.")
        return back

    # Same checks record_payment() makes, but with the actual figures in the message
    row = query("""SELECT v.status, v.total_due - v.total_paid AS remaining, l.status AS loan_status
                   FROM v_installment_status v JOIN loan l ON l.loan_id = v.loan_id
                   WHERE v.installment_id = %s""", (iid,))
    if not row:
        flash("That installment no longer exists.")
        return back
    r = row[0]
    if r["loan_status"] != "ACTIVE":
        flash("Payments can only be recorded on active loans.")
        return back
    if r["status"] == "PAID":
        flash("This installment is already fully paid.")
        return back
    if amount > r["remaining"]:
        flash(f"Amount is more than the {money(r['remaining'])} still due on this installment.")
        return back

    conn = connect()
    try:                       # stored procedure does the validation + allocation
        cur = conn.cursor()
        cur.callproc("record_payment", (iid, amount, request.form["mode"], ref))
        conn.commit()
        flash(f"Payment of {money(amount)} recorded.")
    except Error as e:
        conn.rollback()
        flash(friendly(e))
    finally:
        conn.close()
    return back

# ------------------------------------------------------------------ REPORTS
@app.route("/reports")
def reports():
    sections = [
        ("Overdue installments", query("""
            SELECT b.full_name AS borrower, v.loan_id, v.seq_no AS emi_no, v.due_date,
                   v.total_due - v.total_paid AS balance
            FROM v_installment_status v
            JOIN loan l ON l.loan_id = v.loan_id
            JOIN borrower b ON b.borrower_id = l.borrower_id
            WHERE v.status = 'OVERDUE' ORDER BY v.due_date""")),
        ("Outstanding principal per loan", query("""
            SELECT l.loan_id, b.full_name AS borrower, o.outstanding_principal
            FROM v_loan_outstanding o
            JOIN loan l ON l.loan_id = o.loan_id
            JOIN borrower b ON b.borrower_id = l.borrower_id
            WHERE l.status = 'ACTIVE'""")),
        ("Monthly collections", query("""
            SELECT DATE_FORMAT(paid_at, '%Y-%m') AS month, COUNT(*) AS payments,
                   SUM(amount) AS collected
            FROM payment WHERE status = 'SUCCESS' GROUP BY month ORDER BY month""")),
        ("Loans per officer", query("""
            SELECT o.name AS officer, COUNT(l.loan_id) AS loans,
                   COALESCE(SUM(l.principal), 0) AS total_principal
            FROM officer o LEFT JOIN loan l ON l.officer_id = o.officer_id
            GROUP BY o.officer_id, o.name""")),
        ("Allowed officer / branch / product combinations", query("""
            SELECT o.name AS officer, br.name AS branch, p.name AS product
            FROM officer_branch ob
            JOIN branch_product bp  ON bp.branch_id = ob.branch_id
            JOIN officer_product op ON op.officer_id = ob.officer_id
                                   AND op.product_id = bp.product_id
            JOIN officer o ON o.officer_id = ob.officer_id
            JOIN branch br ON br.branch_id = ob.branch_id
            JOIN loan_product p ON p.product_id = bp.product_id
            ORDER BY o.name, br.name""")),
    ]
    return render_template("reports.html", sections=sections)

if __name__ == "__main__":
    app.run(debug=True)