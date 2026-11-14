"""Deterministic six-file Demo Day source pack (synthetic data only).

The files deliberately exercise every format difference in the brief:

* a title block before the header;
* different English/Chinese aliases;
* shuffled and extra columns;
* thousand-CNY prices and warehouse boxes;
* ISO, DD/MM/YYYY and Excel serial dates;
* a CSV, and a workbook whose data is on the second worksheet.

Exactly six records need human confirmation in the complete 6-file batch:
two missing values, two unit conflicts and two cross-file conflicts.
"""

from __future__ import annotations

import csv
import random
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO, StringIO
from pathlib import Path

from openpyxl import Workbook

SEED = 20261118
EXCEL_EPOCH = date(1899, 12, 30)
BOX_TO_PIECE = 12

CUSTOMERS = (
    ("C-2101", "Aurora Retail"),
    ("C-2102", "Blue Harbor Foods"),
    ("C-2103", "Cedar & Co."),
    ("C-2104", "Delta Works"),
    ("C-2105", "Evergreen Supply"),
    ("C-2106", "Fjord Analytics"),
    ("C-2107", "Greenfield Market"),
    ("C-2108", "Harborline Studio"),
)
PRODUCTS = ("Packaging film", "Recycled carton", "Label roll", "Paper tape", "Shipping insert")
QUANTITY_PATTERN = (24, 36, 12, 48, 60, 24, 36, 12)
PRICE_PATTERN = (24.50, 18.75, 42.00, 15.20, 31.40, 27.60, 12.90, 55.00)

MISSING_CUSTOMER_ID_INDEX = 3
CROSS_CONFLICT_A = 7
CROSS_CONFLICT_B = 19
THOUSAND_CONFLICT = 10
BOX_CONFLICT = 22
MISSING_QUANTITY = 29

FILE1 = "01_orders_header_offset.xlsx"
FILE2 = "02_orders_thousand_cny.xlsx"
FILE3 = "03_orders_shuffled.csv"
FILE4 = "04_orders_second_sheet.xlsx"
FILE5 = "05_orders_warehouse_boxes.xlsx"
FILE6 = "06_orders_chinese_aliases.xlsx"
FILE_ORDER = (FILE1, FILE2, FILE3, FILE4, FILE5, FILE6)


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_orders() -> list[dict]:
    """36 synthetic orders; all quantities are multiples of a 12-piece box."""
    rng = random.Random(SEED)
    orders = []
    for index in range(36):
        customer_id, customer_name = CUSTOMERS[index % len(CUSTOMERS)]
        quantity = QUANTITY_PATTERN[index % len(QUANTITY_PATTERN)]
        price = _money(Decimal(str(PRICE_PATTERN[index % len(PRICE_PATTERN)])) + Decimal(rng.choice((-0.50, 0, 0.25, 0.75))))
        amount = _money(Decimal(quantity) * price)
        order_date = date(2026, 9, 1 + ((index * 5) % 28))
        orders.append(
            {
                "order_id": f"ORD-{3001 + index}",
                "customer_name": customer_name,
                "customer_id": customer_id,
                "quantity": quantity,
                "unit": "件",
                "unit_price": price,
                "amount": amount,
                "order_date": order_date,
                "product": PRODUCTS[index % len(PRODUCTS)],
            }
        )
    return orders


def _selection_1() -> list[int]:
    return [index for index in range(29) if index != BOX_CONFLICT] + [30, 31]


def _selection_2() -> list[int]:
    excluded = {0, MISSING_CUSTOMER_ID_INDEX, CROSS_CONFLICT_A, CROSS_CONFLICT_B,
                BOX_CONFLICT, MISSING_QUANTITY}
    return [index for index in range(36) if index not in excluded]


def _selection_3() -> list[int]:
    excluded = {MISSING_CUSTOMER_ID_INDEX, CROSS_CONFLICT_A, CROSS_CONFLICT_B,
                BOX_CONFLICT, MISSING_QUANTITY}
    return [index for index in range(33) if index not in excluded]


def _selection_4() -> list[int]:
    excluded = {MISSING_CUSTOMER_ID_INDEX, BOX_CONFLICT, MISSING_QUANTITY}
    return [index for index in range(36) if index not in excluded][:30]


