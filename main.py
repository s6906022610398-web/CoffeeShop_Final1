# COFFEE SHOP MANAGEMENT SYSTEM
# Single-file version: main.py
# All data files remain binary (.dat); all reports are separate .txt files.

from pathlib import Path
import os
import struct
from datetime import datetime

# =========================
# CONFIGURATION
# =========================
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
PRODUCT_FILE = DATA_DIR / "products.dat"
ORDER_FILE = DATA_DIR / "orders.dat"
PAYMENT_FILE = DATA_DIR / "payments.dat"
REPORT_DIR = Path("reports")
PRODUCT_REPORT_FILE = REPORT_DIR / "product_report.txt"
ORDER_REPORT_FILE = REPORT_DIR / "order_report.txt"
PAYMENT_REPORT_FILE = REPORT_DIR / "payment_report.txt"
APP_VERSION = "1.0"
ENCODING = "utf-8"
STATUS_DELETED = 0
STATUS_ACTIVE = 1
FREE_NONE = 0xFFFFFFFF
FREE_NONE_Q = 0xFFFFFFFFFFFFFFFF


# =========================
# BINARY DATABASE ENGINE
# =========================

# Header:
# magic(4) + version(1) + padding(3) +
# record_size(4) + record_count(4) + active_count(4) +
# free_head(4) + next_id(4) = 28 bytes
HEADER_STRUCT = struct.Struct("<4sB3xIIIII")

MAGIC = b"CSDB"
VERSION = 1
HEADER_SIZE = HEADER_STRUCT.size


def encode_fixed(value, size):
    """Encode text to UTF-8, safely truncate, then pad with zero bytes."""
    raw = str(value).encode(ENCODING)

    if len(raw) > size:
        raw = raw[:size]

        # Prevent cutting a UTF-8 character in half
        while True:
            try:
                raw.decode(ENCODING)
                break
            except UnicodeDecodeError:
                raw = raw[:-1]

    return raw.ljust(size, b"\x00")


def decode_fixed(raw):
    """Decode fixed-length UTF-8 bytes."""
    return raw.rstrip(b"\x00").decode(
        ENCODING,
        errors="replace"
    )


