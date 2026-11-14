"""Normalization contract shared by the rule engine, API and exports.

The legacy ``orders-v1`` rule set keeps its seven fields. Multi-source cleanup
adds a provenance-aware, normalized schema. Writing it here means the parser,
the database, the download workbook and the future AI fallback all speak the
same vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RULE_VERSION = "normalize-v1"
MAX_FILES = 6
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_ROWS_PER_FILE = 10_000
MAX_COLUMNS = 256
MAX_HEADER_ROW = 1_000
BOX_TO_PIECE = 12

# The first eight are mapped from source columns. The final two are provenance
# added by FlowRemote and must not be trusted from an uploaded header.
NORMALIZED_FIELDS = (
    "order_id",
    "customer_name",
    "customer_id",
    "quantity",
    "unit",
    "unit_price",
    "amount",
    "order_date",
    "source_file",
    "source_row",
)
MAPPED_FIELDS = NORMALIZED_FIELDS[:8]
REQUIRED_FIELDS = (
    "order_id",
    "customer_name",
    "customer_id",
    "quantity",
    "unit_price",
    "amount",
    "order_date",
)

# Normalised header token -> field. Keys are compared after stripping spaces,
# punctuation and case by ``header_key`` in the parser.
ALIASES: dict[str, tuple[str, ...]] = {
    "order_id": (
        "orderid", "orderno", "ordernumber", "ordercode", "referenceno",
        "订单号", "订单编号", "订单id", "单号", "单据编号",
    ),
    "customer_name": (
        "customername", "customer", "clientname", "client", "buyer", "buyername",
        "accountname", "客户名称", "客户姓名", "客户名", "顾客名称", "买方",
    ),
    "customer_id": (
        "customerid", "customercode", "customerno", "clientid", "clientcode",
        "accountid", "memberid", "客户编号", "客户id", "客户编码", "客户号",
        "顾客编号", "会员编号",
    ),
    "quantity": (
        "quantity", "qty", "units", "unitcount", "count", "pieces", "数量",
        "订单数量", "件数", "数量件", "购买数量",
    ),
    "unit": (
        "unit", "uom", "measure", "unitofmeasure", "包装单位", "单位", "计量单位",
        "规格单位",
    ),
    "unit_price": (
        "unitprice", "price", "rate", "priceperunit", "unitcost", "单价",
        "单位价格", "价格", "售价",
    ),
    "amount": (
        "amount", "total", "totalamount", "ordertotal", "value", "sum", "金额",
        "总金额", "订单金额", "合计", "总额", "订单总额",
    ),
    "order_date": (
        "orderdate", "date", "purchasedate", "bookingdate", "订单日期", "下单日期",
        "日期", "订货日期", "购买日期",
    ),
}

PRICE_THOUSAND_TOKENS = ("千元", "thousand", "'000", "000cny", "cny000", "k cny")
UNIT_ALIASES: dict[str, str] = {
    "件": "piece",
    "个": "piece",
    "只": "piece",
    "pcs": "piece",
    "pc": "piece",
    "piece": "piece",
    "pieces": "piece",
    "unit": "piece",
    "each": "piece",
    "箱": "box",
    "boxes": "box",
    "box": "box",
    "carton": "box",
    "ctn": "box",
    "kg": "kg",
    "公斤": "kg",
    "千克": "kg",
}
UNIT_LABELS = {"piece": "piece", "box": "box", "kg": "kg"}


@dataclass(frozen=True)
class DetectedTable:
    """One readable table located inside an uploaded file."""

    file_type: str
    worksheet: str
    header_row: int
    headers: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...] = field(repr=False)
    row_numbers: tuple[int, ...] = field(repr=False)
    header_index: int = 0
    delimiter: str | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return len(self.headers)


@dataclass(frozen=True)
class ColumnMapping:
    field: str
    index: int
    header: str
    confidence: float
    method: str
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "index": self.index,
            "header": self.header,
            "confidence": self.confidence,
            "method": self.method,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class MappingResult:
    columns: tuple[ColumnMapping, ...]
    price_multiplier: int = 1
    price_evidence: tuple[str, ...] = ()
    unmapped_headers: tuple[str, ...] = ()
    date_order: str = "day-first"

    def by_field(self) -> dict[str, ColumnMapping]:
        return {column.field: column for column in self.columns}

    @property
    def field_count(self) -> int:
        return len({column.field for column in self.columns})

    def as_dict(self) -> dict[str, Any]:
        return {
            "columns": [column.as_dict() for column in self.columns],
            "price_multiplier": self.price_multiplier,
            "price_evidence": list(self.price_evidence),
            "unmapped_headers": list(self.unmapped_headers),
            "date_order": self.date_order,
            "field_count": self.field_count,
        }


@dataclass(frozen=True)
class NormalizedSourceRow:
    order_id: str
    customer_name: str
    customer_id: str
    quantity: int | None
    unit: str
    unit_price: float | None
    amount: float | None
    order_date: str | None
    source_file: str
    source_row: int
    source_file_id: str = ""
    file_ordinal: int = 0
    changes: tuple[dict[str, Any], ...] = ()
    issues: tuple[dict[str, Any], ...] = ()

    def values(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "customer_name": self.customer_name,
            "customer_id": self.customer_id,
            "quantity": self.quantity,
            "unit": self.unit,
            "unit_price": self.unit_price,
            "amount": self.amount,
            "order_date": self.order_date,
            "source_file": self.source_file,
            "source_row": self.source_row,
        }

    def comparison_values(self) -> dict[str, Any]:
        return {
            "customer_name": self.customer_name,
            "customer_id": self.customer_id,
            "quantity": self.quantity,
            "unit": self.unit,
            "unit_price": self.unit_price,
            "amount": self.amount,
            "order_date": self.order_date,
        }
