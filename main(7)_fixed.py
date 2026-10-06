from pathlib import Path
import os
import struct
from datetime import datetime

# ============================================================
# COFFEE SHOP MANAGEMENT SYSTEM
# Single Python file version
# Binary database + 3 TXT reports
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"
DATA_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

PRODUCT_FILE = DATA_DIR / "products.dat"
ORDER_FILE = DATA_DIR / "orders.dat"
PAYMENT_FILE = DATA_DIR / "payments.dat"

STATUS_DELETED = 0
STATUS_ACTIVE = 1
FREE_NONE = 0xFFFFFFFF
FREE_NONE_Q = 0xFFFFFFFFFFFFFFFF
ENCODING = "utf-8"
APP_VERSION = "2.0"

HEADER_STRUCT = struct.Struct("<4sB3xIIIII")
MAGIC = b"CSDB"
VERSION = 1


def encode_fixed(value, size):
    raw = str(value).encode(ENCODING)
    if len(raw) > size:
        raw = raw[:size]
        while True:
            try:
                raw.decode(ENCODING)
                break
            except UnicodeDecodeError:
                raw = raw[:-1]
    return raw.ljust(size, b"\x00")


def decode_fixed(raw):
    return raw.rstrip(b"\x00").decode(ENCODING, errors="replace")


