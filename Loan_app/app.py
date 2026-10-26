import os
from datetime import date
from decimal import Decimal, InvalidOperation

import mysql.connector
from mysql.connector import Error
from flask import Flask, render_template, request, redirect, url_for, flash, abort

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-key")

DB = dict(
    host=os.environ.get("DB_HOST", "localhost"),
    user=os.environ.get("DB_USER", "loan_app"),
    password=os.environ.get("DB_PASSWORD", "star"),
    database="loan_mang",
)

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

def friendly(e):
    """Turn MySQL errors into readable messages."""
    if e.errno == 1452:
        return ("Not allowed: the officer must work at the branch, the branch must offer "
                "the product, and the officer must be certified for the product.")
    if e.errno == 1451:
        return "Cannot delete: other records depend on this one."
    if e.errno == 1062:
        return "That value already exists."
    if e.errno == 3819:
        return "A value breaks a rule (for example, amounts must be positive)."
    return e.msg          # includes messages raised by our triggers/procedures

def borrower_error(f, check_phone=True):
    if not f["full_name"].strip():
        return "Name is required."
    try:
        dob = date.fromisoformat(f["dob"])
    except ValueError:
        return "Enter a valid date of birth."
    if (date.today() - dob).days < 18 * 365:
        return "Borrower must be at least 18 years old."
    if check_phone and not (f["phone"].isdigit() and len(f["phone"]) == 10):
        return "Phone must be exactly 10 digits."
    return None

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
                        (bid, f["phone"]))
            if f["email"].strip():
                cur.execute("INSERT INTO borrower_email (borrower_id, email) VALUES (%s,%s)",
                            (bid, f["email"].strip()))
            cur.execute("INSERT INTO borrower_address (borrower_id, line1, pincode) "
                        "VALUES (%s,%s,%s)", (bid, f["line1"], f["pincode"]))
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
                 (f["line1"], f["pincode"], bid)),
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
    if kind == "phone" and not (value.isdigit() and len(value) == 10):
        flash("Phone must be exactly 10 digits.")
    elif kind == "email" and "@" not in value:
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
    execute(f"DELETE FROM {table} WHERE borrower_id=%s AND {col}=%s",
            (bid, request.form["value"]))
    flash(f"{kind.capitalize()} removed.")
    return redirect(url_for("edit_borrower", bid=bid))

@app.post("/borrowers/<int:bid>/delete")               # DELETE
def delete_borrower(bid):
    try:
        execute("DELETE FROM borrower WHERE borrower_id=%s", (bid,))
        flash("Borrower deleted.")
    except Error as e:
        flash("Cannot delete: this borrower has loans." if e.errno == 1451 else friendly(e))
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
        try:
            principal = Decimal(f["principal"])
            rate = Decimal(f["rate"])
            tenure = int(f["tenure"])
            date.fromisoformat(f["start_date"])
            if principal <= 0 or rate <= 0 or tenure <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            flash("Principal, rate and tenure must be positive numbers, and the date valid.")
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
    try:
        amount = Decimal(request.form["amount"])
    except InvalidOperation:
        flash("Enter a valid amount.")
        return redirect(url_for("loan_detail", lid=lid))
    conn = connect()
    try:                       # stored procedure does the validation + allocation
        cur = conn.cursor()
        cur.callproc("record_payment",
                     (iid, amount, request.form["mode"], request.form.get("ref") or None))
        conn.commit()
        flash("Payment recorded.")
    except Error as e:
        conn.rollback()
        flash(friendly(e))
    finally:
        conn.close()
    return redirect(url_for("loan_detail", lid=lid))

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