class BinaryTable:
    """
    Reusable fixed-length binary table.

    Features:
    - Fixed-length records
    - Binary file I/O
    - Logical delete
    - Free-list
    - In-memory index
    """

    def __init__(
        self,
        path: Path,
        record_struct,
        pack_record,
        unpack_record,
        initial_id=1,
    ):
        self.path = Path(path)
        self.record_struct = record_struct
        self.pack_record = pack_record
        self.unpack_record = unpack_record
        self.initial_id = initial_id
        self.index = {}

        self._ensure_file()
        self.load()

    # ---------------------------------------------------------
    # File initialization
    # ---------------------------------------------------------

    def _ensure_file(self):
        """Create the binary file and header if it does not exist."""

        # Make sure the data folder exists
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        # Create a new empty file
        if not self.path.exists() or self.path.stat().st_size == 0:
            self.path.touch()

            self._write_header(
                record_count=0,
                active_count=0,
                free_head=FREE_NONE,
                next_id=self.initial_id,
            )

    # ---------------------------------------------------------
    # Header
    # ---------------------------------------------------------

    def _write_header(
        self,
        record_count,
        active_count,
        free_head,
        next_id,
    ):
        """Write the database header without deleting records."""

        header = HEADER_STRUCT.pack(
            MAGIC,
            VERSION,
            self.record_struct.size,
            record_count,
            active_count,
            free_head,
            next_id,
        )

        # r+b = read/write binary without deleting existing data
        with open(self.path, "r+b") as file:
            file.seek(0)
            file.write(header)
            file.flush()
            os.fsync(file.fileno())

    def _read_header(self):
        """Read and validate the database header."""

        with open(self.path, "rb") as file:
            raw = file.read(HEADER_SIZE)

        if len(raw) != HEADER_SIZE:
            raise ValueError(
                f"{self.path} has an invalid header."
            )

        (
            magic,
            version,
            record_size,
            record_count,
            active_count,
            free_head,
            next_id,
        ) = HEADER_STRUCT.unpack(raw)

        if magic != MAGIC:
            raise ValueError(
                f"{self.path} is not a Coffee Shop data file."
            )

        if version != VERSION:
            raise ValueError(
                f"{self.path} uses an unsupported file version."
            )

        if record_size != self.record_struct.size:
            raise ValueError(
                f"{self.path} record size mismatch: "
                f"file={record_size}, "
                f"expected={self.record_struct.size}"
            )

        return {
            "record_count": record_count,
            "active_count": active_count,
            "free_head": free_head,
            "next_id": next_id,
        }

    # ---------------------------------------------------------
    # Record position
    # ---------------------------------------------------------

    def _offset(self, slot):
        """Calculate byte position of a record slot."""

        return (
            HEADER_SIZE
            + slot * self.record_struct.size
        )

    # ---------------------------------------------------------
    # Read / Write Record
    # ---------------------------------------------------------

    def _read_slot(self, file, slot):
        """Read one fixed-length record."""

        file.seek(self._offset(slot))

        raw = file.read(
            self.record_struct.size
        )

        if len(raw) != self.record_struct.size:
            raise ValueError(
                f"Corrupt record at slot {slot} "
                f"in {self.path}."
            )

        return self.unpack_record(raw)

    def _write_slot(self, file, slot, record):
        """Write one fixed-length record."""

        file.seek(self._offset(slot))

        file.write(
            self.pack_record(record)
        )

    # ---------------------------------------------------------
    # Load
    # ---------------------------------------------------------

    def load(self):
        """Load active records into the in-memory index."""

        header = self._read_header()

        expected_size = (
            HEADER_SIZE
            + (
                header["record_count"]
                * self.record_struct.size
            )
        )

        actual_size = self.path.stat().st_size

        if actual_size != expected_size:
            raise ValueError(
                f"{self.path} size mismatch. "
                f"Expected {expected_size} bytes, "
                f"found {actual_size} bytes."
            )

        self.index.clear()

        with open(self.path, "rb") as file:

            for slot in range(
                header["record_count"]
            ):
                record = self._read_slot(
                    file,
                    slot
                )

                if (
                    record["status"]
                    == STATUS_ACTIVE
                ):
                    self.index[
                        record["id"]
                    ] = slot

        if (
            len(self.index)
            != header["active_count"]
        ):
            raise ValueError(
                f"{self.path} active record "
                f"count does not match its header."
            )

        return header

    # ---------------------------------------------------------
    # Get
    # ---------------------------------------------------------

    def get(self, record_id):
        """Get one active record by ID."""

        slot = self.index.get(record_id)

        if slot is None:
            return None

        with open(self.path, "rb") as file:
            return self._read_slot(
                file,
                slot
            )

    # ---------------------------------------------------------
    # Get All Active Records
    # ---------------------------------------------------------

    def all_active(self):
        """Return all active records sorted by ID."""

        records = []

        with open(self.path, "rb") as file:

            for record_id, slot in self.index.items():
                records.append(
                    self._read_slot(
                        file,
                        slot
                    )
                )

        records.sort(
            key=lambda item: item["id"]
        )

        return records

    # ---------------------------------------------------------
    # Add
    # ---------------------------------------------------------

    def add(self, record):
        """
        Add a new record.

        If a deleted slot exists, reuse that slot.
        Otherwise append a new slot at the end.
        """

        header = self._read_header()

        record_id = header["next_id"]

        record["id"] = record_id
        record["status"] = STATUS_ACTIVE

        # -----------------------------------------------------
        # Reuse deleted slot
        # -----------------------------------------------------

        if header["free_head"] != FREE_NONE:

            slot = header["free_head"]

            with open(
                self.path,
                "r+b"
            ) as file:

                old_record = self._read_slot(
                    file,
                    slot
                )

                next_free = old_record[
                    "next_free"
                ]

                record["next_free"] = FREE_NONE_Q

                self._write_slot(
                    file,
                    slot,
                    record
                )

                file.flush()
                os.fsync(file.fileno())

            new_free_head = next_free

            new_record_count = (
                header["record_count"]
            )

        # -----------------------------------------------------
        # Append new slot
        # -----------------------------------------------------

        else:

            slot = header["record_count"]

            record["next_free"] = FREE_NONE_Q

            with open(
                self.path,
                "r+b"
            ) as file:

                self._write_slot(
                    file,
                    slot,
                    record
                )

                file.flush()
                os.fsync(file.fileno())

            new_free_head = FREE_NONE

            new_record_count = (
                header["record_count"] + 1
            )

        # -----------------------------------------------------
        # Update header
        # -----------------------------------------------------

        self._write_header(
            record_count=new_record_count,
            active_count=(
                header["active_count"] + 1
            ),
            free_head=new_free_head,
            next_id=record_id + 1,
        )

        # Update in-memory index
        self.index[record_id] = slot

        return record_id

    # ---------------------------------------------------------
    # Update
    # ---------------------------------------------------------

    def update(self, record_id, record):
        """Update an existing active record."""

        slot = self.index.get(record_id)

        if slot is None:
            return False

        record["id"] = record_id
        record["status"] = STATUS_ACTIVE
        record["next_free"] = FREE_NONE_Q

        with open(
            self.path,
            "r+b"
        ) as file:

            self._write_slot(
                file,
                slot,
                record
            )

            file.flush()
            os.fsync(file.fileno())

        return True

    # ---------------------------------------------------------
    # Delete
    # ---------------------------------------------------------

    def delete(self, record_id):
        """
        Logical delete.

        The record remains inside the binary file,
        but its status becomes DELETED and its slot
        is added to the free-list.
        """

        slot = self.index.get(record_id)

        if slot is None:
            return False

        header = self._read_header()

        with open(
            self.path,
            "r+b"
        ) as file:

            old_record = self._read_slot(
                file,
                slot
            )

            old_record["status"] = STATUS_DELETED

            # Link this deleted slot to the
            # previous free-list head
            old_record["next_free"] = (
                header["free_head"]
            )

            self._write_slot(
                file,
                slot,
                old_record
            )

            file.flush()
            os.fsync(file.fileno())

        # Update header
        self._write_header(
            record_count=header["record_count"],
            active_count=(
                header["active_count"] - 1
            ),
            free_head=slot,
            next_id=header["next_id"],
        )

        # Remove from active index
        del self.index[record_id]

        return True

    # ---------------------------------------------------------
    # Statistics
    # ---------------------------------------------------------

    def stats(self):
        """Return database statistics."""

        header = self._read_header()

        deleted = (
            header["record_count"]
            - header["active_count"]
        )

        return {
            "active": header["active_count"],
            "deleted": deleted,
            "free_slots": deleted,
            "total_slots": header["record_count"],
        }

