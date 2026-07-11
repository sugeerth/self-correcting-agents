"""The fixture database for the text-to-SQL domain.

One small e-commerce schema with fixed, hand-written rows. ``connect()``
builds it fresh in memory (stdlib sqlite3, no files, fully deterministic),
so validators and scorers can execute candidate SQL safely and repeatably.
"""

from __future__ import annotations

import sqlite3

SCHEMA_SQL = """\
CREATE TABLE customers (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  country TEXT NOT NULL,
  signup_year INTEGER NOT NULL
);
CREATE TABLE products (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  price REAL NOT NULL
);
CREATE TABLE orders (
  id INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  order_date TEXT NOT NULL,
  status TEXT NOT NULL
);
CREATE TABLE order_items (
  order_id INTEGER NOT NULL REFERENCES orders(id),
  product_id INTEGER NOT NULL REFERENCES products(id),
  quantity INTEGER NOT NULL
);
"""

_CUSTOMERS = [
    (1, "Asha Rao", "IN", 2021),
    (2, "Bruno Keller", "DE", 2020),
    (3, "Carmen Diaz", "ES", 2022),
    (4, "Deniz Aydin", "TR", 2021),
    (5, "Elena Petrova", "DE", 2023),
    (6, "Farid Haddad", "FR", 2020),
    (7, "Grace Chen", "US", 2022),
    (8, "Hugo Lindqvist", "SE", 2023),
]

_PRODUCTS = [
    (1, "Trail Backpack 30L", "outdoor", 89.5),
    (2, "Thermal Flask 1L", "outdoor", 24.0),
    (3, "Mechanical Keyboard", "electronics", 129.0),
    (4, "USB-C Dock", "electronics", 79.9),
    (5, "Espresso Grinder", "kitchen", 189.0),
    (6, "Cast Iron Pan", "kitchen", 45.5),
    (7, "Noise-Cancel Headphones", "electronics", 249.0),
    (8, "Camping Stove", "outdoor", 62.0),
]

_ORDERS = [
    (1, 1, "2024-01-14", "delivered"),
    (2, 2, "2024-01-20", "delivered"),
    (3, 3, "2024-02-02", "cancelled"),
    (4, 1, "2024-02-10", "delivered"),
    (5, 5, "2024-02-18", "shipped"),
    (6, 7, "2024-03-01", "delivered"),
    (7, 4, "2024-03-05", "delivered"),
    (8, 2, "2024-03-12", "cancelled"),
    (9, 6, "2024-03-21", "shipped"),
    (10, 7, "2024-04-02", "delivered"),
    (11, 8, "2024-04-09", "delivered"),
    (12, 5, "2024-04-15", "delivered"),
    (13, 3, "2024-04-22", "shipped"),
    (14, 1, "2024-05-03", "delivered"),
]

_ORDER_ITEMS = [
    (1, 1, 1),
    (1, 2, 2),
    (2, 3, 1),
    (2, 4, 1),
    (3, 7, 1),
    (4, 5, 1),
    (4, 6, 2),
    (5, 2, 3),
    (6, 7, 1),
    (6, 3, 1),
    (7, 8, 2),
    (8, 6, 1),
    (9, 1, 1),
    (9, 8, 1),
    (10, 4, 2),
    (11, 5, 1),
    (11, 2, 1),
    (12, 7, 1),
    (12, 4, 1),
    (13, 3, 2),
    (14, 6, 1),
    (14, 2, 2),
    (14, 8, 1),
]


def connect() -> sqlite3.Connection:
    """A fresh in-memory database with the fixture schema and rows."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_SQL)
    conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", _CUSTOMERS)
    conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", _PRODUCTS)
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", _ORDERS)
    conn.executemany("INSERT INTO order_items VALUES (?, ?, ?)", _ORDER_ITEMS)
    conn.commit()
    return conn