def _selection_5() -> list[int]:
    excluded = {MISSING_CUSTOMER_ID_INDEX, CROSS_CONFLICT_A, CROSS_CONFLICT_B,
                MISSING_QUANTITY, 34, 35}
    return [index for index in range(36) if index not in excluded]


def _selection_6() -> list[int]:
    excluded = {MISSING_CUSTOMER_ID_INDEX, CROSS_CONFLICT_A, CROSS_CONFLICT_B,
                BOX_CONFLICT}
    return [index for index in range(36) if index not in excluded][:26]


def _workbook_bytes(workbook: Workbook) -> bytes:
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _friendly_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _excel_serial(value: date) -> int:
    return (value - EXCEL_EPOCH).days


def _price_text(value: Decimal) -> float:
    return float(value)


def _file_1(orders: list[dict]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "September extract"
    sheet["A1"] = "Aurora Retail Group — wholesale order extract"
    sheet["A2"] = "Prepared by the demo data team. This is synthetic data."
    # Header deliberately sits on row 4, after a title block.
    headers = ["order_id", "customer_name", "customer_id", "quantity", "unit",
               "unit_price", "amount", "order_date"]
    sheet.append([])
    sheet.append(headers)
    for index in _selection_1():
        order = orders[index]
        customer_id = "" if index == MISSING_CUSTOMER_ID_INDEX else order["customer_id"]
        price = order["unit_price"]
        amount = order["amount"]
        if index == CROSS_CONFLICT_A:
            price = _money(price + Decimal("2.00"))
            amount = _money(Decimal(order["quantity"]) * price)
        sheet.append(
            [
                order["order_id"],
                order["customer_name"],
                customer_id,
                order["quantity"],
                "件",
                _price_text(price),
                _price_text(amount),
                order["order_date"].isoformat(),
            ]
        )
    for column, width in zip("ABCDEFGH", (13, 24, 14, 10, 8, 12, 12, 14), strict=False):
        sheet.column_dimensions[column].width = width
    return _workbook_bytes(workbook)


def _file_2(orders: list[dict]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Orders (thousand CNY)"
    sheet.append(
        ["Order No.", "Customer", "Customer Code", "Qty", "Unit",
         "Price (CNY '000)", "Total Amount", "Order Date"]
    )
    for index in _selection_2():
        order = orders[index]
        if index == THOUSAND_CONFLICT:
            price = order["unit_price"]  # deliberately entered in CNY, not '000
        else:
            # Keep enough precision: 24.50 CNY is 0.0245 thousand CNY.
            price = order["unit_price"] / Decimal(1000)
        sheet.append(
            [
                order["order_id"],
                order["customer_name"],
                order["customer_id"],
                order["quantity"],
                "件",
                float(price),
                _price_text(order["amount"]),
                order["order_date"].isoformat(),
            ]
        )
    for column, width in zip("ABCDEFGH", (13, 24, 14, 9, 8, 18, 14, 14), strict=False):
        sheet.column_dimensions[column].width = width
    return _workbook_bytes(workbook)


def _file_3(orders: list[dict]) -> bytes:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    # Shuffled columns plus three genuinely unrelated extras.
    headers = ["Sales Region", "Total", "Order No.", "Priority", "Customer Code",
               "Customer", "Reviewer Note", "Qty", "Unit", "Order Date", "Unit Price"]
    writer.writerow(headers)
    for index in _selection_3():
        order = orders[index]
        writer.writerow(
            [
                ["North", "South", "East", "West"][index % 4],
                f"{order['amount']:.2f}",
                order["order_id"],
                "Normal" if index % 3 else "Priority",
                order["customer_id"],
                order["customer_name"],
                "",
                order["quantity"],
                "件",
                order["order_date"].strftime("%Y/%m/%d"),
                f"{order['unit_price']:.2f}",
            ]
        )
    return buffer.getvalue().encode("utf-8")


def _file_4(orders: list[dict]) -> bytes:
    workbook = Workbook()
    cover = workbook.active
    cover.title = "Read me"
    cover["A1"] = "September orders — data tab"
    cover["A2"] = "The order table is on the second sheet."
    cover["A3"] = "All names and identifiers are synthetic."
    sheet = workbook.create_sheet("September Orders")
    sheet["A1"] = "September order lines"
    sheet.append([])
    sheet.append(
        ["Order No.", "Customer Name", "Customer ID", "Qty", "Unit",
         "Unit Price", "Amount", "Order Date"]
    )
    for position, index in enumerate(_selection_4()):
        order = orders[index]
        price = order["unit_price"]
        amount = order["amount"]
        if index == CROSS_CONFLICT_B:
            price = _money(price - Decimal("1.50"))
            amount = _money(Decimal(order["quantity"]) * price)
        date_value = (
            _excel_serial(order["order_date"])
            if position % 2
            else _friendly_date(order["order_date"])
        )
        sheet.append(
            [
                order["order_id"],
                order["customer_name"],
                order["customer_id"],
                order["quantity"],
                "件",
                _price_text(price),
                _price_text(amount),
                date_value,
            ]
        )
    for column, width in zip("ABCDEFGH", (13, 24, 14, 9, 8, 12, 12, 14), strict=False):
        sheet.column_dimensions[column].width = width
    return _workbook_bytes(workbook)


def _file_5(orders: list[dict]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Warehouse"
    sheet.append(["Order No.", "Customer", "Customer Code", "Qty", "Unit",
                  "Unit Price", "Total", "Order Date"])
    for index in _selection_5():
        order = orders[index]
        boxes = order["quantity"] // BOX_TO_PIECE
        if index == BOX_CONFLICT:
            # Quantity is in boxes but the total was calculated as if it were
            # pieces; the rule detects the 12x mismatch and asks a person.
            price = order["unit_price"]
        else:
            price = _money(order["unit_price"] * Decimal(BOX_TO_PIECE))
        sheet.append(
            [
                order["order_id"],
                order["customer_name"],
                order["customer_id"],
                boxes,
                "箱",
                _price_text(price),
                _price_text(order["amount"]),
                _excel_serial(order["order_date"]),
            ]
        )
    for column, width in zip("ABCDEFGH", (13, 24, 14, 9, 8, 12, 12, 14), strict=False):
        sheet.column_dimensions[column].width = width
    return _workbook_bytes(workbook)


def _file_6(orders: list[dict]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "订单"
    sheet.append(["订单编号", "客户名称", "客户编号", "数量", "单位", "单价", "金额", "下单日期"])
    for index in _selection_6():
        order = orders[index]
        quantity = "" if index == MISSING_QUANTITY else order["quantity"]
        sheet.append(
            [
                order["order_id"],
                order["customer_name"],
                order["customer_id"],
                quantity,
                "件",
                _price_text(order["unit_price"]),
                _price_text(order["amount"]),
                order["order_date"].strftime("%Y/%m/%d"),
            ]
        )
    for column, width in zip("ABCDEFGH", (13, 24, 14, 10, 8, 12, 12, 14), strict=False):
        sheet.column_dimensions[column].width = width
    return _workbook_bytes(workbook)


def build_demo_files() -> dict[str, bytes]:
    orders = build_orders()
    return {
        FILE1: _file_1(orders),
        FILE2: _file_2(orders),
        FILE3: _file_3(orders),
        FILE4: _file_4(orders),
        FILE5: _file_5(orders),
        FILE6: _file_6(orders),
    }


def demo_sources() -> list[tuple[str, bytes]]:
    files = build_demo_files()
    return [(name, files[name]) for name in FILE_ORDER]


def write_demo_files(folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, data in build_demo_files().items():
        path = folder / name
        path.write_bytes(data)
        paths.append(path)
    return paths


def customer_registry() -> list[dict[str, str]]:
    regions = ("North", "South", "East", "West")
    tiers = ("standard", "priority")
    return [
        {
            "customer_id": customer_id,
            "customer_name": name,
            "region": regions[index % len(regions)],
            "tier": tiers[index % len(tiers)],
        }
        for index, (customer_id, name) in enumerate(CUSTOMERS)
    ]


def write_customer_registry(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["customer_id", "customer_name", "region", "tier"]
        )
        writer.writeheader()
        writer.writerows(customer_registry())
    return path
