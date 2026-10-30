# BuildRent — Shop Rental Billing System

A Flask web app built for **one shop** renting construction materials & machines
(bamboos, hatodi, khora, chalni, grinders, mixers, JCBs, cranes, etc.) — for a
Civil Engineering minor project. No multi-vendor marketplace, no demand
forecasting — just a real POS-style billing system with three access levels.

## Roles

1. **Owner** — full access: inventory, categories, staff (biller) accounts,
   shop settings, all bills, analytics dashboard with charts.
2. **Biller** — point-of-sale billing: build a bill with multiple items for a
   walk-in customer, print the invoice, process returns. Cannot touch
   inventory, staff, or settings.
3. **Customer** *(optional login)* — read-only: view their own rental
   history and reprint past invoices. Rentals are still created by the
   biller at the counter, not self-booked online.

## Key Features

- **POS-style "New Bill" screen** — pick a customer (auto-fills if their
  phone matches an existing record), add multiple items to a live cart with
  dates & quantity, see the running total instantly, submit as one bill.
- **Account claiming** — a customer who was originally added as a walk-in by
  a biller can later register with the *same phone number* and their full
  bill history is automatically linked to their new login.
- Role-based access control (owner / biller / customer route guards)
- Inventory & category management, low-stock alerts
- Full item lifecycle: **Ongoing → Returned** (or voided), with automatic
  **late fee** calculation on overdue returns
- Multi-item **printable invoice** (Print / Save as PDF) shown after billing
  and reusable from the bill history
- Owner analytics dashboard: revenue, active rentals, overdue count, items
  by status (chart), revenue by category (chart)
- Shop settings (name, address, phone, GST) reflected on every invoice

## Setup

```bash
cd rental_system
pip install -r requirements.txt
python app.py
```

Visit **http://127.0.0.1:5000**. The database (`shop.db`, SQLite) and demo
data are created automatically on first run.

## Demo Logins

| Role   | Email             | Password  |
|--------|-------------------|-----------|
| Owner  | owner@shop.com    | owner123  |
| Biller | biller@shop.com   | biller123 |

Try billing a walk-in customer via **New Bill**, then register a customer
account (`/register`) using that same phone number to see the account-claim
feature link their history.

## Project Structure

```
rental_system/
├── app.py                 # routes, auth, billing logic
├── models.py               # User, ShopSettings, Category, Material, Bill, BillItem
├── requirements.txt
├── static/css/style.css
└── templates/
    ├── base.html, index.html, catalog.html, login.html, register.html, invoice.html
    ├── owner/    (dashboard, inventory, material_form, categories, staff, settings)
    ├── biller/   (dashboard)
    ├── shared/   (new_bill, bills, active_rentals, customers — owner + biller)
    └── customer/ (dashboard, bills)
```

## Possible Extensions

- Payment gateway integration for deposits
- SMS notifications on return due date
- Barcode/QR scanning for faster item lookup at the counter
- Multi-branch support
