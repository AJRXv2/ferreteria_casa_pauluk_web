#!/usr/bin/env python3
"""
CLI importer for export ZIP produced by admin export.
Usage:
  python scripts/import_dump.py --file export.zip [--mode upsert|replace|skip] [--images]

Modes:
  upsert (default): update existing records by id or create new ones.
  replace: remove existing products/categories/brands/slides before import (dangerous).
  skip: skip records that already exist.

By default images included in the ZIP are extracted into `static/img/<folder>/...`.
"""
import argparse
import json
import os
import zipfile
import tempfile
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app import create_app, db
from app.models import Category, Brand, Product, ProductImage, Slide, SiteInfo


def _coerce_uuid(val):
    if not val:
        return None
    try:
        return uuid.UUID(str(val))
    except Exception:
        return None


def _parse_decimal(s):
    if s is None:
        return None
    try:
        return Decimal(str(s))
    except (InvalidOperation, ValueError):
        return None


def import_from_zip(zip_path: str, mode: str = "upsert", extract_images: bool = True):
    app = create_app()
    results = {"created": 0, "updated": 0, "skipped": 0, "errors": []}
    with app.app_context():
        if not os.path.exists(zip_path):
            raise FileNotFoundError(zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            if "dump.json" not in zf.namelist():
                raise RuntimeError("dump.json not found in archive")
            dump = json.loads(zf.read("dump.json").decode("utf-8"))
            # extract images
            if extract_images:
                for member in zf.namelist():
                    if member.startswith("images/"):
                        parts = member.split("/")
                        if len(parts) >= 3:
                            folder = parts[1]
                            fname = "/".join(parts[2:])
                            outdir = Path(app.static_folder) / "img" / folder
                            outdir.mkdir(parents=True, exist_ok=True)
                            outpath = outdir / fname
                            with zf.open(member) as srcf, open(outpath, "wb") as outf:
                                outf.write(srcf.read())

            # Optionally replace (delete) current data
            if mode == "replace":
                print("[import] mode=replace: deleting existing products, images, slides, categories, brands")
                try:
                    num_pi = ProductImage.query.delete()
                    num_p = Product.query.delete()
                    num_s = Slide.query.delete()
                    num_c = Category.query.delete()
                    num_b = Brand.query.delete()
                    db.session.commit()
                    print(f"[import] deleted rows: product_images={num_pi}, products={num_p}, slides={num_s}, categories={num_c}, brands={num_b}")
                except Exception as ex:
                    db.session.rollback()
                    raise

            # Categories (two-pass to set parents)
            cats = dump.get("categories", [])
            for c in cats:
                try:
                    cid = _coerce_uuid(c.get("id"))
                    cat = Category.query.get(cid)
                    if cat:
                        if mode == "skip":
                            results["skipped"] += 1
                            continue
                        cat.name = c.get("name")
                        cat.slug = c.get("slug")
                        results["updated"] += 1
                    else:
                        cat = Category(id=cid, name=c.get("name"), slug=c.get("slug"))
                        db.session.add(cat)
                        results["created"] += 1
                except Exception as ex:
                    db.session.rollback()
                    results["errors"].append(f"category {c.get('id')}: {ex}")
            db.session.commit()
            for c in cats:
                try:
                    cid = _coerce_uuid(c.get("id"))
                    parent_id = _coerce_uuid(c.get("parent_id"))
                    cat = Category.query.get(cid)
                    if cat:
                        cat.parent_id = parent_id
                except Exception as ex:
                    results["errors"].append(f"category-parent {c.get('id')}: {ex}")
            db.session.commit()

            # Brands
            brands = dump.get("brands", [])
            for b in brands:
                try:
                    bid = _coerce_uuid(b.get("id"))
                    brand = Brand.query.get(bid)
                    if brand:
                        if mode == "skip":
                            results["skipped"] += 1
                            continue
                        brand.name = b.get("name")
                        brand.slug = b.get("slug")
                        brand.visible = bool(b.get("visible"))
                        results["updated"] += 1
                    else:
                        brand = Brand(id=bid, name=b.get("name"), slug=b.get("slug"), visible=bool(b.get("visible", True)))
                        db.session.add(brand)
                        results["created"] += 1
                except Exception as ex:
                    db.session.rollback()
                    results["errors"].append(f"brand {b.get('id')}: {ex}")
            db.session.commit()

            # Products
            products = dump.get("products", [])
            for p in products:
                try:
                    pid = _coerce_uuid(p.get("id"))
                    prod = Product.query.get(pid)
                    if prod:
                        if mode == "skip":
                            results["skipped"] += 1
                            continue
                        prod.name = p.get("name")
                        prod.sku = p.get("sku")
                        prod.price = _parse_decimal(p.get("price"))
                        prod.in_stock = bool(p.get("in_stock"))
                        prod.featured = bool(p.get("featured"))
                        prod.short_desc = p.get("short_desc")
                        prod.long_desc = p.get("long_desc")
                        prod.image_filename = p.get("image_filename")
                        prod.category_id = _coerce_uuid(p.get("category_id"))
                        prod.brand_id = _coerce_uuid(p.get("brand_id"))
                        results["updated"] += 1
                    else:
                        prod = Product(id=pid, name=p.get("name"), sku=p.get("sku"), price=_parse_decimal(p.get("price")), in_stock=bool(p.get("in_stock", True)), featured=bool(p.get("featured", False)), short_desc=p.get("short_desc"), long_desc=p.get("long_desc"), image_filename=p.get("image_filename"), category_id=_coerce_uuid(p.get("category_id")), brand_id=_coerce_uuid(p.get("brand_id")))
                        db.session.add(prod)
                        results["created"] += 1
                except Exception as ex:
                    db.session.rollback()
                    results["errors"].append(f"product {p.get('id')}: {ex}")
            db.session.commit()

            # Product images
            pim = dump.get("product_images", [])
            for i in pim:
                try:
                    iid = _coerce_uuid(i.get("id"))
                    pi = ProductImage.query.get(iid)
                    if pi:
                        if mode == "skip":
                            results["skipped"] += 1
                            continue
                        pi.product_id = _coerce_uuid(i.get("product_id"))
                        pi.filename = i.get("filename")
                        pi.position = int(i.get("position") or 0)
                        results["updated"] += 1
                    else:
                        pi = ProductImage(id=iid, product_id=_coerce_uuid(i.get("product_id")), filename=i.get("filename"), position=int(i.get("position") or 0))
                        db.session.add(pi)
                        results["created"] += 1
                except Exception as ex:
                    db.session.rollback()
                    results["errors"].append(f"product_image {i.get('id')}: {ex}")
            db.session.commit()

            # Slides
            sls = dump.get("slides", [])
            for s in sls:
                try:
                    sid = _coerce_uuid(s.get("id"))
                    slide = Slide.query.get(sid)
                    if slide:
                        if mode == "skip":
                            results["skipped"] += 1
                            continue
                        slide.image_filename = s.get("image_filename")
                        slide.order = int(s.get("order") or 0)
                        slide.visible = bool(s.get("visible"))
                        results["updated"] += 1
                    else:
                        slide = Slide(id=sid, image_filename=s.get("image_filename"), order=int(s.get("order") or 0), visible=bool(s.get("visible", True)))
                        db.session.add(slide)
                        results["created"] += 1
                except Exception as ex:
                    db.session.rollback()
                    results["errors"].append(f"slide {s.get('id')}: {ex}")
            db.session.commit()

            # Site info
            si = dump.get("site_info")
            if si:
                try:
                    existing = SiteInfo.query.first()
                    if existing:
                        existing.store_name = si.get("store_name")
                        existing.address = si.get("address")
                        existing.hours = si.get("hours")
                        existing.email = si.get("email")
                        existing.phone = si.get("phone")
                        existing.instagram = si.get("instagram")
                        existing.whatsapp = si.get("whatsapp")
                        existing.consultas_enabled = bool(si.get("consultas_enabled", True))
                        results["updated"] += 1
                    else:
                        newsi = SiteInfo(id=_coerce_uuid(si.get("id")), store_name=si.get("store_name"), address=si.get("address") or "", hours=si.get("hours") or "", email=si.get("email"), phone=si.get("phone"), instagram=si.get("instagram"), whatsapp=si.get("whatsapp"), consultas_enabled=bool(si.get("consultas_enabled", True)))
                        db.session.add(newsi)
                        results["created"] += 1
                except Exception as ex:
                    db.session.rollback()
                    results["errors"].append(f"site_info: {ex}")
            db.session.commit()

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import dump ZIP generated by the app export")
    parser.add_argument("--file", "-f", required=True, help="Path to export ZIP")
    parser.add_argument("--mode", choices=("upsert", "replace", "skip"), default="upsert", help="Import mode: upsert (default), replace, skip existing")
    parser.add_argument("--no-images", dest="images", action="store_false", help="Do not extract images from archive")
    args = parser.parse_args()

    res = import_from_zip(args.file, mode=args.mode, extract_images=args.images)
    print("Import results:")
    print(json.dumps(res, indent=2, ensure_ascii=False))
