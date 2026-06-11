"""Seeded one-shot generator for the messy invoice corpus and its ground truth.

Run once (the artifacts are committed and become the source of truth):

    python -m selfcorrect.invoices.generate_corpus --seed 7

Every invoice samples one option per style axis (layout, date format,
currency cue, number style, extra noise) so the 24 documents cover the full
variety matrix. Every document carries at least one decoy amount (shipping,
previous balance, ...) so wrong-total extraction errors are plausible.

Ground truth is exact 2-decimal money arithmetic, computed with Decimal and
rounded half-up at the item level, so for each record:

    quantity * unit_price == amount        (every line item)
    sum(amounts)          == subtotal
    subtotal + tax        == total

All three invariants are asserted for all 24 records before anything is
written; the script crashes if any is violated.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

CENT = Decimal("0.01")
NUM_INVOICES = 24

LAYOUTS = ["table", "prose", "email", "receipt"]
DATE_STYLES = ["iso", "us", "eu", "long"]
CURRENCIES = ["USD", "EUR", "GBP"]
CURRENCY_CUES = ["iso", "symbol"]
NUMBER_STYLES = ["plain", "thousands", "trailing"]
NOISE_KINDS = ["po", "decoy", "legalese", "ocr"]

SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

VENDORS = [
    "Cascade Office Supply Co.",
    "Northwind Logistics GmbH",
    "Brightline Software Ltd.",
    "Harbor & Pine Furnishings",
    "Velocity Cloud Services Inc.",
    "Meridian Industrial Tools",
    "Bluegrass Catering Group",
    "Stonebridge Legal Associates",
    "Apex Electrical Wholesale",
    "Lumen Creative Studio",
    "Granite Peak Consulting LLC",
    "Riverbend Print & Mail",
    "Falcon Freight Systems",
    "Juniper Lab Supplies",
    "Orion Data Networks",
    "Maple Leaf Janitorial Services",
    "Crestview Security Solutions",
    "Tidewater Marine Parts",
    "Silverline Translation Bureau",
    "Foxglove Botanical Wholesale",
    "Ironworks Machining Co.",
    "Summit Ridge Training Partners",
    "Copperfield Stationers",
    "Atlas Geo Survey Services",
]

ADDRESSES = [
    "4821 Mercantile Row, Suite 210, Columbus, OH 43215",
    "Werkstrasse 18, 70565 Stuttgart",
    "9 Harbourside Walk, Bristol BS1 5TT",
    "1170 Sandpiper Ave, Unit 4, Tampa, FL 33607",
    "300 Granary Lane, Floor 2, Madison, WI 53703",
    "Unit 12, Riverside Trade Park, Leeds LS10 1AB",
    "Industriering 7, 4051 Basel",
    "55 Quayside Street, Galway H91 X2F4",
]

ITEM_POOL = [
    "A4 copy paper, 500 sheets",
    "Toner cartridge, black, high yield",
    "Standing desk, oak finish",
    "Ergonomic task chair",
    "Cat6 patch cable, 10m",
    "Wireless presenter remote",
    "Consulting hours, backend integration",
    "On-site training session, half day",
    "Annual SaaS license, Pro tier",
    "Monthly cloud hosting, region EU-1",
    "Industrial shelving unit, 5-tier",
    "Safety goggles, anti-fog, 10-pack",
    "Espresso beans, 1kg, dark roast",
    "Catered lunch, per head",
    "Logo redesign, two revision rounds",
    "Brochure printing, 250 copies",
    "Pallet freight, zone 3",
    "Nitrile gloves, box of 100",
    "Server rack rental, per month",
    "Window cleaning, ground floor",
    "CCTV camera, outdoor dome",
    "Hydraulic hose assembly, 2m",
    "Document translation, per 1000 words",
    "Soil sample analysis, standard panel",
    "USB-C docking station",
    "Whiteboard, magnetic, 120x90cm",
    "Extension lead, 8-way surge protected",
    "First aid kit refill, workplace",
]

DECOY_LABELS = [
    "Amount before discount",
    "Shipping & handling (billed separately)",
    "Previous balance",
    "Estimated annual spend",
    "Credit available on account",
    "Suggested deposit for next order",
]

LEGALESE = [
    "Payment due within 30 days of invoice date. Late payments accrue 1.5% monthly interest.",
    "Please remit payment to the account on file. Thank you for your business.",
    "This invoice was generated electronically and is valid without a signature.",
    "Goods remain the property of the seller until paid in full. E&OE.",
]

TOTAL_LABELS = ["TOTAL", "Total due", "TOTAL DUE", "Amount due", "Balance due"]
SUBTOTAL_LABELS = ["Subtotal", "SUBTOTAL", "Sub-total"]
TAX_RATES = ["0.05", "0.0725", "0.08", "0.0875", "0.19", "0.20"]


@dataclass(slots=True)
class _Doc:
    """Everything needed to render one invoice document deterministically."""

    inv_id: str
    layout: str  # "table" | "prose" | "email" | "receipt"
    invoice_number: str
    vendor: str
    address: str
    date_text: str
    currency: str
    cue: str  # "iso" | "symbol"
    num_style: str  # "plain" | "thousands" | "trailing"
    items: list[tuple[str, int, Decimal, Decimal]]  # (description, qty, unit_price, amount)
    subtotal: Decimal
    tax: Decimal
    tax_rate_pct: str
    total: Decimal
    decoys: list[tuple[str, Decimal]]
    po_number: str | None
    legalese: str | None
    ocr: bool
    total_token: str = ""
    decoy_tokens: list[str] = field(default_factory=list)


def _axis_plan(seed: int, axis: str, options: list[str], n: int) -> list[str]:
    """Balanced, seed-deterministic assignment of axis options across n invoices."""
    plan = (options * (n // len(options) + 1))[:n]
    random.Random(f"{seed}:{axis}").shuffle(plan)
    return plan


def _cents(rng: random.Random, lo: int, hi: int) -> Decimal:
    """A 2-decimal money value drawn uniformly from [lo, hi] cents."""
    return (Decimal(rng.randrange(lo, hi + 1)) / 100).quantize(CENT)


def _fmt_number(value: Decimal, thousands: bool) -> str:
    """The bare numeric token as it appears in the document."""
    return f"{value:,.2f}" if thousands else f"{value:.2f}"


def _fmt_money(value: Decimal, doc: _Doc) -> str:
    """Document-styled money: optional symbol prefix and trailing ISO code."""
    text = _fmt_number(value, doc.num_style == "thousands")
    if doc.cue == "symbol":
        text = SYMBOLS[doc.currency] + text
    if doc.num_style == "trailing":
        text = f"{text} {doc.currency}"
    return text


def _format_date(iso_date: str, style: str) -> str:
    year, month, day = (int(p) for p in iso_date.split("-"))
    if style == "iso":
        return iso_date
    if style == "us":
        return f"{month:02d}/{day:02d}/{year}"
    if style == "eu":
        return f"{day}.{month}.{year}"
    return f"{MONTH_NAMES[month - 1]} {day}, {year}"


def _make_decoys(
    rng: random.Random, count: int, total: Decimal, subtotal: Decimal, tax: Decimal
) -> list[tuple[str, Decimal]]:
    """Plausible money figures that are NOT the answer (all distinct from truth values)."""
    decoys: list[tuple[str, Decimal]] = []
    for label in rng.sample(DECOY_LABELS, count):
        for _ in range(100):
            if label == "Amount before discount":
                factor = Decimal(rng.choice(["1.05", "1.08", "1.10", "1.15"]))
                value = (total * factor).quantize(CENT, ROUND_HALF_UP)
            elif label.startswith("Shipping"):
                value = _cents(rng, 500, 4999)
            else:
                value = _cents(rng, 2500, 999999)
            taken = [total, subtotal, tax] + [v for _, v in decoys]
            if all(abs(value - other) >= Decimal("0.02") for other in taken):
                decoys.append((label, value))
                break
        else:
            raise AssertionError(f"could not draw a distinct decoy for {label!r}")
    return decoys


def _build(seed: int) -> tuple[dict[str, dict[str, Any]], dict[str, _Doc]]:
    """All 24 ground-truth records plus the render plans for their documents."""
    layouts = _axis_plan(seed, "layout", LAYOUTS, NUM_INVOICES)
    date_styles = _axis_plan(seed, "date", DATE_STYLES, NUM_INVOICES)
    currencies = _axis_plan(seed, "currency", CURRENCIES, NUM_INVOICES)
    cues = _axis_plan(seed, "cue", CURRENCY_CUES, NUM_INVOICES)
    num_styles = _axis_plan(seed, "numstyle", NUMBER_STYLES, NUM_INVOICES)
    noises = _axis_plan(seed, "noise", NOISE_KINDS, NUM_INVOICES)
    vendors = list(VENDORS)
    random.Random(f"{seed}:vendors").shuffle(vendors)

    records: dict[str, dict[str, Any]] = {}
    docs: dict[str, _Doc] = {}
    for i in range(1, NUM_INVOICES + 1):
        inv_id = f"inv_{i:03d}"
        rng = random.Random(f"{seed}:{inv_id}:data")

        items: list[tuple[str, int, Decimal, Decimal]] = []
        for description in rng.sample(ITEM_POOL, rng.randint(2, 6)):
            quantity = rng.randint(1, 12)
            unit_price = _cents(rng, 150, 250000)
            # Integer qty x 2dp price is already exact; half-up quantize keeps the
            # item-level rounding rule explicit and the invariants airtight.
            amount = (Decimal(quantity) * unit_price).quantize(CENT, ROUND_HALF_UP)
            items.append((description, quantity, unit_price, amount))

        subtotal = sum((a for _, _, _, a in items), Decimal("0")).quantize(CENT)
        rate = Decimal(rng.choice(TAX_RATES))
        tax = (subtotal * rate).quantize(CENT, ROUND_HALF_UP)
        total = (subtotal + tax).quantize(CENT)
        iso_date = f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        invoice_number = rng.choice(
            [f"INV-2025-{rng.randint(1000, 9999)}", f"2025-{rng.randint(10000, 99999)}",
             f"INV/{rng.randint(100, 999)}/2025"]
        )

        noise = noises[i - 1]
        n_decoys = rng.randint(1, 2) + (1 if noise == "decoy" else 0)
        decoys = _make_decoys(rng, n_decoys, total, subtotal, tax)

        doc = _Doc(
            inv_id=inv_id,
            layout=layouts[i - 1],
            invoice_number=invoice_number,
            vendor=vendors[i - 1],
            address=rng.choice(ADDRESSES),
            date_text=_format_date(iso_date, date_styles[i - 1]),
            currency=currencies[i - 1],
            cue=cues[i - 1],
            num_style=num_styles[i - 1],
            items=items,
            subtotal=subtotal,
            tax=tax,
            tax_rate_pct=f"{rate * 100:.2f}".rstrip("0").rstrip("."),
            total=total,
            decoys=decoys,
            po_number=f"PO-{rng.randint(10000, 99999)}" if noise == "po" else None,
            legalese=rng.choice(LEGALESE) if noise == "legalese" else None,
            ocr=noise == "ocr",
        )
        doc.total_token = _fmt_number(total, doc.num_style == "thousands")
        doc.decoy_tokens = [
            _fmt_number(v, doc.num_style == "thousands") for _, v in decoys
        ]
        docs[inv_id] = doc
        records[inv_id] = {
            "invoice_number": invoice_number,
            "vendor": doc.vendor,
            "date": iso_date,
            "currency": doc.currency,
            "line_items": [
                {
                    "description": d,
                    "quantity": q,
                    "unit_price": float(p),
                    "amount": float(a),
                }
                for d, q, p, a in items
            ],
            "subtotal": float(subtotal),
            "tax": float(tax),
            "total": float(total),
        }
    return records, docs


# --------------------------------------------------------------------------- rendering


def _render_table(doc: _Doc, rng: random.Random) -> list[str]:
    lines = [
        f"INVOICE{' ' * 45}{doc.invoice_number}",
        doc.vendor,
        doc.address,
        "",
        f"Invoice date: {doc.date_text}"
        + (f"        PO Number: {doc.po_number}" if doc.po_number else ""),
    ]
    if doc.cue == "iso":
        lines.append(f"Currency: {doc.currency}")
    lines += ["", f"{'QTY':>4}  {'DESCRIPTION':<42}{'UNIT PRICE':>14}{'AMOUNT':>14}"]
    for description, quantity, unit_price, amount in doc.items:
        lines.append(
            f"{quantity:>4}  {description:<42}"
            f"{_fmt_money(unit_price, doc):>14}{_fmt_money(amount, doc):>14}"
        )
    lines.append("")
    for label, value in doc.decoys:
        lines.append(f"{label:>60}{_fmt_money(value, doc):>14}")
    lines.append(f"{rng.choice(SUBTOTAL_LABELS):>60}{_fmt_money(doc.subtotal, doc):>14}")
    lines.append(f"{'TAX (' + doc.tax_rate_pct + '%)':>60}{_fmt_money(doc.tax, doc):>14}")
    lines.append(f"{rng.choice(TOTAL_LABELS):>60}{_fmt_money(doc.total, doc):>14}")
    if doc.legalese:
        lines += ["", doc.legalese]
    return lines


def _render_prose(doc: _Doc, rng: random.Random) -> list[str]:
    lines = [
        f"Invoice Number: {doc.invoice_number}",
        f"Vendor: {doc.vendor}",
        f"Address: {doc.address}",
        f"Date: {doc.date_text}",
    ]
    if doc.cue == "iso":
        lines.append(f"Currency: {doc.currency}")
    if doc.po_number:
        lines.append(f"PO Number: {doc.po_number}")
    lines.append("")
    for n, (description, quantity, unit_price, amount) in enumerate(doc.items, start=1):
        lines.append(
            f"Item {n}: {description} -- qty {quantity} @ {_fmt_money(unit_price, doc)} each, "
            f"line total {_fmt_money(amount, doc)}"
        )
    lines.append("")
    for label, value in doc.decoys:
        lines.append(f"{label}: {_fmt_money(value, doc)}")
    lines.append(f"{rng.choice(SUBTOTAL_LABELS)}: {_fmt_money(doc.subtotal, doc)}")
    lines.append(f"Tax ({doc.tax_rate_pct}%): {_fmt_money(doc.tax, doc)}")
    lines.append(f"{rng.choice(TOTAL_LABELS)}: {_fmt_money(doc.total, doc)}")
    if doc.legalese:
        lines += ["", doc.legalese]
    return lines


def _render_email(doc: _Doc, rng: random.Random) -> list[str]:
    domain = "".join(c for c in doc.vendor.lower() if c.isalpha())[:18]
    body = [
        "Hello,",
        f"Please find below the invoice details from {doc.vendor}.",
        "",
        f"Invoice no: {doc.invoice_number}",
        f"Date: {doc.date_text}",
    ]
    if doc.cue == "iso":
        body.append(f"All amounts in {doc.currency}.")
    if doc.po_number:
        body.append(f"Your PO: {doc.po_number}")
    body.append("")
    for description, quantity, unit_price, amount in doc.items:
        body.append(
            f"{quantity} x {description} @ {_fmt_money(unit_price, doc)}"
            f" = {_fmt_money(amount, doc)}"
        )
    body.append("")
    for label, value in doc.decoys:
        body.append(f"{label}: {_fmt_money(value, doc)}")
    body.append(f"{rng.choice(SUBTOTAL_LABELS)}: {_fmt_money(doc.subtotal, doc)}")
    body.append(f"Tax @ {doc.tax_rate_pct}%: {_fmt_money(doc.tax, doc)}")
    body.append(f"{rng.choice(TOTAL_LABELS)}: {_fmt_money(doc.total, doc)}")
    if doc.legalese:
        body += ["", doc.legalese]
    body += ["", "Kind regards,", "Accounts Receivable"]
    return [
        f"From: accounts@{domain}.example.com",
        "To: ap@yourcompany.example.com",
        f"Subject: FW: Invoice {doc.invoice_number} -- payment requested",
        "",
        "---------- Forwarded message ----------",
        *[f"> {line}".rstrip() for line in body],
    ]


def _render_receipt(doc: _Doc, rng: random.Random) -> list[str]:
    rule = "-" * 30
    lines = [f"  {doc.vendor}", f"  {rule}", f"  {doc.invoice_number}", f"  {doc.date_text}"]
    if doc.po_number:
        lines.append(f"  PO {doc.po_number}")
    if doc.cue == "iso":
        lines.append(f"  Currency: {doc.currency}")
    lines.append(f"  {rule}")
    for description, quantity, unit_price, amount in doc.items:
        lines.append(f"  {description}")
        lines.append(f"    {quantity} @ {_fmt_money(unit_price, doc)}   {_fmt_money(amount, doc)}")
    lines.append(f"  {rule}")
    for label, value in doc.decoys:
        lines.append(f"  {label}")
        lines.append(f"      {_fmt_money(value, doc)}")
    lines.append(f"  {rng.choice(SUBTOTAL_LABELS)}    {_fmt_money(doc.subtotal, doc)}")
    lines.append(f"  Tax {doc.tax_rate_pct}%    {_fmt_money(doc.tax, doc)}")
    lines.append(f"  {rng.choice(TOTAL_LABELS)}    {_fmt_money(doc.total, doc)}")
    lines.append(f"  {rule}")
    if doc.legalese:
        lines.append(f"  {doc.legalese}")
    return lines


_RENDERERS = {
    "table": _render_table,
    "prose": _render_prose,
    "email": _render_email,
    "receipt": _render_receipt,
}


def _apply_ocr_noise(lines: list[str], doc: _Doc, rng: random.Random) -> list[str]:
    """Doubled spaces and mild letter/digit swaps; never touches the vendor line,
    never touches any line containing a digit (so amounts, dates, and ids survive)."""
    noisy: list[str] = []
    for line in lines:
        new = line
        if doc.vendor not in new:
            interior = [
                j for j in range(1, len(new) - 1) if new[j] == " " and new[j - 1] != " "
            ]
            if interior and rng.random() < 0.35:
                j = rng.choice(interior)
                new = new[:j] + " " + new[j:]
            if not any(c.isdigit() for c in new) and rng.random() < 0.30:
                if "l" in new:
                    new = new.replace("l", "1", 1)
                elif "o" in new:
                    new = new.replace("o", "0", 1)
        noisy.append(new)
    return noisy


def _render(doc: _Doc, seed: int) -> str:
    rng = random.Random(f"{seed}:{doc.inv_id}:render")
    lines = _RENDERERS[doc.layout](doc, rng)
    if doc.ocr:
        lines = _apply_ocr_noise(lines, doc, rng)
    return "\n".join(line.rstrip() for line in lines) + "\n"


# --------------------------------------------------------------------------- invariants


def _as_money(value: Any, where: str) -> Decimal:
    """Decimal via str(); rejects bool (a bool is an int, but never a number here)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AssertionError(f"{where}: expected a number, got {value!r}")
    return Decimal(str(value))


