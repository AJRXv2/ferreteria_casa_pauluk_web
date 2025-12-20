#!/usr/bin/env python3
"""
List category slugs and product counts from the local DB.
Usage:
  python scripts/list_category_slugs.py [--limit 10] [--min-products 0]

This script boots the Flask app context and queries the `Category` table.
"""
import argparse
import sys
import os

# Ensure project root is on sys.path so `from app import ...` works when running this script directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import Category, Product

parser = argparse.ArgumentParser()
parser.add_argument("--limit", type=int, default=50)
parser.add_argument("--min-products", type=int, default=0)
args = parser.parse_args()

app = create_app()
with app.app_context():
    qs = Category.query.order_by(Category.name)
    rows = []
    for c in qs:
        count = Product.query.filter_by(category_id=c.id).count()
        if count >= args.min_products:
            rows.append((str(c.id), c.name, c.slug, count))
    rows = rows[: args.limit]
    if not rows:
        print("No categories found")
    else:
        print(f"Found {len(rows)} categories (limit={args.limit}, min-products={args.min_products}):\n")
        for cid, name, slug, cnt in rows:
            print(f"- {slug} (name: {name}) — products: {cnt} — id: {cid}")
