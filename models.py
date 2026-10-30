from datetime import date
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

ROLE_OWNER = "owner"
ROLE_BILLER = "biller"
ROLE_CUSTOMER = "customer"

ITEM_ONGOING = "Ongoing"
ITEM_RETURNED = "Returned"
ITEM_CANCELLED = "Cancelled"


class ShopSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shop_name = db.Column(db.String(150), default="BuildRent Hardware & Machinery")
    tagline = db.Column(db.String(200), default="Construction material & machine rentals")
    address = db.Column(db.String(255), default="MIDC, Chh. Sambhaji Nagar, Maharashtra")
    phone = db.Column(db.String(20), default="9876543210")
    gst_no = db.Column(db.String(30), default="")


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    phone = db.Column(db.String(20), unique=True, nullable=True)
    address = db.Column(db.String(255))
    password_hash = db.Column(db.String(255), nullable=True)
    has_login = db.Column(db.Boolean, default=False)  # False for walk-in customers with no account yet
    role = db.Column(db.String(20), nullable=False, default=ROLE_CUSTOMER)
    is_active_account = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=db.func.now())

    bills_as_customer = db.relationship("Bill", foreign_keys="Bill.customer_id", backref="customer", lazy=True)
    bills_as_biller = db.relationship("Bill", foreign_keys="Bill.biller_id", backref="biller", lazy=True)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)
        self.has_login = True

    def check_password(self, pw):
        return bool(self.password_hash) and check_password_hash(self.password_hash, pw)

    @property
    def is_active(self):
        return self.is_active_account


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    icon = db.Column(db.String(20), default="🧰")

    materials = db.relationship("Material", backref="category", lazy=True)


class Material(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    price_per_day = db.Column(db.Float, nullable=False)
    deposit_amount = db.Column(db.Float, default=0)
    quantity_total = db.Column(db.Integer, nullable=False, default=1)
    quantity_available = db.Column(db.Integer, nullable=False, default=1)
    image_emoji = db.Column(db.String(10), default="🧱")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=db.func.now())

    items = db.relationship("BillItem", backref="material", lazy=True)

    @property
    def low_stock(self):
        return self.quantity_total > 0 and (self.quantity_available / self.quantity_total) <= 0.2


class Bill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    biller_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=db.func.now())

    items = db.relationship("BillItem", backref="bill", lazy=True, cascade="all, delete-orphan")

    @property
    def subtotal(self):
        return sum(i.subtotal for i in self.items if i.status != ITEM_CANCELLED)

    @property
    def deposit_total(self):
        return sum(i.deposit_total for i in self.items if i.status != ITEM_CANCELLED)

    @property
    def late_fee_total(self):
        return sum(i.late_fee or 0 for i in self.items)

    @property
    def grand_total(self):
        return self.subtotal + self.deposit_total + self.late_fee_total

    @property
    def status(self):
        active_items = [i for i in self.items if i.status != ITEM_CANCELLED]
        if not active_items:
            return ITEM_CANCELLED
        if any(i.status == ITEM_ONGOING for i in active_items):
            return ITEM_ONGOING
        return ITEM_RETURNED

    @property
    def is_overdue(self):
        return any(i.is_overdue for i in self.items)


class BillItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey("bill.id"), nullable=False)
    material_id = db.Column(db.Integer, db.ForeignKey("material.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    rate_per_day = db.Column(db.Float, nullable=False)
    deposit_per_unit = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default=ITEM_ONGOING)
    actual_return_date = db.Column(db.Date)
    late_fee = db.Column(db.Float, default=0)

    @property
    def days(self):
        return max((self.end_date - self.start_date).days, 1)

    @property
    def subtotal(self):
        return self.days * self.rate_per_day * self.quantity

    @property
    def deposit_total(self):
        return self.deposit_per_unit * self.quantity

    @property
    def is_overdue(self):
        return self.status == ITEM_ONGOING and date.today() > self.end_date