# =========================
# PRODUCT
# =========================

# Product record = 80 bytes
# < i 40s 20s f i Q
PRODUCT_STRUCT = struct.Struct("<i40s20sfiQ")


def pack_product(record):
    return PRODUCT_STRUCT.pack(
        record["id"],
        encode_fixed(record["name"], 40),
        encode_fixed(record["category"], 20),
        float(record["price"]),
        int(record["status"]),
        int(record["next_free"]),
    )


def unpack_product(raw):
    record_id, name, category, price, status, next_free = PRODUCT_STRUCT.unpack(raw)

    return {
        "id": record_id,
        "name": decode_fixed(name),
        "category": decode_fixed(category),
        "price": price,
        "status": status,
        "next_free": next_free,
    }


class ProductTable(BinaryTable):
    def __init__(self):
        super().__init__(
            PRODUCT_FILE,
            PRODUCT_STRUCT,
            pack_product,
            unpack_product,
            initial_id=2001,
        )


def create_product(name, category, price):
    if not name.strip():
        raise ValueError("Product name cannot be empty.")
    if not category.strip():
        raise ValueError("Category cannot be empty.")
    if price < 0:
        raise ValueError("Price cannot be negative.")

    return {
        "id": 0,
        "name": name.strip(),
        "category": category.strip(),
        "price": float(price),
        "status": STATUS_ACTIVE,
        "next_free": FREE_NONE_Q,
    }


# =========================
# ORDER
# =========================

# Order record = 68 bytes
# < id, customer_id, product_id_1, qty_1, product_id_2, qty_2, product_id_3, qty_3, total, date, status, next_free
ORDER_STRUCT = struct.Struct("<iiiiiiiif20siQ")


def pack_order(record):
    items = record.get("items", [])
    items = (items + [(0, 0)] * 3)[:3]

    return ORDER_STRUCT.pack(
        record["id"],
        record["customer_id"],
        items[0][0], items[0][1],
        items[1][0], items[1][1],
        items[2][0], items[2][1],
        float(record["total"]),
        encode_fixed(record["date"], 20),
        int(record["status"]),
        int(record["next_free"]),
    )


def unpack_order(raw):
    (
        record_id, customer_id,
        p1, q1, p2, q2, p3, q3,
        total, date, status, next_free,
    ) = ORDER_STRUCT.unpack(raw)

    items = [(p1, q1), (p2, q2), (p3, q3)]
    items = [(pid, qty) for pid, qty in items if pid > 0 and qty > 0]

    return {
        "id": record_id,
        "customer_id": customer_id,
        "product_id": items[0][0] if items else 0,
        "quantity": items[0][1] if items else 0,
        "items": items,
        "total": total,
        "date": decode_fixed(date),
        "status": status,
        "next_free": next_free,
    }