def _assert_invariants(records: dict[str, dict[str, Any]]) -> None:
    """Crash unless all three money invariants hold exactly for every record."""
    for inv_id, rec in records.items():
        subtotal = _as_money(rec["subtotal"], f"{inv_id}.subtotal")
        tax = _as_money(rec["tax"], f"{inv_id}.tax")
        total = _as_money(rec["total"], f"{inv_id}.total")
        running = Decimal("0")
        for k, item in enumerate(rec["line_items"]):
            qty = _as_money(item["quantity"], f"{inv_id}.line_items[{k}].quantity")
            price = _as_money(item["unit_price"], f"{inv_id}.line_items[{k}].unit_price")
            amount = _as_money(item["amount"], f"{inv_id}.line_items[{k}].amount")
            product = (qty * price).quantize(CENT, ROUND_HALF_UP)
            if product != amount:
                raise AssertionError(
                    f"{inv_id}.line_items[{k}]: {qty} * {price} = {product} != {amount}"
                )
            running += amount
        if running != subtotal:
            raise AssertionError(f"{inv_id}: sum(amounts) {running} != subtotal {subtotal}")
        if subtotal + tax != total:
            raise AssertionError(f"{inv_id}: {subtotal} + {tax} != total {total}")


def _verify_corpus(docs: dict[str, _Doc]) -> None:
    """Re-load everything through the public loader and re-check the contract."""
    from selfcorrect.invoices.loader import load_ground_truth, load_tasks

    tasks = load_tasks()
    truth = load_ground_truth()
    expected_ids = [f"inv_{i:03d}" for i in range(1, NUM_INVOICES + 1)]
    if [t.id for t in tasks] != expected_ids:
        raise AssertionError(f"task ids mismatch: {[t.id for t in tasks]}")
    if sorted(truth) != expected_ids:
        raise AssertionError(f"ground-truth ids mismatch: {sorted(truth)}")
    _assert_invariants(truth)
    for task in tasks:
        doc = docs[task.id]
        if doc.total_token not in task.prompt:
            raise AssertionError(f"{task.id}: total token {doc.total_token!r} not in document")
        if not any(token in task.prompt for token in doc.decoy_tokens):
            raise AssertionError(f"{task.id}: no decoy amount found in document")
    n_decoys = sum(len(d.decoy_tokens) for d in docs.values())
    print(f"verified: {len(tasks)} tasks loaded; ground truth has the same {len(truth)} ids")
    print("verified: item, subtotal, and total invariants hold exactly (Decimal re-check)")
    print(f"verified: every document contains its true total and >=1 of {n_decoys} decoys")


# --------------------------------------------------------------------------- entrypoint


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate the invoice corpus + ground truth.")
    parser.add_argument("--seed", type=int, default=7, help="deterministic seed (default: 7)")
    args = parser.parse_args(argv)

    records, docs = _build(args.seed)
    _assert_invariants(records)  # crash BEFORE writing anything

    package_dir = Path(__file__).resolve().parent
    corpus_dir = package_dir / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    for inv_id, doc in docs.items():
        (corpus_dir / f"{inv_id}.txt").write_text(_render(doc, args.seed), encoding="utf-8")
    gt_path = package_dir / "ground_truth.json"
    gt_path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(records)} invoices to {corpus_dir}")
    print(f"wrote ground truth to {gt_path}")

    _verify_corpus(docs)


if __name__ == "__main__":
    main()