class BinaryTable:
    def __init__(self, path, record_struct, pack_record, unpack_record, initial_id):
        self.path = Path(path)
        self.record_struct = record_struct
        self.pack_record = pack_record
        self.unpack_record = unpack_record
        self.initial_id = initial_id
        self.index = {}
        self._ensure_file()
        self.load()

    def _ensure_file(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists() or self.path.stat().st_size == 0:
            self.path.touch()
            self._write_header(0, 0, FREE_NONE, self.initial_id)

    def _write_header(self, record_count, active_count, free_head, next_id):
        header = HEADER_STRUCT.pack(
            MAGIC, VERSION, self.record_struct.size,
            record_count, active_count, free_head, next_id
        )
        with open(self.path, "r+b") as f:
            f.seek(0)
            f.write(header)
            f.flush()
            os.fsync(f.fileno())

    def _read_header(self):
        with open(self.path, "rb") as f:
            raw = f.read(HEADER_STRUCT.size)
        if len(raw) != HEADER_STRUCT.size:
            raise ValueError(f"{self.path} has an invalid header.")
        magic, version, record_size, record_count, active_count, free_head, next_id = HEADER_STRUCT.unpack(raw)
        if magic != MAGIC:
            raise ValueError(f"{self.path} is not a Coffee Shop data file.")
        if version != VERSION:
            raise ValueError(f"{self.path} uses an unsupported file version.")
        if record_size != self.record_struct.size:
            raise ValueError(f"{self.path} record size mismatch.")
        return {
            "record_count": record_count,
            "active_count": active_count,
            "free_head": free_head,
            "next_id": next_id
        }

    def _offset(self, slot):
        return HEADER_STRUCT.size + slot * self.record_struct.size

    def _read_slot(self, f, slot):
        f.seek(self._offset(slot))
        raw = f.read(self.record_struct.size)
        if len(raw) != self.record_struct.size:
            raise ValueError(f"Corrupt record at slot {slot} in {self.path}.")
        return self.unpack_record(raw)

    def _write_slot(self, f, slot, record):
        f.seek(self._offset(slot))
        f.write(self.pack_record(record))

    def load(self):
        header = self._read_header()
        expected_size = HEADER_STRUCT.size + header["record_count"] * self.record_struct.size
        if self.path.stat().st_size != expected_size:
            raise ValueError(f"{self.path} size mismatch.")
        self.index.clear()
        with open(self.path, "rb") as f:
            for slot in range(header["record_count"]):
                record = self._read_slot(f, slot)
                if record["status"] == STATUS_ACTIVE:
                    self.index[record["id"]] = slot
        if len(self.index) != header["active_count"]:
            raise ValueError(f"{self.path} active count mismatch.")

    def get(self, record_id):
        slot = self.index.get(record_id)
        if slot is None:
            return None
        with open(self.path, "rb") as f:
            return self._read_slot(f, slot)

    def all_active(self):
        records = []
        with open(self.path, "rb") as f:
            for record_id, slot in self.index.items():
                records.append(self._read_slot(f, slot))
        records.sort(key=lambda x: x["id"])
        return records

    def add(self, record):
        header = self._read_header()
        record_id = header["next_id"]
        record["id"] = record_id
        record["status"] = STATUS_ACTIVE
        record["next_free"] = FREE_NONE_Q

        if header["free_head"] != FREE_NONE:
            slot = header["free_head"]
            with open(self.path, "r+b") as f:
                old = self._read_slot(f, slot)
                next_free = old["next_free"]
                self._write_slot(f, slot, record)
                f.flush()
                os.fsync(f.fileno())
            new_free_head = next_free
            new_count = header["record_count"]
        else:
            slot = header["record_count"]
            with open(self.path, "r+b") as f:
                self._write_slot(f, slot, record)
                f.flush()
                os.fsync(f.fileno())
            new_free_head = FREE_NONE
            new_count = header["record_count"] + 1

        self._write_header(
            new_count, header["active_count"] + 1,
            new_free_head, record_id + 1
        )
        self.index[record_id] = slot
        return record_id

    def update(self, record_id, record):
        slot = self.index.get(record_id)
        if slot is None:
            return False
        record["id"] = record_id
        record["status"] = STATUS_ACTIVE
        record["next_free"] = FREE_NONE_Q
        with open(self.path, "r+b") as f:
            self._write_slot(f, slot, record)
            f.flush()
            os.fsync(f.fileno())
        return True

    def delete(self, record_id):
        slot = self.index.get(record_id)
        if slot is None:
            return False
        header = self._read_header()
        with open(self.path, "r+b") as f:
            old = self._read_slot(f, slot)
            old["status"] = STATUS_DELETED
            old["next_free"] = header["free_head"]
            self._write_slot(f, slot, old)
            f.flush()
            os.fsync(f.fileno())
        self._write_header(
            header["record_count"], header["active_count"] - 1,
            slot, header["next_id"]
        )
        del self.index[record_id]
        return True

    def stats(self):
        header = self._read_header()
        deleted = header["record_count"] - header["active_count"]
        return {
            "active": header["active_count"],
            "deleted": deleted,
            "free_slots": deleted,
            "total_slots": header["record_count"]
        }


# ------------------------- Product ---------------------------

PRODUCT_STRUCT = struct.Struct("<i40s20sfiQ")


def pack_product(r):
    return PRODUCT_STRUCT.pack(
        r["id"], encode_fixed(r["name"], 40),
        encode_fixed(r["category"], 20), float(r["price"]),
        int(r["status"]), int(r["next_free"])
    )


def unpack_product(raw):
    record_id, name, category, price, status, next_free = PRODUCT_STRUCT.unpack(raw)
    return {
        "id": record_id, "name": decode_fixed(name),
        "category": decode_fixed(category), "price": price,
        "status": status, "next_free": next_free
    }


class ProductTable(BinaryTable):
    def __init__(self):
        super().__init__(PRODUCT_FILE, PRODUCT_STRUCT, pack_product, unpack_product, 2001)


def create_product(name, category, price):
    if not name.strip():
        raise ValueError("Product name cannot be empty.")
    if not category.strip():
        raise ValueError("Category cannot be empty.")
    if price < 0:
        raise ValueError("Price cannot be negative.")
    return {
        "id": 0, "name": name.strip(), "category": category.strip(),
        "price": float(price), "status": STATUS_ACTIVE, "next_free": FREE_NONE_Q
    }


# -------------------------- Order ----------------------------

# 68 bytes: id, customer_id, 3*(product_id,qty), total, date, status, next_free
ORDER_STRUCT = struct.Struct("<iiiiiiiif20siQ")


def pack_order(r):
    items = (r.get("items", []) + [(0, 0)] * 3)[:3]
    return ORDER_STRUCT.pack(
        r["id"], r["customer_id"],
        items[0][0], items[0][1],
        items[1][0], items[1][1],
        items[2][0], items[2][1],
        float(r["total"]), encode_fixed(r["date"], 20),
        int(r["status"]), int(r["next_free"])
    )


def unpack_order(raw):
    values = ORDER_STRUCT.unpack(raw)
    record_id, customer_id, p1, q1, p2, q2, p3, q3, total, date, status, next_free = values
    items = [(p1, q1), (p2, q2), (p3, q3)]
    items = [(pid, qty) for pid, qty in items if pid > 0 and qty > 0]
    return {
        "id": record_id, "customer_id": customer_id,
        "items": items,
        "product_id": items[0][0] if items else 0,
        "quantity": items[0][1] if items else 0,
        "total": total, "date": decode_fixed(date),
        "status": status, "next_free": next_free
    }


class OrderTable(BinaryTable):
    def __init__(self):
        super().__init__(ORDER_FILE, ORDER_STRUCT, pack_order, unpack_order, 3001)


def create_order(customer_id, items, total):
    if customer_id <= 0:
        raise ValueError("Customer ID must be greater than 0.")
    if not items:
        raise ValueError("Order must contain at least one product.")
    if len(items) > 3:
        raise ValueError("An order can contain up to 3 different products.")
    if total < 0:
        raise ValueError("Total cannot be negative.")
    cleaned = []
    for pid, qty in items:
        if pid <= 0 or qty <= 0:
            raise ValueError("Product ID and quantity must be greater than 0.")
        cleaned.append((int(pid), int(qty)))
    return {
        "id": 0, "customer_id": int(customer_id), "items": cleaned,
        "product_id": cleaned[0][0], "quantity": cleaned[0][1],
        "total": float(total),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": STATUS_ACTIVE, "next_free": FREE_NONE_Q
    }


# ------------------------- Payment ---------------------------

PAYMENT_METHODS = ("Cash", "PromptPay")
PAYMENT_STRUCT = struct.Struct("<ii20sf20siQ")


def pack_payment(r):
    return PAYMENT_STRUCT.pack(
        r["id"], r["order_id"], encode_fixed(r["method"], 20),
        float(r["amount"]), encode_fixed(r["date"], 20),
        int(r["status"]), int(r["next_free"])
    )


def unpack_payment(raw):
    payment_id, order_id, method, amount, date, status, next_free = PAYMENT_STRUCT.unpack(raw)
    return {
        "id": payment_id, "order_id": order_id,
        "method": decode_fixed(method), "amount": amount,
        "date": decode_fixed(date), "status": status, "next_free": next_free
    }


class PaymentTable(BinaryTable):
    def __init__(self):
        super().__init__(PAYMENT_FILE, PAYMENT_STRUCT, pack_payment, unpack_payment, 4001)


def create_payment(order_id, method, amount):
    if method not in PAYMENT_METHODS:
        raise ValueError("Payment method must be Cash or PromptPay.")
    if amount < 0:
        raise ValueError("Amount cannot be negative.")
    return {
        "id": 0, "order_id": int(order_id), "method": method,
        "amount": float(amount),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": STATUS_ACTIVE, "next_free": FREE_NONE_Q
    }


# -------------------------- Reports --------------------------

def border(width):
    return "-" * width


def report_header(title, files):
    return [
        "=" * 110,
        title.center(110),
        "=" * 110,
        f"Generated At : {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"App Version  : {APP_VERSION}",
        "Database     : Binary fixed-length records",
        f"Data Files   : {files}",
        "=" * 110,
        ""
    ]


def generate_product_report(products, orders):
    # Product report: show every product exactly once.
    # products.dat is the main source; orders.dat supplies total sold quantity.
    product_rows = products.all_active()
    order_rows = orders.all_active()

    sold_qty = {p["id"]: 0 for p in product_rows}
    for order in order_rows:
        for pid, qty in order["items"]:
            if pid in sold_qty:
                sold_qty[pid] += qty

    lines = report_header(
        "COFFEE SHOP MANAGEMENT SYSTEM - PRODUCT REPORT",
        "products.dat + orders.dat"
    )
    lines += [
        "REPORT DETAILS",
        "แสดงสินค้าทั้งหมดจาก products.dat และจำนวนที่ขายได้ของสินค้าแต่ละรายการ",
        "โดยนำจำนวนสินค้าใน orders.dat มารวมตาม Product ID",
        "",
        border(105),
        "| Product ID | Product Name          | Category       | Price (THB) | Sold Qty | Sales (THB) |",
        border(105)
    ]

    total_qty = 0
    total_sales = 0.0
    for product in product_rows:
        qty = sold_qty[product["id"]]
        sales = product["price"] * qty
        total_qty += qty
        total_sales += sales
        lines.append(
            f"| {product['id']:<10} | {product['name']:<21} | "
            f"{product['category']:<14} | {product['price']:>11.2f} | "
            f"{qty:>8} | {sales:>11.2f} |"
        )

    if not product_rows:
        lines.append("| No active products.                                                                          |")

    lines += [
        border(105),
        "",
        "REPORT SUMMARY",
        border(75),
        f"Total Products : {len(product_rows)}",
        f"Total Sold Qty : {total_qty}",
        f"Total Sales    : {total_sales:.2f} THB",
        "",
        "End of Product Report",
        "=" * 105
    ]
    path = REPORT_DIR / "product_report.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

def generate_order_report(products, orders, payments):
    # One order per row. Multiple products in the same order are combined in one row.
    # Payment method is linked from payments.dat using Order ID.
    products_map = {p["id"]: p for p in products.all_active()}
    rows = orders.all_active()
    payment_map = {p["order_id"]: p["method"] for p in payments.all_active()}

    lines = report_header(
        "COFFEE SHOP MANAGEMENT SYSTEM - ORDER REPORT",
        "products.dat + orders.dat + payments.dat"
    )
    lines += [
        "REPORT DETAILS",
        "ตารางนี้รวมข้อมูลจาก orders.dat, products.dat และ payments.dat โดยเชื่อมด้วย Product ID และ Order ID",
        "",
        border(145),
        "| Order ID | Customer | Products                    | Qty       | Order Total | Payment   | Date                |",
        border(145)
    ]

    total_sales = 0
    total_items = 0

    for r in rows:
        product_names = []
        quantities = []

        for pid, qty in r["items"]:
            product = products_map.get(pid)
            product_name = product["name"] if product else "Unknown"
            product_names.append(product_name)
            quantities.append(str(qty))
            total_items += qty

        products_text = ", ".join(product_names)
        quantities_text = ", ".join(quantities)
        payment_method = payment_map.get(r["id"], "Unpaid")
        total_sales += r["total"]

        lines.append(
            f"| {r['id']:<8} | {r['customer_id']:<8} | "
            f"{products_text:<27} | {quantities_text:<9} | "
            f"{r['total']:>11.2f} | {payment_method:<9} | "
            f"{r['date']:<19} |"
        )

    if not rows:
        lines.append(
            "| No active orders.                                                                                                                             |"
        )

    lines += [
        border(145),
        "",
        "REPORT SUMMARY",
        border(80),
        f"Active Orders : {len(rows)}",
        f"Total Items   : {total_items}",
        f"Total Sales   : {total_sales:.2f} THB",
        "",
        "End of Order Report",
        "=" * 110
    ]

    path = REPORT_DIR / "order_report.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

def generate_payment_report(payments, orders):
    """One combined table: payments.dat + orders.dat."""
    payment_rows = payments.all_active()
    order_map = {o["id"]: o for o in orders.all_active()}

    cash = sum(p["method"] == "Cash" for p in payment_rows)
    promptpay = sum(p["method"] == "PromptPay" for p in payment_rows)
    total_paid = sum(p["amount"] for p in payment_rows)

    lines = report_header(
        "COFFEE SHOP MANAGEMENT SYSTEM - PAYMENT REPORT",
        "payments.dat + orders.dat"
    )
    lines += [
        "REPORT DETAILS",
        "ตารางเดียวนี้เชื่อมข้อมูลการชำระเงิน (payments.dat) กับข้อมูลคำสั่งซื้อ (orders.dat)",
        "โดย Order ID เป็นตัวเชื่อมเพื่อแสดง Customer ID และ Order Total ในตารางเดียวกัน",
        "",
        border(125),
        "| Payment ID | Order ID | Customer | Method    | Paid (THB) | Order Total | Payment Date       |",
        border(125)
    ]

    for p in payment_rows:
        order = order_map.get(p["order_id"])
        customer = str(order["customer_id"]) if order else "N/A"
        order_total = order["total"] if order else 0.0
        lines.append(
            f"| {p['id']:<10} | {p['order_id']:<8} | {customer:<8} | "
            f"{p['method']:<9} | {p['amount']:>10.2f} | {order_total:>11.2f} | {p['date']:<18} |"
        )

    if not payment_rows:
        lines.append("| No active payments.                                                                                                           |")

    lines += [
        border(125),
        "",
        "REPORT SUMMARY",
        border(60),
        f"Cash Payments      : {cash}",
        f"PromptPay Payments : {promptpay}",
        f"Active Payments    : {len(payment_rows)}",
        f"Total Paid         : {total_paid:.2f} THB",
        "",
        "End of Payment Report",
        "=" * 110
    ]
    path = REPORT_DIR / "payment_report.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --------------------------- Input ----------------------------

def read_int(prompt, minimum=None):
    while True:
        try:
            value = int(input(prompt).strip())
            if minimum is not None and value < minimum:
                print(f"Please enter a number >= {minimum}.")
                continue
            return value
        except ValueError:
            print("Please enter a valid integer.")


def read_float(prompt, minimum=None):
    while True:
        try:
            value = float(input(prompt).strip())
            if minimum is not None and value < minimum:
                print(f"Please enter a number >= {minimum}.")
                continue
            return value
        except ValueError:
            print("Please enter a valid number.")


def read_text(prompt):
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("This field cannot be empty.")


def choose_payment_method():
    print("1. Cash")
    print("2. PromptPay")
    while True:
        choice = input("Choose method: ").strip()
        if choice == "1":
            return "Cash"
        if choice == "2":
            return "PromptPay"
        print("Invalid choice.")


# --------------------------- View -----------------------------

def print_products(products):
    rows = products.all_active()
    print("\n" + border(90))
    print(f"{'ID':<8}{'Name':<25}{'Category':<17}{'Price':>10}")
    print(border(90))
    for r in rows:
        print(f"{r['id']:<8}{r['name']:<25}{r['category']:<17}{r['price']:>10.2f}")
    if not rows:
        print("No products found.")
    print(border(90))


def print_orders(products, orders):
    product_map = {p["id"]: p for p in products.all_active()}
    rows = orders.all_active()
    print("\n" + border(110))
    print(f"{'ID':<8}{'Customer':<12}{'Products':<32}{'Total':<14}{'Date':<20}")
    print(border(110))
    for r in rows:
        items = ", ".join(
            f"{product_map.get(pid, {'name': str(pid)})['name']} x{qty}"
            for pid, qty in r["items"]
        )
        print(f"{r['id']:<8}{r['customer_id']:<12}{items:<32}{r['total']:<14.2f}{r['date']:<20}")
    if not rows:
        print("No orders found.")
    print(border(110))


def print_payments(payments):
    rows = payments.all_active()
    print("\n" + border(90))
    print(f"{'ID':<10}{'Order':<10}{'Method':<12}{'Amount':<14}{'Date':<20}")
    print(border(90))
    for r in rows:
        print(f"{r['id']:<10}{r['order_id']:<10}{r['method']:<12}{r['amount']:<14.2f}{r['date']:<20}")
    if not rows:
        print("No payments found.")
    print(border(90))


# --------------------------- CRUD -----------------------------

def add_product(products):
    print("\n--- Add Product ---")
    name = read_text("Name: ")
    category = read_text("Category: ")
    price = read_float("Price (THB): ", 0)
    print(f"Product added. ID = {products.add(create_product(name, category, price))}")


def add_order(products, orders, payments):
    print("\n--- Add Order ---")
    customer_id = read_int("Customer ID: ", 1)
    items = []

    while len(items) < 3:
        print_products(products)
        pid = read_int("Product ID: ", 1)
        product = products.get(pid)
        if product is None:
            print("Product ID not found.")
            continue
        qty = read_int("Quantity: ", 1)

        found = False
        for i, (old_pid, old_qty) in enumerate(items):
            if old_pid == pid:
                items[i] = (pid, old_qty + qty)
                found = True
                break
        if not found:
            items.append((pid, qty))

        total = sum(products.get(p)["price"] * q for p, q in items)
        print(f"Current Total = {total:.2f} THB")

        if len(items) == 3:
            break
        if input("Add another product? (Y/N): ").strip().upper() != "Y":
            break

    total = sum(products.get(p)["price"] * q for p, q in items)
    order_id = orders.add(create_order(customer_id, items, total))
    print(f"Order added. ID = {order_id}, Total = {total:.2f} THB")

    if input("Pay now? (Y/N): ").strip().upper() == "Y":
        method = choose_payment_method()
        payments.add(create_payment(order_id, method, total))
        print("Payment added.")


def add_payment(orders, payments):
    print_orders_for_payment(orders)
    order_id = read_int("Order ID: ", 1)
    order = orders.get(order_id)
    if order is None:
        print("Order not found.")
        return
    method = choose_payment_method()
    payments.add(create_payment(order_id, method, order["total"]))
    print("Payment added.")


def print_orders_for_payment(orders):
    print("\n--- Orders ---")
    for r in orders.all_active():
        print(f"Order {r['id']} | Customer {r['customer_id']} | Total {r['total']:.2f}")


def update_product(products):
    print_products(products)
    rid = read_int("Product ID: ", 1)
    old = products.get(rid)
    if old is None:
        print("Product not found.")
        return
    name = read_text(f"Name [{old['name']}]: ")
    category = read_text(f"Category [{old['category']}]: ")
    price = read_float(f"Price [{old['price']:.2f}]: ", 0)
    products.update(rid, create_product(name, category, price))
    print("Product updated.")


def update_order(products, orders):
    print_orders(products, orders)
    rid = read_int("Order ID: ", 1)
    old = orders.get(rid)
    if old is None:
        print("Order not found.")
        return

    customer_id = read_int(f"Customer ID [{old['customer_id']}]: ", 1)
    items = []
    while len(items) < 3:
        print_products(products)
        pid = read_int("Product ID: ", 1)
        if products.get(pid) is None:
            print("Product not found.")
            continue
        qty = read_int("Quantity: ", 1)
        items.append((pid, qty))
        if len(items) == 3 or input("Add another product? (Y/N): ").strip().upper() != "Y":
            break

    total = sum(products.get(pid)["price"] * qty for pid, qty in items)
    updated = create_order(customer_id, items, total)
    updated["date"] = old["date"]
    orders.update(rid, updated)
    print("Order updated.")


def update_payment(orders, payments):
    print_payments(payments)
    rid = read_int("Payment ID: ", 1)
    old = payments.get(rid)
    if old is None:
        print("Payment not found.")
        return
    order = orders.get(old["order_id"])
    if order is None:
        print("Related order not found.")
        return
    method = choose_payment_method()
    updated = create_payment(old["order_id"], method, order["total"])
    updated["date"] = old["date"]
    payments.update(rid, updated)
    print("Payment updated.")


def delete_product(products, orders):
    rid = read_int("Product ID: ", 1)
    for order in orders.all_active():
        if any(pid == rid for pid, _ in order["items"]):
            print("Cannot delete: product is used by an active order.")
            return
    print("Product deleted." if products.delete(rid) else "Product not found.")


def delete_order(orders, payments):
    rid = read_int("Order ID: ", 1)
    for p in payments.all_active():
        if p["order_id"] == rid:
            payments.delete(p["id"])
    print("Order deleted." if orders.delete(rid) else "Order not found.")


def delete_payment(payments):
    rid = read_int("Payment ID: ", 1)
    print("Payment deleted." if payments.delete(rid) else "Payment not found.")


# --------------------------- Menus ----------------------------

def add_menu(products, orders, payments):
    while True:
        print("\n=== ADD MENU ===")
        print("1. Product")
        print("2. Order")
        print("3. Payment")
        print("0. Back")
        c = input("Choose: ").strip()
        if c == "1":
            add_product(products)
        elif c == "2":
            add_order(products, orders, payments)
        elif c == "3":
            add_payment(orders, payments)
        elif c == "0":
            return
        else:
            print("Invalid choice.")


def update_menu(products, orders, payments):
    while True:
        print("\n=== UPDATE MENU ===")
        print("1. Product")
        print("2. Order")
        print("3. Payment")
        print("0. Back")
        c = input("Choose: ").strip()
        if c == "1":
            update_product(products)
        elif c == "2":
            update_order(products, orders)
        elif c == "3":
            update_payment(orders, payments)
        elif c == "0":
            return
        else:
            print("Invalid choice.")


def delete_menu(products, orders, payments):
    while True:
        print("\n=== DELETE MENU ===")
        print("1. Product")
        print("2. Order")
        print("3. Payment")
        print("0. Back")
        c = input("Choose: ").strip()
        if c == "1":
            delete_product(products, orders)
        elif c == "2":
            delete_order(orders, payments)
        elif c == "3":
            delete_payment(payments)
        elif c == "0":
            return
        else:
            print("Invalid choice.")


def view_menu(products, orders, payments):
    while True:
        print("\n=== VIEW MENU ===")
        print("1. Products")
        print("2. Orders")
        print("3. Payments")
        print("0. Back")
        c = input("Choose: ").strip()
        if c == "1":
            print_products(products)
        elif c == "2":
            print_orders(products, orders)
        elif c == "3":
            print_payments(payments)
        elif c == "0":
            return
        else:
            print("Invalid choice.")


def report_menu(products, orders, payments):
    while True:
        print("\n=== GENERATE REPORT ===")
        print("1. Product Report")
        print("2. Order Report")
        print("3. Payment Report")
        print("0. Back")
        c = input("Choose: ").strip()

        if c == "1":
            print("Generated:", generate_product_report(products, orders))
        elif c == "2":
            print("Generated:", generate_order_report(products, orders, payments))
        elif c == "3":
            print("Generated:", generate_payment_report(payments, orders))
        elif c == "0":
            return
        else:
            print("Invalid choice.")


def main():
    try:
        products = ProductTable()
        orders = OrderTable()
        payments = PaymentTable()
    except ValueError as exc:
        print("DATA FILE ERROR:", exc)
        return

    while True:
        print("\n" + "=" * 55)
        print("       COFFEE SHOP MANAGEMENT SYSTEM")
        print("=" * 55)
        print("1. Add")
        print("2. Update")
        print("3. Delete")
        print("4. View")
        print("5. Generate Report")
        print("0. Exit")
        print("=" * 55)

        choice = input("Choose: ").strip()
        try:
            if choice == "1":
                add_menu(products, orders, payments)
            elif choice == "2":
                update_menu(products, orders, payments)
            elif choice == "3":
                delete_menu(products, orders, payments)
            elif choice == "4":
                view_menu(products, orders, payments)
            elif choice == "5":
                report_menu(products, orders, payments)
            elif choice == "0":
                print("Goodbye.")
                break
            else:
                print("Invalid choice.")
        except (ValueError, EOFError) as exc:
            print("Error:", exc)


if __name__ == "__main__":
    main()