class OrderTable(BinaryTable):
    def __init__(self):
        super().__init__(
            ORDER_FILE,
            ORDER_STRUCT,
            pack_order,
            unpack_order,
            initial_id=3001,
        )


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
    for product_id, quantity in items:
        if product_id <= 0:
            raise ValueError("Product ID must be greater than 0.")
        if quantity <= 0:
            raise ValueError("Quantity must be greater than 0.")
        cleaned.append((int(product_id), int(quantity)))

    return {
        "id": 0,
        "customer_id": int(customer_id),
        "product_id": cleaned[0][0],
        "quantity": cleaned[0][1],
        "items": cleaned,
        "total": float(total),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": STATUS_ACTIVE,
        "next_free": FREE_NONE_Q,
    }


# =========================
# PAYMENT
# =========================

PAYMENT_METHODS = ("Cash", "PromptPay")

# Payment record = 68 bytes
# < i i 20s f 20s i Q
PAYMENT_STRUCT = struct.Struct("<ii20sf20siQ")


def pack_payment(record):
    return PAYMENT_STRUCT.pack(
        record["id"],
        record["order_id"],
        encode_fixed(record["method"], 20),
        float(record["amount"]),
        encode_fixed(record["date"], 20),
        int(record["status"]),
        int(record["next_free"]),
    )


def unpack_payment(raw):
    payment_id, order_id, method, amount, date, status, next_free = (
        PAYMENT_STRUCT.unpack(raw)
    )

    return {
        "id": payment_id,
        "order_id": order_id,
        "method": decode_fixed(method),
        "amount": amount,
        "date": decode_fixed(date),
        "status": status,
        "next_free": next_free,
    }


class PaymentTable(BinaryTable):
    def __init__(self):
        super().__init__(
            PAYMENT_FILE,
            PAYMENT_STRUCT,
            pack_payment,
            unpack_payment,
            initial_id=4001,
        )


def create_payment(order_id, method, amount):
    if method not in PAYMENT_METHODS:
        raise ValueError("Payment method must be Cash or PromptPay.")
    if amount < 0:
        raise ValueError("Amount cannot be negative.")

    return {
        "id": 0,
        "order_id": order_id,
        "method": method,
        "amount": float(amount),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": STATUS_ACTIVE,
        "next_free": FREE_NONE_Q,
    }


# =========================
# REPORTS
# =========================

# -----------------------------------------------------------------------------
# Formatting helpers
# -----------------------------------------------------------------------------

def line(char="-", width=100):
    return char * width


def status_text(status):
    return "Active" if status == 1 else "Deleted"


def payment_status_text(status):
    return "Paid" if status == 1 else "Deleted"


def fit_text(value, width):
    """Keep text inside a fixed-width TXT table column."""
    text = str(value)
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def _header(title, data_files, purpose):
    """Common report details section used by every report."""
    return [
        "=" * 100,
        f"                 {title}",
        "=" * 100,
        "=== Report Details ===",
        f"Generated At : {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"App Version  : {APP_VERSION}",
        "Endianness   : Little-Endian",
        "Encoding     : UTF-8 (Fixed-length Record)",
        f"Data Files   : {data_files}",
        f"Purpose      : {purpose}",
        "=" * 100,
        "",
    ]


# -----------------------------------------------------------------------------
# Product Report
# Uses products.dat + orders.dat
# -----------------------------------------------------------------------------

def generate_product_report(products, orders):
    product_rows = products.all_active()
    order_rows = orders.all_active()
    stats = products.stats()

    # Calculate sold quantity from orders.dat.
    sold_quantity = {}
    for order in order_rows:
        for product_id, quantity in order.get("items", []):
            sold_quantity[product_id] = sold_quantity.get(product_id, 0) + quantity

    lines = _header(
        "Coffee Shop Management System - Product Report",
        "products.dat, orders.dat",
        "Product information from products.dat with sales quantity from orders.dat",
    )

    lines += [
        "=== Product Report ===",
        line("-", 100),
        "| ID     | Name                     | Category       | Price (THB) | Sold Qty | Sales (THB) | Status  |",
        line("-", 100),
    ]

    total_sales = 0.0
    total_sold = 0

    for row in product_rows:
        quantity = sold_quantity.get(row["id"], 0)
        sales = row["price"] * quantity
        total_sold += quantity
        total_sales += sales

        lines.append(
            f"| {row['id']:<6} | {fit_text(row['name'], 24):<24} | "
            f"{fit_text(row['category'], 14):<14} | {row['price']:>11.2f} | "
            f"{quantity:>8} | {sales:>11.2f} | {status_text(row['status']):<7} |"
        )

    if not product_rows:
        lines.append(
            "| No active products.                                                                                     |"
        )

    lines += [
        line("-", 100),
        "",
        "=== Product Summary ===",
        line("-"),
        f"Active Products : {stats['active']}",
        f"Deleted Products: {stats['deleted']}",
        f"Free Slots      : {stats['free_slots']}",
        f"Total Sold Qty  : {total_sold}",
        f"Total Sales     : {total_sales:.2f} THB",
        "",
        "Note: Product details come from products.dat; Sold Qty and Sales are calculated from orders.dat.",
        "",
        "=" * 100,
        "                              End of Product Report",
        "=" * 100,
    ]

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    PRODUCT_REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return PRODUCT_REPORT_FILE


