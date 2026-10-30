import os
import json
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)

from models import (
    db, User, ShopSettings, Category, Material, Bill, BillItem,
    ROLE_OWNER, ROLE_BILLER, ROLE_CUSTOMER,
    ITEM_ONGOING, ITEM_RETURNED, ITEM_CANCELLED,
)

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-secret-key-for-production"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(basedir, "shop.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------- helpers ----------

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("login"))
            if current_user.role not in roles:
                flash("You don't have access to that page.", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return wrapped
    return decorator


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def get_shop():
    shop = ShopSettings.query.first()
    if not shop:
        shop = ShopSettings()
        db.session.add(shop)
        db.session.commit()
    return shop


@app.context_processor
def inject_shop():
    return {"shop": get_shop()}


def get_or_create_customer(name, phone, email):
    phone = (phone or "").strip() or None
    email = (email or "").strip().lower() or None
    customer = None
    if phone:
        customer = User.query.filter_by(phone=phone, role=ROLE_CUSTOMER).first()
    if not customer and email:
        customer = User.query.filter_by(email=email, role=ROLE_CUSTOMER).first()
    if customer:
        if name and not customer.name:
            customer.name = name
        if email and not customer.email:
            customer.email = email
        if phone and not customer.phone:
            customer.phone = phone
        return customer
    customer = User(name=name or "Walk-in Customer", phone=phone, email=email, role=ROLE_CUSTOMER,
                     is_active_account=True, has_login=False)
    db.session.add(customer)
    db.session.flush()
    return customer


# ---------- public ----------

@app.route("/")
def index():
    categories = Category.query.all()
    featured = Material.query.filter_by(is_active=True).order_by(Material.created_at.desc()).limit(6).all()
    return render_template("index.html", categories=categories, featured=featured)


@app.route("/catalog")
def catalog():
    q = request.args.get("q", "").strip()
    category_id = request.args.get("category", type=int)
    query = Material.query.filter_by(is_active=True)
    if q:
        query = query.filter(Material.name.ilike(f"%{q}%"))
    if category_id:
        query = query.filter_by(category_id=category_id)
    materials = query.order_by(Material.name).all()
    categories = Category.query.all()
    return render_template("catalog.html", materials=materials, categories=categories, q=q, category_id=category_id)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()
        if user and user.has_login and user.check_password(password) and user.is_active_account:
            login_user(user)
            flash(f"Welcome back, {user.name}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Customer self-registration. If a walk-in profile already exists
    (created by a biller) with the same phone, this 'claims' that profile
    so bill history carries over."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form["password"]
        address = request.form.get("address", "").strip()

        existing_login = User.query.filter_by(email=email).first()
        if existing_login and existing_login.has_login:
            flash("An account with that email already exists. Please log in.", "danger")
            return redirect(url_for("register"))

        claimed = None
        if phone:
            claimed = User.query.filter_by(phone=phone, role=ROLE_CUSTOMER).first()

        if claimed:
            claimed.name = name or claimed.name
            claimed.email = email
            claimed.address = address or claimed.address
            claimed.set_password(password)
            db.session.commit()
            flash("Welcome! We found your past rentals with us and linked them to your new account.", "success")
        else:
            user = User(name=name, email=email, phone=phone or None, address=address, role=ROLE_CUSTOMER,
                        is_active_account=True)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("Account created! Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role == ROLE_OWNER:
        return redirect(url_for("owner_dashboard"))
    if current_user.role == ROLE_BILLER:
        return redirect(url_for("biller_dashboard"))
    return redirect(url_for("customer_dashboard"))


# ---------- customer (read-only) ----------

@app.route("/customer/dashboard")
@role_required(ROLE_CUSTOMER)
def customer_dashboard():
    bills = Bill.query.filter_by(customer_id=current_user.id).order_by(Bill.created_at.desc()).all()
    active_count = sum(1 for b in bills if b.status == ITEM_ONGOING)
    return render_template("customer/dashboard.html", bills=bills[:5], active_count=active_count,
                            total_bills=len(bills))


@app.route("/customer/bills")
@role_required(ROLE_CUSTOMER)
def customer_bills():
    bills = Bill.query.filter_by(customer_id=current_user.id).order_by(Bill.created_at.desc()).all()
    return render_template("customer/bills.html", bills=bills)


@app.route("/customer/bills/<int:bill_id>")
@role_required(ROLE_CUSTOMER)
def customer_bill_invoice(bill_id):
    bill = db.session.get(Bill, bill_id)
    if not bill or bill.customer_id != current_user.id:
        flash("Bill not found.", "danger")
        return redirect(url_for("customer_bills"))
    return render_template("invoice.html", bill=bill)


# ---------- shared: billing (owner + biller) ----------

@app.route("/bills")
@role_required(ROLE_OWNER, ROLE_BILLER)
def bills_list():
    q = request.args.get("q", "").strip()
    query = Bill.query
    if q:
        query = query.join(User, Bill.customer_id == User.id).filter(
            (User.name.ilike(f"%{q}%")) | (User.phone.ilike(f"%{q}%"))
        )
    bills = query.order_by(Bill.created_at.desc()).all()
    return render_template("shared/bills.html", bills=bills, q=q)


@app.route("/bills/<int:bill_id>")
@role_required(ROLE_OWNER, ROLE_BILLER)
def bill_detail(bill_id):
    bill = db.session.get(Bill, bill_id)
    if not bill:
        flash("Bill not found.", "danger")
        return redirect(url_for("bills_list"))
    return render_template("invoice.html", bill=bill, staff_view=True)


@app.route("/bills/new", methods=["GET", "POST"])
@role_required(ROLE_OWNER, ROLE_BILLER)
def new_bill():
    materials = Material.query.filter_by(is_active=True).filter(Material.quantity_available > 0).order_by(Material.name).all()
    customers = User.query.filter_by(role=ROLE_CUSTOMER).order_by(User.name).all()

    if request.method == "POST":
        cust_name = request.form.get("customer_name", "").strip()
        cust_phone = request.form.get("customer_phone", "").strip()
        cust_email = request.form.get("customer_email", "").strip()
        cart_raw = request.form.get("cart_json", "[]")

        try:
            cart = json.loads(cart_raw)
        except (ValueError, TypeError):
            cart = []

        if not cust_name or not cust_phone:
            flash("Customer name and phone are required.", "danger")
            return render_template("shared/new_bill.html", materials=materials, customers=customers)

        if not cart:
            flash("Add at least one item to the bill.", "danger")
            return render_template("shared/new_bill.html", materials=materials, customers=customers)

        customer = get_or_create_customer(cust_name, cust_phone, cust_email)
        bill = Bill(customer_id=customer.id, biller_id=current_user.id)
        db.session.add(bill)
        db.session.flush()

        errors = []
        for row in cart:
            material = db.session.get(Material, int(row.get("material_id", 0)))
            if not material:
                continue
            try:
                qty = int(row.get("quantity", 1))
                start = parse_date(row["start_date"])
                end = parse_date(row["end_date"])
            except (ValueError, KeyError):
                continue
            if end <= start:
                errors.append(f"{material.name}: end date must be after start date.")
                continue
            if qty < 1 or qty > material.quantity_available:
                errors.append(f"{material.name}: only {material.quantity_available} unit(s) available.")
                continue

            item = BillItem(
                bill_id=bill.id, material_id=material.id, quantity=qty,
                start_date=start, end_date=end,
                rate_per_day=material.price_per_day, deposit_per_unit=material.deposit_amount,
                status=ITEM_ONGOING,
            )
            material.quantity_available -= qty
            db.session.add(item)

        if not bill.items:
            db.session.rollback()
            flash("Couldn't create the bill — " + (" ".join(errors) or "no valid items."), "danger")
            return render_template("shared/new_bill.html", materials=materials, customers=customers)

        db.session.commit()
        if errors:
            flash("Bill created, but some items were skipped: " + " ".join(errors), "warning")
        else:
            flash("Bill created successfully!", "success")
        return redirect(url_for("bill_detail", bill_id=bill.id))

    return render_template("shared/new_bill.html", materials=materials, customers=customers)


@app.route("/bills/<int:bill_id>/items/<int:item_id>/return", methods=["POST"])
@role_required(ROLE_OWNER, ROLE_BILLER)
def return_item(bill_id, item_id):
    item = db.session.get(BillItem, item_id)
    if not item or item.bill_id != bill_id:
        flash("Item not found.", "danger")
        return redirect(url_for("bill_detail", bill_id=bill_id))
    if item.status != ITEM_ONGOING:
        flash("This item is not currently out on rent.", "warning")
        return redirect(url_for("bill_detail", bill_id=bill_id))

    item.actual_return_date = date.today()
    if item.actual_return_date > item.end_date:
        late_days = (item.actual_return_date - item.end_date).days
        item.late_fee = late_days * item.rate_per_day * item.quantity
    item.status = ITEM_RETURNED
    item.material.quantity_available += item.quantity
    db.session.commit()
    flash(f"{item.material.name} marked as returned.", "success")
    return redirect(url_for("bill_detail", bill_id=bill_id))


@app.route("/bills/<int:bill_id>/items/<int:item_id>/cancel", methods=["POST"])
@role_required(ROLE_OWNER, ROLE_BILLER)
def cancel_item(bill_id, item_id):
    item = db.session.get(BillItem, item_id)
    if not item or item.bill_id != bill_id:
        flash("Item not found.", "danger")
        return redirect(url_for("bill_detail", bill_id=bill_id))
    if item.status != ITEM_ONGOING:
        flash("Only ongoing items can be voided.", "warning")
        return redirect(url_for("bill_detail", bill_id=bill_id))
    item.status = ITEM_CANCELLED
    item.material.quantity_available += item.quantity
    db.session.commit()
    flash(f"{item.material.name} voided from bill.", "info")
    return redirect(url_for("bill_detail", bill_id=bill_id))


@app.route("/active-rentals")
@role_required(ROLE_OWNER, ROLE_BILLER)
def active_rentals():
    items = BillItem.query.filter_by(status=ITEM_ONGOING).order_by(BillItem.end_date.asc()).all()
    return render_template("shared/active_rentals.html", items=items)


@app.route("/customers")
@role_required(ROLE_OWNER, ROLE_BILLER)
def customers_list():
    q = request.args.get("q", "").strip()
    query = User.query.filter_by(role=ROLE_CUSTOMER)
    if q:
        query = query.filter((User.name.ilike(f"%{q}%")) | (User.phone.ilike(f"%{q}%")))
    customers = query.order_by(User.name).all()
    return render_template("shared/customers.html", customers=customers, q=q)


# ---------- biller ----------

@app.route("/biller/dashboard")
@role_required(ROLE_BILLER)
def biller_dashboard():
    today = date.today()
    todays_bills = Bill.query.filter(db.func.date(Bill.created_at) == today, Bill.biller_id == current_user.id).all()
    todays_revenue = sum(b.subtotal for b in todays_bills)
    active_count = BillItem.query.filter_by(status=ITEM_ONGOING).count()
    overdue_count = sum(1 for i in BillItem.query.filter_by(status=ITEM_ONGOING).all() if i.is_overdue)
    recent_bills = Bill.query.order_by(Bill.created_at.desc()).limit(5).all()
    return render_template("biller/dashboard.html", todays_count=len(todays_bills), todays_revenue=todays_revenue,
                            active_count=active_count, overdue_count=overdue_count, recent_bills=recent_bills)


# ---------- owner ----------

@app.route("/owner/dashboard")
@role_required(ROLE_OWNER)
def owner_dashboard():
    all_items = BillItem.query.all()
    stats = {
        "total_materials": Material.query.count(),
        "total_bills": Bill.query.count(),
        "total_customers": User.query.filter_by(role=ROLE_CUSTOMER).count(),
        "total_billers": User.query.filter_by(role=ROLE_BILLER).count(),
        "active_rentals": sum(1 for i in all_items if i.status == ITEM_ONGOING),
        "overdue": sum(1 for i in all_items if i.is_overdue),
        "total_revenue": sum(i.subtotal for i in all_items if i.status != ITEM_CANCELLED),
        "low_stock": Material.query.filter_by(is_active=True).all(),
    }
    stats["low_stock"] = [m for m in stats["low_stock"] if m.low_stock]

    status_labels = [ITEM_ONGOING, ITEM_RETURNED, ITEM_CANCELLED]
    status_counts = [sum(1 for i in all_items if i.status == s) for s in status_labels]

    category_labels, category_counts, category_revenue = [], [], []
    for c in Category.query.all():
        category_labels.append(c.name)
        category_counts.append(Material.query.filter_by(category_id=c.id).count())
        rev = sum(i.subtotal for i in all_items if i.status != ITEM_CANCELLED and i.material.category_id == c.id)
        category_revenue.append(round(rev, 2))

    chart_data = {
        "status_labels": status_labels, "status_counts": status_counts,
        "category_labels": category_labels, "category_counts": category_counts,
        "category_revenue": category_revenue,
    }
    recent_bills = Bill.query.order_by(Bill.created_at.desc()).limit(6).all()
    return render_template("owner/dashboard.html", stats=stats, chart_data=chart_data, recent_bills=recent_bills)


@app.route("/inventory")
@role_required(ROLE_OWNER)
def inventory():
    materials = Material.query.order_by(Material.created_at.desc()).all()
    return render_template("owner/inventory.html", materials=materials)


@app.route("/inventory/add", methods=["GET", "POST"])
@role_required(ROLE_OWNER)
def add_material():
    categories = Category.query.all()
    if not categories:
        flash("Create a category first.", "warning")
        return redirect(url_for("categories_page"))
    if request.method == "POST":
        material = Material(
            category_id=int(request.form["category_id"]),
            name=request.form["name"].strip(),
            description=request.form.get("description", "").strip(),
            price_per_day=float(request.form["price_per_day"]),
            deposit_amount=float(request.form.get("deposit_amount") or 0),
            quantity_total=int(request.form["quantity_total"]),
            quantity_available=int(request.form["quantity_total"]),
            image_emoji=request.form.get("image_emoji", "🧱"),
        )
        db.session.add(material)
        db.session.commit()
        flash("Material added to inventory.", "success")
        return redirect(url_for("inventory"))
    return render_template("owner/material_form.html", categories=categories, material=None)


@app.route("/inventory/<int:material_id>/edit", methods=["GET", "POST"])
@role_required(ROLE_OWNER)
def edit_material(material_id):
    material = db.session.get(Material, material_id)
    if not material:
        flash("Material not found.", "danger")
        return redirect(url_for("inventory"))
    categories = Category.query.all()
    if request.method == "POST":
        old_total = material.quantity_total
        new_total = int(request.form["quantity_total"])
        diff = new_total - old_total

        material.category_id = int(request.form["category_id"])
        material.name = request.form["name"].strip()
        material.description = request.form.get("description", "").strip()
        material.price_per_day = float(request.form["price_per_day"])
        material.deposit_amount = float(request.form.get("deposit_amount") or 0)
        material.quantity_total = new_total
        material.quantity_available = max(material.quantity_available + diff, 0)
        material.image_emoji = request.form.get("image_emoji", material.image_emoji)
        material.is_active = "is_active" in request.form
        db.session.commit()
        flash("Material updated.", "success")
        return redirect(url_for("inventory"))
    return render_template("owner/material_form.html", categories=categories, material=material)


@app.route("/inventory/<int:material_id>/delete", methods=["POST"])
@role_required(ROLE_OWNER)
def delete_material(material_id):
    material = db.session.get(Material, material_id)
    if material:
        if BillItem.query.filter_by(material_id=material.id).first():
            material.is_active = False
            db.session.commit()
            flash("Material has billing history, so it was deactivated instead of deleted.", "info")
        else:
            db.session.delete(material)
            db.session.commit()
            flash("Material deleted.", "info")
    return redirect(url_for("inventory"))


@app.route("/categories", methods=["GET", "POST"])
@role_required(ROLE_OWNER)
def categories_page():
    if request.method == "POST":
        name = request.form["name"].strip()
        icon = request.form.get("icon", "🧰").strip() or "🧰"
        if name and not Category.query.filter_by(name=name).first():
            db.session.add(Category(name=name, icon=icon))
            db.session.commit()
            flash("Category added.", "success")
        else:
            flash("Category already exists or invalid name.", "danger")
        return redirect(url_for("categories_page"))
    categories = Category.query.all()
    return render_template("owner/categories.html", categories=categories)


@app.route("/categories/<int:cat_id>/delete", methods=["POST"])
@role_required(ROLE_OWNER)
def delete_category(cat_id):
    cat = db.session.get(Category, cat_id)
    if cat and not cat.materials:
        db.session.delete(cat)
        db.session.commit()
        flash("Category deleted.", "info")
    elif cat:
        flash("Cannot delete a category that has materials.", "danger")
    return redirect(url_for("categories_page"))


@app.route("/staff", methods=["GET", "POST"])
@role_required(ROLE_OWNER)
def staff_page():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        phone = request.form.get("phone", "").strip()
        if User.query.filter_by(email=email).first():
            flash("A user with that email already exists.", "danger")
        else:
            biller = User(name=name, email=email, phone=phone or None, role=ROLE_BILLER, is_active_account=True)
            biller.set_password(password)
            db.session.add(biller)
            db.session.commit()
            flash(f"Biller account created for {name}.", "success")
        return redirect(url_for("staff_page"))
    billers = User.query.filter_by(role=ROLE_BILLER).order_by(User.created_at.desc()).all()
    return render_template("owner/staff.html", billers=billers)


@app.route("/staff/<int:user_id>/toggle", methods=["POST"])
@role_required(ROLE_OWNER)
def toggle_staff(user_id):
    user = db.session.get(User, user_id)
    if user and user.role == ROLE_BILLER:
        user.is_active_account = not user.is_active_account
        db.session.commit()
        flash(f"{user.name} {'activated' if user.is_active_account else 'suspended'}.", "info")
    return redirect(url_for("staff_page"))


@app.route("/settings", methods=["GET", "POST"])
@role_required(ROLE_OWNER)
def settings_page():
    shop = get_shop()
    if request.method == "POST":
        shop.shop_name = request.form.get("shop_name", shop.shop_name).strip()
        shop.tagline = request.form.get("tagline", shop.tagline).strip()
        shop.address = request.form.get("address", shop.address).strip()
        shop.phone = request.form.get("phone", shop.phone).strip()
        shop.gst_no = request.form.get("gst_no", shop.gst_no).strip()
        db.session.commit()
        flash("Shop settings updated.", "success")
        return redirect(url_for("settings_page"))
    return render_template("owner/settings.html", shop=shop)


# ---------- seed data ----------

def seed_data():
    db.create_all()
    get_shop()

    if not User.query.filter_by(email="owner@shop.com").first():
        owner = User(name="Rajesh Patil", email="owner@shop.com", role=ROLE_OWNER, is_active_account=True)
        owner.set_password("owner123")
        db.session.add(owner)

    if not User.query.filter_by(email="biller@shop.com").first():
        biller = User(name="Sneha Kale", email="biller@shop.com", role=ROLE_BILLER, is_active_account=True)
        biller.set_password("biller123")
        db.session.add(biller)

    if Category.query.count() == 0:
        cats = [
            Category(name="Hand Tools", icon="🔨"),
            Category(name="Scaffolding & Support", icon="🪜"),
            Category(name="Mixing & Small Machines", icon="⚙️"),
            Category(name="Power & Electrical Tools", icon="🔌"),
            Category(name="Heavy Machinery", icon="🚜"),
            Category(name="Safety & Others", icon="🧰"),
        ]
        db.session.add_all(cats)
    db.session.commit()

    if Material.query.count() == 0:
        hand_tools = Category.query.filter_by(name="Hand Tools").first()
        scaffolding = Category.query.filter_by(name="Scaffolding & Support").first()
        small_machines = Category.query.filter_by(name="Mixing & Small Machines").first()
        power_tools = Category.query.filter_by(name="Power & Electrical Tools").first()
        heavy = Category.query.filter_by(name="Heavy Machinery").first()
        safety = Category.query.filter_by(name="Safety & Others").first()

        samples = [
            # ---- Hand Tools ----
            Material(category_id=hand_tools.id, name="Bamboo (Set of 10)",
                     description="Sturdy bamboo poles for scaffolding support.",
                     price_per_day=50, deposit_amount=500, quantity_total=40, quantity_available=40, image_emoji="🎍"),
            Material(category_id=hand_tools.id, name="Hatodi (Hammer)",
                     description="Standard construction hammer.",
                     price_per_day=20, deposit_amount=100, quantity_total=25, quantity_available=25, image_emoji="🔨"),
            Material(category_id=hand_tools.id, name="Khora (Spade/Shovel)",
                     description="Heavy duty digging spade.",
                     price_per_day=25, deposit_amount=150, quantity_total=30, quantity_available=30, image_emoji="⛏️"),
            Material(category_id=hand_tools.id, name="Phawada (Pickaxe)",
                     description="Standard pickaxe for breaking hard ground.",
                     price_per_day=25, deposit_amount=150, quantity_total=20, quantity_available=20, image_emoji="⛏️"),
            Material(category_id=hand_tools.id, name="Wheelbarrow",
                     description="Single-wheel site barrow for moving debris & material.",
                     price_per_day=60, deposit_amount=400, quantity_total=15, quantity_available=15, image_emoji="🛒"),
            Material(category_id=hand_tools.id, name="Measuring Tape (50m)",
                     description="Fibreglass long-tape for site layout & measurement.",
                     price_per_day=15, deposit_amount=100, quantity_total=12, quantity_available=12, image_emoji="📏"),

            # ---- Scaffolding & Support ----
            Material(category_id=scaffolding.id, name="Chalni (Sieve)",
                     description="Sand/aggregate sieving mesh.",
                     price_per_day=30, deposit_amount=200, quantity_total=20, quantity_available=20, image_emoji="🕸️"),
            Material(category_id=scaffolding.id, name="Steel Scaffolding Pipe (per piece)",
                     description="Standard MS scaffolding pipe, 2m length.",
                     price_per_day=15, deposit_amount=100, quantity_total=100, quantity_available=100, image_emoji="🪜"),
            Material(category_id=scaffolding.id, name="Aluminium Ladder (12 ft)",
                     description="Lightweight extendable ladder for site work.",
                     price_per_day=80, deposit_amount=500, quantity_total=10, quantity_available=10, image_emoji="🪜"),
            Material(category_id=scaffolding.id, name="Adjustable Steel Prop / Jack",
                     description="Height-adjustable support prop for slab shuttering.",
                     price_per_day=40, deposit_amount=300, quantity_total=25, quantity_available=25, image_emoji="🔩"),

            # ---- Mixing & Small Machines ----
            Material(category_id=small_machines.id, name="Concrete Grinder",
                     description="Electric surface grinder for concrete finishing.",
                     price_per_day=350, deposit_amount=2000, quantity_total=6, quantity_available=6, image_emoji="🪚"),
            Material(category_id=small_machines.id, name="Concrete Mixer (Small, 1 bag)",
                     description="Portable concrete mixer machine, 1 bag capacity.",
                     price_per_day=600, deposit_amount=3000, quantity_total=4, quantity_available=4, image_emoji="⚙️"),
            Material(category_id=small_machines.id, name="Concrete Mixer (Large, 2 bag)",
                     description="Higher-capacity mixer for bigger pours.",
                     price_per_day=900, deposit_amount=4000, quantity_total=3, quantity_available=3, image_emoji="⚙️"),
            Material(category_id=small_machines.id, name="Plate Compactor (Rammer)",
                     description="Vibratory plate compactor for soil & sub-base compaction.",
                     price_per_day=700, deposit_amount=3500, quantity_total=3, quantity_available=3, image_emoji="🧱"),
            Material(category_id=small_machines.id, name="Dewatering Water Pump",
                     description="Petrol/diesel pump for clearing waterlogged foundations.",
                     price_per_day=500, deposit_amount=2500, quantity_total=5, quantity_available=5, image_emoji="💧"),

            # ---- Power & Electrical Tools ----
            Material(category_id=power_tools.id, name="Angle Grinder (4 inch)",
                     description="Handheld grinder for cutting & finishing.",
                     price_per_day=150, deposit_amount=800, quantity_total=10, quantity_available=10, image_emoji="🔌"),
            Material(category_id=power_tools.id, name="Rotary Hammer Drill",
                     description="Heavy-duty drill for concrete & masonry.",
                     price_per_day=250, deposit_amount=1200, quantity_total=8, quantity_available=8, image_emoji="🛠️"),
            Material(category_id=power_tools.id, name="Welding Machine",
                     description="Arc welding machine for rebar & structural steel work.",
                     price_per_day=400, deposit_amount=2000, quantity_total=5, quantity_available=5, image_emoji="🔥"),
            Material(category_id=power_tools.id, name="Portable Generator (5 KVA)",
                     description="Backup power for sites without a stable connection.",
                     price_per_day=1200, deposit_amount=8000, quantity_total=3, quantity_available=3, image_emoji="🔋"),

            # ---- Heavy Machinery ----
            Material(category_id=heavy.id, name="JCB Excavator",
                     description="Backhoe loader for excavation work.",
                     price_per_day=6000, deposit_amount=25000, quantity_total=2, quantity_available=2, image_emoji="🚜"),
            Material(category_id=heavy.id, name="Tower Crane (Small)",
                     description="Small tower crane for material lifting on site.",
                     price_per_day=9000, deposit_amount=40000, quantity_total=1, quantity_available=1, image_emoji="🏗️"),
            Material(category_id=heavy.id, name="Vibro Roller (Road Roller)",
                     description="Compaction roller for road & sub-base work.",
                     price_per_day=5500, deposit_amount=20000, quantity_total=2, quantity_available=2, image_emoji="🚧"),
            Material(category_id=heavy.id, name="Mini Concrete Pump",
                     description="Trailer-mounted pump for placing concrete at height.",
                     price_per_day=4500, deposit_amount=18000, quantity_total=2, quantity_available=2, image_emoji="🚛"),

            # ---- Safety & Others ----
            Material(category_id=safety.id, name="Safety Helmet (Set of 10)",
                     description="ISI-marked site helmets.",
                     price_per_day=30, deposit_amount=200, quantity_total=15, quantity_available=15, image_emoji="⛑️"),
            Material(category_id=safety.id, name="Safety Harness",
                     description="Full-body harness for work at height.",
                     price_per_day=50, deposit_amount=300, quantity_total=12, quantity_available=12, image_emoji="🦺"),
        ]
        db.session.add_all(samples)
        db.session.commit()


def seed_dummy_bills():
    """Sample bills across several customers, statuses, and dates so the
    owner dashboard, charts, and bill history have real data to show."""
    if Bill.query.count() > 0:
        return

    biller = User.query.filter_by(email="biller@shop.com").first()
    owner = User.query.filter_by(email="owner@shop.com").first()

    def get_customer(name, phone):
        c = User.query.filter_by(phone=phone).first()
        if not c:
            c = User(name=name, phone=phone, role=ROLE_CUSTOMER, is_active_account=True, has_login=False)
            db.session.add(c)
            db.session.flush()
        return c

    ramesh = get_customer("Ramesh Walk-in", "9123456780")
    sunita = get_customer("Sunita Jadhav", "9988776655")
    amit = get_customer("Amit Deshmukh", "9876501234")
    priya = get_customer("Priya Shinde", "9765432100")
    ganesh = get_customer("Ganesh Pawar", "9654321098")
    mahesh = get_customer("Mahesh Kulkarni", "9543210987")
    sneha_w = get_customer("Sneha Wagh", "9432109876")

    def mat(name):
        return Material.query.filter_by(name=name).first()

    def make_bill(customer, biller_user, created_days_ago, items):
        bill = Bill(customer_id=customer.id, biller_id=biller_user.id,
                    created_at=datetime.utcnow() - timedelta(days=created_days_ago))
        db.session.add(bill)
        db.session.flush()
        for it in items:
            m = mat(it["material"])
            qty = it["qty"]
            start = date.today() - timedelta(days=it["start_days_ago"])
            end = date.today() - timedelta(days=it["end_days_ago"])
            status = it["status"]
            bi = BillItem(bill_id=bill.id, material_id=m.id, quantity=qty,
                          start_date=start, end_date=end,
                          rate_per_day=m.price_per_day, deposit_per_unit=m.deposit_amount,
                          status=status)
            if status == ITEM_ONGOING:
                m.quantity_available = max(m.quantity_available - qty, 0)
            elif status == ITEM_RETURNED:
                ret_offset = it.get("returned_days_ago", it["end_days_ago"])
                bi.actual_return_date = date.today() - timedelta(days=ret_offset)
                if bi.actual_return_date > end:
                    late_days = (bi.actual_return_date - end).days
                    bi.late_fee = late_days * m.price_per_day * qty
            db.session.add(bi)
        return bill

    # 1 — Ramesh: Bamboo + Chalni, returned on time
    make_bill(ramesh, biller, 18, [
        {"material": "Bamboo (Set of 10)", "qty": 2, "start_days_ago": 18, "end_days_ago": 15,
         "status": ITEM_RETURNED, "returned_days_ago": 15},
        {"material": "Chalni (Sieve)", "qty": 1, "start_days_ago": 18, "end_days_ago": 15,
         "status": ITEM_RETURNED, "returned_days_ago": 15},
    ])

    # 2 — Sunita: JCB Excavator, returned 2 days late (late fee applies)
    make_bill(sunita, owner, 15, [
        {"material": "JCB Excavator", "qty": 1, "start_days_ago": 15, "end_days_ago": 13,
         "status": ITEM_RETURNED, "returned_days_ago": 11},
    ])

    # 3 — Amit: Hatodi + Khora, returned on time
    make_bill(amit, biller, 12, [
        {"material": "Hatodi (Hammer)", "qty": 3, "start_days_ago": 12, "end_days_ago": 10,
         "status": ITEM_RETURNED, "returned_days_ago": 10},
        {"material": "Khora (Spade/Shovel)", "qty": 2, "start_days_ago": 12, "end_days_ago": 10,
         "status": ITEM_RETURNED, "returned_days_ago": 10},
    ])

    # 4 — Priya: Concrete Mixer (Small), currently ongoing, due in the future
    make_bill(priya, biller, 3, [
        {"material": "Concrete Mixer (Small, 1 bag)", "qty": 1, "start_days_ago": 3, "end_days_ago": -4,
         "status": ITEM_ONGOING},
    ])

    # 5 — Ganesh: Concrete Grinder, ongoing but OVERDUE
    make_bill(ganesh, owner, 7, [
        {"material": "Concrete Grinder", "qty": 1, "start_days_ago": 7, "end_days_ago": 2,
         "status": ITEM_ONGOING},
    ])

    # 6 — Ramesh: Angle Grinder, voided/cancelled
    make_bill(ramesh, biller, 5, [
        {"material": "Angle Grinder (4 inch)", "qty": 1, "start_days_ago": 5, "end_days_ago": 3,
         "status": ITEM_CANCELLED},
    ])

    # 7 — Sunita: Tower Crane, big-ticket returned job
    make_bill(sunita, biller, 20, [
        {"material": "Tower Crane (Small)", "qty": 1, "start_days_ago": 20, "end_days_ago": 16,
         "status": ITEM_RETURNED, "returned_days_ago": 16},
    ])

    # 8 — Mahesh: Ladder + Wheelbarrow, returned on time
    make_bill(mahesh, owner, 9, [
        {"material": "Aluminium Ladder (12 ft)", "qty": 2, "start_days_ago": 9, "end_days_ago": 7,
         "status": ITEM_RETURNED, "returned_days_ago": 7},
        {"material": "Wheelbarrow", "qty": 1, "start_days_ago": 9, "end_days_ago": 7,
         "status": ITEM_RETURNED, "returned_days_ago": 7},
    ])

    # 9 — Sneha Wagh: Generator + Welding Machine, ongoing, due in the future
    make_bill(sneha_w, biller, 2, [
        {"material": "Portable Generator (5 KVA)", "qty": 1, "start_days_ago": 2, "end_days_ago": -3,
         "status": ITEM_ONGOING},
        {"material": "Welding Machine", "qty": 1, "start_days_ago": 2, "end_days_ago": -3,
         "status": ITEM_ONGOING},
    ])

    # 10 — Priya: Vibro Roller, returned late
    make_bill(priya, owner, 25, [
        {"material": "Vibro Roller (Road Roller)", "qty": 1, "start_days_ago": 25, "end_days_ago": 22,
         "status": ITEM_RETURNED, "returned_days_ago": 20},
    ])

    db.session.commit()


with app.app_context():
    seed_data()
    seed_dummy_bills()


if __name__ == "__main__":
    app.run(debug=True)
