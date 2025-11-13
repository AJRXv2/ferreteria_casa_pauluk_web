import uuid
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import func
from . import db
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(140), unique=True, nullable=False)
    parent_id = db.Column(UUID(as_uuid=True), db.ForeignKey("categories.id"), nullable=True)
    parent = db.relationship("Category", remote_side=[id], backref="children")
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(200), nullable=False)
    sku = db.Column(db.String(64), unique=True, nullable=True)
    price = db.Column(db.Numeric(12, 2), nullable=True)
    in_stock = db.Column(db.Boolean, nullable=False, default=True)
    featured = db.Column(db.Boolean, nullable=False, default=False)
    short_desc = db.Column(db.String(300))
    long_desc = db.Column(db.Text)
    image_filename = db.Column(db.String(200), nullable=True)

    category_id = db.Column(UUID(as_uuid=True), db.ForeignKey("categories.id"), nullable=True)
    category = db.relationship("Category", backref="products")

    brand_id = db.Column(UUID(as_uuid=True), db.ForeignKey("brands.id"), nullable=True)
    brand = db.relationship("Brand", backref="products")

    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())
    updated_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        db.Index("ix_products_name", "name"),
        db.Index("ix_products_sku", "sku"),
        db.Index("ix_products_featured", "featured"),
    )


class Brand(db.Model):
    __tablename__ = "brands"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(150), unique=True, nullable=False)
    slug = db.Column(db.String(160), unique=True, nullable=False)
    visible = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class SiteInfo(db.Model):
    __tablename__ = "site_info"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_name = db.Column(db.String(160), nullable=False)
    address = db.Column(db.String(300), nullable=False)
    hours = db.Column(db.String(400), nullable=False)
    email = db.Column(db.String(160), nullable=True)
    phone = db.Column(db.String(80), nullable=True)
    instagram = db.Column(db.String(160), nullable=True)
    whatsapp = db.Column(db.String(80), nullable=True)
    consultas_enabled = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Slide(db.Model):
    __tablename__ = "slides"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_filename = db.Column(db.String(200), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)
    visible = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())


class Consulta(db.Model):
    __tablename__ = "consultas"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(160), nullable=False)
    telefono = db.Column(db.String(80), nullable=True)
    consulta = db.Column(db.String(500), nullable=False)
    image1 = db.Column(db.String(200), nullable=True)
    image2 = db.Column(db.String(200), nullable=True)
    image3 = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    read_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.Index("ix_consultas_created_at", "created_at"),
        db.Index("ix_consultas_read_at", "read_at"),
    )