# -----------------------------------------------------------------------------
# Order Report
# Uses products.dat + orders.dat
# -----------------------------------------------------------------------------

def generate_order_report(products, orders):
    order_rows = orders.all_active()
    product_map = {row["id"]: row for row in products.all_active()}
    stats = orders.stats()
    total_sales = sum(row["total"] for row in order_rows)

    lines = _header(
        "Coffee Shop Management System - Order Report",
        "products.dat, orders.dat",
        "Order information from orders.dat with product names from products.dat",
    )

    lines += [
        "=== Order Report ===",
        line("-", 110),
        "| Order ID | Customer | Products                          | Total (THB) | Date                | Status  |",
        line("-", 110),
    ]

    for row in order_rows:
        product_text = ", ".join(
            f"{product_map.get(pid, {'name': str(pid)})['name']} x{qty}"
            for pid, qty in row.get("items", [])
        )
        product_text = fit_text(product_text, 33)

        lines.append(
            f"| {row['id']:<8} | {row['customer_id']:<8} | {product_text:<33} | "
            f"{row['total']:>10.2f} | {row['date']:<19} | "
            f"{status_text(row['status']):<7} |"
        )

    if not order_rows:
        lines.append(
            "| No active orders.                                                                                               |"
        )

    lines += [
        line("-", 110),
        "",
        "=== Customer Order Summary ===",
        line("-", 100),
        "| Customer ID | Total Cups | Products Ordered                                      |",
        line("-", 100),
    ]

    customer_summary = {}
    for row in order_rows:
        customer_id = row["customer_id"]
        customer_summary.setdefault(customer_id, {"cups": 0, "products": []})

        for product_id, quantity in row.get("items", []):
            customer_summary[customer_id]["cups"] += quantity
            name = product_map.get(product_id, {"name": str(product_id)})["name"]
            customer_summary[customer_id]["products"].append(
                f"{name} x{quantity}"
            )

    if customer_summary:
        for customer_id, data in sorted(customer_summary.items()):
            product_text = fit_text(", ".join(data["products"]), 52)
            lines.append(
                f"| {customer_id:<11} | {data['cups']:>10} | {product_text:<52} |"
            )
    else:
        lines.append(
            "| No active customer orders.                                                                         |"
        )

    lines += [
        line("-", 100),
        "",
        "=== Order Summary ===",
        line("-"),
        f"Active Orders : {stats['active']}",
        f"Deleted Orders: {stats['deleted']}",
        f"Free Slots    : {stats['free_slots']}",
        f"Total Sales   : {total_sales:.2f} THB",
        "",
        "Note: Order records come from orders.dat and product names are resolved from products.dat.",
        "",
        "=" * 100,
        "                              End of Order Report",
        "=" * 100,
    ]

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ORDER_REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ORDER_REPORT_FILE


# -----------------------------------------------------------------------------
# Payment Report
# Uses payments.dat + orders.dat
# -----------------------------------------------------------------------------

def generate_payment_report(payments, orders):
    payment_rows = payments.all_active()
    order_map = {row["id"]: row for row in orders.all_active()}
    stats = payments.stats()

    cash_count = sum(row["method"] == "Cash" for row in payment_rows)
    promptpay_count = sum(row["method"] == "PromptPay" for row in payment_rows)
    total_paid = sum(row["amount"] for row in payment_rows)

    lines = _header(
        "Coffee Shop Management System - Payment Report",
        "payments.dat, orders.dat",
        "Payment information from payments.dat with customer/order details from orders.dat",
    )

    lines += [
        "=== Payment Report ===",
        line("-", 120),
        "| Payment ID | Order ID | Customer | Method    | Amount (THB) | Order Total | Payment Date        | Status  |",
        line("-", 120),
    ]

    for row in payment_rows:
        order = order_map.get(row["order_id"])
        customer_id = order["customer_id"] if order else "N/A"
        order_total = order["total"] if order else 0.0

        lines.append(
            f"| {row['id']:<10} | {row['order_id']:<8} | {str(customer_id):<8} | "
            f"{row['method']:<9} | {row['amount']:>12.2f} | {order_total:>11.2f} | "
            f"{row['date']:<19} | {payment_status_text(row['status']):<7} |"
        )

    if not payment_rows:
        lines.append(
            "| No active payments.                                                                                                               |"
        )

    lines += [
        line("-", 120),
        "",
        "=== Payment Summary ===",
        line("-"),
        f"Cash Payments      : {cash_count}",
        f"PromptPay Payments : {promptpay_count}",
        f"Total Paid         : {total_paid:.2f} THB",
        f"Active Payments    : {stats['active']}",
        f"Deleted Payments   : {stats['deleted']}",
        f"Free Slots         : {stats['free_slots']}",
        "",
        "Note: Payment details come from payments.dat; Customer and Order Total are resolved from orders.dat.",
        "",
        "=" * 100,
        "                            End of Payment Report",
        "=" * 100,
    ]

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    PAYMENT_REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return PAYMENT_REPORT_FILE


# =========================
# MENU / APPLICATION
# =========================

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

        print("Invalid choice. Please select 1 or 2.")


def print_products(products):
    rows = products.all_active()

    if not rows:
        print("\nNo products found.")
        return

    print("\n" + "-" * 90)
    print(
        f"{'ID':<8}"
        f"{'Name':<25}"
        f"{'Category':<17}"
        f"{'Price':>10}"
        f"{'Status':>12}"
    )
    print("-" * 90)

    for row in rows:
        status = "Active" if row["status"] == 1 else "Deleted"

        print(
            f"{row['id']:<8}"
            f"{row['name']:<25}"
            f"{row['category']:<17}"
            f"{row['price']:>10.2f}"
            f"{status:>12}"
        )

    print("-" * 90)


def format_order_items(row):
    return ", ".join(
        f"{product_id}x{quantity}"
        for product_id, quantity in row.get("items", [])
    )


def print_orders(orders):
    rows = orders.all_active()

    if not rows:
        print("\nNo orders found.")
        return

    print("\n" + "-" * 110)
    print(
        f"{'ID':<8}"
        f"{'Customer':<12}"
        f"{'Products':<28}"
        f"{'Total':<14}"
        f"{'Date':<20}"
        f"{'Status':>10}"
    )
    print("-" * 110)

    for row in rows:
        status = "Active" if row["status"] == 1 else "Deleted"
        print(
            f"{row['id']:<8}"
            f"{row['customer_id']:<12}"
            f"{format_order_items(row):<28}"
            f"{row['total']:<14.2f}"
            f"{row['date']:<20}"
            f"{status:>10}"
        )

    print("-" * 110)


def print_payments(payments):
    rows = payments.all_active()

    if not rows:
        print("\nNo payments found.")
        return

    print("\n" + "-" * 105)
    print(
        f"{'ID':<10}"
        f"{'Order':<10}"
        f"{'Method':<12}"
        f"{'Amount':<14}"
        f"{'Date':<20}"
        f"{'Status':>10}"
    )
    print("-" * 105)

    for row in rows:
        status = "Paid" if row["status"] == 1 else "Deleted"

        print(
            f"{row['id']:<10}"
            f"{row['order_id']:<10}"
            f"{row['method']:<12}"
            f"{row['amount']:<14.2f}"
            f"{row['date']:<20}"
            f"{status:>10}"
        )

    print("-" * 105)

def add_product(products, activities):
    print("\n--- Add Product ---")
    name = read_text("Name: ")
    category = read_text("Category: ")
    price = read_float("Price (THB): ", 0)

    try:
        record_id = products.add(create_product(name, category, price))
        activities.append((
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ADD",
            "Product",
            record_id,
        ))
        print(f"Product added successfully. ID = {record_id}")
    except ValueError as exc:
        print(f"Error: {exc}")


def add_order(products, orders, payments, activities):
    print("\n--- Add Order ---")
    customer_id = read_int("Customer ID: ", 1)
    items = []
    total = 0.0

    while len(items) < 3:
        print_products(products)
        product_id = read_int("Product ID: ", 1)
        product = products.get(product_id)

        if product is None:
            print("Product ID not found.")
            continue

        quantity = read_int("Quantity: ", 1)

        # If the same product is selected again, combine the quantity.
        found = False
        for index, (pid, qty) in enumerate(items):
            if pid == product_id:
                items[index] = (pid, qty + quantity)
                found = True
                break

        if not found:
            items.append((product_id, quantity))

        total = sum(products.get(pid)["price"] * qty for pid, qty in items)
        print(f"Current Total = {total:.2f} THB")

        if len(items) == 3:
            print("Maximum 3 different products per order.")
            break

        more = input("Add another product? (Y/N): ").strip().upper()
        if more != "Y":
            break

    print("\nOrder Summary")
    for product_id, quantity in items:
        product = products.get(product_id)
        print(f"- {product['name']} x{quantity}")
    print(f"Total = {total:.2f} THB")

    try:
        record_id = orders.add(create_order(customer_id, items, total))

        activities.append((
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ADD",
            "Order",
            record_id,
        ))

        print(f"Order added successfully. ID = {record_id}")

        pay_now = input("Pay now? (Y/N): ").strip().upper()
        if pay_now == "Y":
            add_payment_for_order(record_id, total, payments, activities)

    except ValueError as exc:
        print(f"Error: {exc}")


def add_payment_for_order(order_id, amount, payments, activities):
    print("\n--- Payment ---")
    print(f"Order ID: {order_id}")
    print(f"Amount = {amount:.2f} THB")
    method = choose_payment_method()

    try:
        record_id = payments.add(create_payment(order_id, method, amount))
        activities.append((
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ADD",
            "Payment",
            record_id,
        ))
        print(f"Payment added successfully. ID = {record_id}")
    except ValueError as exc:
        print(f"Error: {exc}")


def add_payment(orders, payments, activities):
    print("\n--- Add Payment ---")
    print_orders(orders)

    order_id = read_int("Order ID: ", 1)
    order = orders.get(order_id)

    if order is None:
        print("Order ID not found.")
        return

    print(f"Amount = {order['total']:.2f} THB")
    method = choose_payment_method()

    try:
        record_id = payments.add(
            create_payment(order_id, method, order["total"])
        )
        activities.append((
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ADD",
            "Payment",
            record_id,
        ))
        print(f"Payment added successfully. ID = {record_id}")
    except ValueError as exc:
        print(f"Error: {exc}")


def update_product(products, activities):
    print("\n--- Update Product ---")
    print_products(products)

    record_id = read_int("Product ID: ", 1)
    old = products.get(record_id)

    if old is None:
        print("Product ID not found.")
        return

    name = read_text(f"Name [{old['name']}]: ")
    category = read_text(f"Category [{old['category']}]: ")
    price = read_float(f"Price [{old['price']:.2f}]: ", 0)

    updated = create_product(name, category, price)
    products.update(record_id, updated)

    activities.append((
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "UPDATE",
        "Product",
        record_id,
    ))
    print("Product updated successfully.")


def update_order(products, orders, activities):
    print("\n--- Update Order ---")
    print_orders(orders)

    record_id = read_int("Order ID: ", 1)
    old = orders.get(record_id)

    if old is None:
        print("Order ID not found.")
        return

    customer_id = read_int(f"Customer ID [{old['customer_id']}]: ", 1)
    items = []

    while len(items) < 3:
        print_products(products)
        product_id = read_int("Product ID: ", 1)
        product = products.get(product_id)
        if product is None:
            print("Product ID not found.")
            continue

        quantity = read_int("Quantity: ", 1)
        items.append((product_id, quantity))

        if len(items) == 3:
            break
        more = input("Add another product? (Y/N): ").strip().upper()
        if more != "Y":
            break

    total = sum(products.get(pid)["price"] * qty for pid, qty in items)
    updated = create_order(customer_id, items, total)
    updated["date"] = old["date"]
    orders.update(record_id, updated)

    activities.append((
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "UPDATE",
        "Order",
        record_id,
    ))
    print("Order updated successfully.")


def update_payment(orders, payments, activities):
    print("\n--- Update Payment ---")
    print_payments(payments)

    record_id = read_int("Payment ID: ", 1)
    old = payments.get(record_id)

    if old is None:
        print("Payment ID not found.")
        return

    order = orders.get(old["order_id"])
    if order is None:
        print("Related order no longer exists.")
        return

    print(f"Order ID: {old['order_id']}")
    print(f"Amount: {order['total']:.2f} THB")
    method = choose_payment_method()

    updated = create_payment(
        old["order_id"],
        method,
        order["total"],
    )
    updated["date"] = old["date"]
    payments.update(record_id, updated)

    activities.append((
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "UPDATE",
        "Payment",
        record_id,
    ))
    print("Payment updated successfully.")


def delete_product(products, orders, activities):
    print("\n--- Delete Product ---")
    print_products(products)

    record_id = read_int("Product ID: ", 1)

    for order in orders.all_active():
        if any(pid == record_id for pid, qty in order.get("items", [])):
            print("Cannot delete: this product is used by an active order.")
            return

    if products.delete(record_id):
        activities.append((
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "DELETE",
            "Product",
            record_id,
        ))
        print("Product deleted successfully.")
    else:
        print("Product ID not found.")


def delete_order(orders, payments, activities):
    print("\n--- Delete Order ---")
    print_orders(orders)

    record_id = read_int("Order ID: ", 1)

    # Delete related payments first, so the order can be removed
    # without leaving orphan payment records.
    related_payments = [
        payment["id"]
        for payment in payments.all_active()
        if payment["order_id"] == record_id
    ]

    for payment_id in related_payments:
        payments.delete(payment_id)
        activities.append((
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "DELETE",
            "Payment",
            payment_id,
        ))

    if orders.delete(record_id):
        activities.append((
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "DELETE",
            "Order",
            record_id,
        ))
        print("Order deleted successfully.")
    else:
        print("Order ID not found.")


def delete_payment(payments, activities):
    print("\n--- Delete Payment ---")
    print_payments(payments)

    record_id = read_int("Payment ID: ", 1)

    if payments.delete(record_id):
        activities.append((
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "DELETE",
            "Payment",
            record_id,
        ))
        print("Payment deleted successfully.")
    else:
        print("Payment ID not found.")


def add_menu(products, orders, payments, activities):
    while True:
        print("\n=== Add Menu ===")
        print("1. Product")
        print("2. Order")
        print("3. Payment")
        print("0. Back")

        choice = input("Choose: ").strip()

        if choice == "1":
            add_product(products, activities)
        elif choice == "2":
            add_order(products, orders, payments, activities)
        elif choice == "3":
            add_payment(orders, payments, activities)
        elif choice == "0":
            return
        else:
            print("Invalid choice.")


def update_menu(products, orders, payments, activities):
    while True:
        print("\n=== Update Menu ===")
        print("1. Product")
        print("2. Order")
        print("3. Payment")
        print("0. Back")

        choice = input("Choose: ").strip()

        if choice == "1":
            update_product(products, activities)
        elif choice == "2":
            update_order(products, orders, activities)
        elif choice == "3":
            update_payment(orders, payments, activities)
        elif choice == "0":
            return
        else:
            print("Invalid choice.")


def delete_menu(products, orders, payments, activities):
    while True:
        print("\n=== Delete Menu ===")
        print("1. Product")
        print("2. Order")
        print("3. Payment")
        print("0. Back")

        choice = input("Choose: ").strip()

        if choice == "1":
            delete_product(products, orders, activities)
        elif choice == "2":
            delete_order(orders, payments, activities)
        elif choice == "3":
            delete_payment(payments, activities)
        elif choice == "0":
            return
        else:
            print("Invalid choice.")


def view_menu(products, orders, payments):
    while True:
        print("\n=== View Menu ===")
        print("1. Products")
        print("2. Orders")
        print("3. Payments")
        print("0. Back")

        choice = input("Choose: ").strip()

        if choice == "1":
            print_products(products)
        elif choice == "2":
            print_orders(orders)
        elif choice == "3":
            print_payments(payments)
        elif choice == "0":
            return
        else:
            print("Invalid choice.")


def main():
    try:
        products = ProductTable()
        orders = OrderTable()
        payments = PaymentTable()
    except ValueError as exc:
        print("\nDATA FILE ERROR")
        print(exc)
        print("Check the .dat files before running the program again.")
        return

    activities = []

    while True:
        print("\n" + "=" * 50)
        print("       COFFEE SHOP MANAGEMENT SYSTEM")
        print("=" * 50)
        print("1. Add")
        print("2. Update")
        print("3. Delete")
        print("4. View")
        print("5. Generate Report")
        print("0. Exit")
        print("=" * 50)

        choice = input("Choose: ").strip()

        if choice == "1":
            add_menu(products, orders, payments, activities)

        elif choice == "2":
            update_menu(products, orders, payments, activities)

        elif choice == "3":
            delete_menu(products, orders, payments, activities)

        elif choice == "4":
            view_menu(products, orders, payments)

        elif choice == "5":
            while True:
                print("\n=== Generate Report ===")
                print("1. Product Report")
                print("2. Order Report")
                print("3. Payment Report")
                print("0. Back")

                report_choice = input("Choose: ").strip()

                if report_choice == "1":
                    path = generate_product_report(products, orders)
                    print(f"Report generated: {path}")

                elif report_choice == "2":
                    path = generate_order_report(products, orders)
                    print(f"Report generated: {path}")

                elif report_choice == "3":
                    path = generate_payment_report(payments, orders)
                    print(f"Report generated: {path}")

                elif report_choice == "0":
                    break

                else:
                    print("Invalid choice.")

        elif choice == "0":
            print("Goodbye.")
            break

        else:
            print("Invalid choice. Please select 0-5.")


if __name__ == "__main__":
    main()
