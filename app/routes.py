import uuid
import json
import re
from decimal import Decimal, InvalidOperation
from functools import wraps
import os
import base64
import mimetypes
import random
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, current_app, abort, Response, session, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.datastructures import FileStorage
from .models import Category, Product, User, Brand, SiteInfo, Slide, Consulta, ProductImage
from sqlalchemy.exc import ProgrammingError, OperationalError, IntegrityError
from sqlalchemy import or_
from . import db, slugify

bp = Blueprint("main", __name__)

ALLOWED_PRODUCT_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_REMOTE_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_GALLERY_IMAGES = 10


def _get_bulk_preview_rows():
    return list(session.get("bulk_preview_rows") or [])


def _set_bulk_preview_rows(rows):
    session["bulk_preview_rows"] = rows
    session.modified = True


def _clear_bulk_preview_rows():
    if "bulk_preview_rows" in session:
        session.pop("bulk_preview_rows", None)
        session.modified = True


def _coerce_uuid(value):
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except Exception:
        return None


@bp.route("/")
def index():
    categories = Category.query.order_by(Category.name).all()
    products = Product.query.order_by(Product.created_at.desc()).limit(10).all()
    try:
        featured_products = (
            Product.query.filter_by(featured=True)
            .order_by(Product.updated_at.desc(), Product.created_at.desc())
            .limit(12)
            .all()
        )
    except (ProgrammingError, OperationalError):
        # La columna puede no existir aún si falta correr la migración
        featured_products = []
    site_info = SiteInfo.query.first()
    slides = (
        Slide.query.filter_by(visible=True)
        .order_by(Slide.order.asc(), Slide.created_at.desc())
        .limit(15)
        .all()
    )
    return render_template("index.html", categories=categories, products=products, featured_products=featured_products, site_info=site_info, slides=slides)


@bp.route("/logoferreteria.png")
def logo_file():
    # Sirve el logo que está en la carpeta raíz del proyecto (un nivel arriba del paquete app)
    project_root = os.path.abspath(os.path.join(current_app.root_path, os.pardir))
    logo_path = os.path.join(project_root, "logoferreteria.png")
    if not os.path.exists(logo_path):
        abort(404)
    return send_from_directory(project_root, "logoferreteria.png")


@bp.route("/brand-pattern.svg")
def brand_pattern_svg():
    # Genera un SVG tile en tiempo real con los logos dentro de static/img/brands
    brands_dir = os.path.join(current_app.static_folder, "img", "brands")
    allowed_ext = {".svg", ".png", ".webp", ".jpg", ".jpeg"}
    files = []
    candidate_files = []
    if os.path.isdir(brands_dir):
        for fn in os.listdir(brands_dir):
            ext = os.path.splitext(fn)[1].lower()
            if ext in allowed_ext:
                candidate_files.append(os.path.join(brands_dir, fn))
    # Mezclar para que no salga siempre igual y tomar hasta 20 logos
    random.shuffle(candidate_files)
    max_cells = 20
    files = candidate_files[:max_cells]

    # Si no hay logos, devolvemos un tile vacío transparente mínimo
    if not files:
        svg_empty = """
        <svg xmlns='http://www.w3.org/2000/svg' width='32' height='32' viewBox='0 0 32 32'>
        </svg>
        """
        resp = Response(svg_empty, mimetype="image/svg+xml")
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp

    # Parámetros del tile: una sola fila para hasta 20 logos
    cols = max_cells
    rows = 1
    base_cell = 120
    tile_w = cols * base_cell
    tile_h = base_cell
    cell_w = tile_w // cols
    cell_h = tile_h // rows
    pad = int(min(cell_w, cell_h) * 0.1)
    inner_w = cell_w - 2 * pad
    inner_h = cell_h - 2 * pad

    # Cargar y embedir imágenes como data URI base64
    data_images = []
    for path in files[: cols * rows]:
        mime, _ = mimetypes.guess_type(path)
        if not mime:
            # fallback razonable
            ext = os.path.splitext(path)[1].lower()
            mime = {
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
            }.get(ext, "application/octet-stream")
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        data_images.append((f"data:{mime};base64,{b64}", mime))

    # Si hay menos que celdas, repetir
    while len(data_images) < cols * rows and len(data_images) > 0:
        data_images.append(data_images[len(data_images) % len(files)])

    # Armar contenido SVG
    svg_parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{tile_w}' height='{tile_h}' viewBox='0 0 {tile_w} {tile_h}'>",
    ]

    idx = 0
    for r in range(rows):
        for c in range(cols):
            x = c * cell_w + pad
            y = r * cell_h + pad
            href, _ = data_images[idx]
            # Imágenes con baja opacidad, desaturadas y preservando el aspecto
            svg_parts.append(
                (
                    f"<image x='{x}' y='{y}' width='{inner_w}' height='{inner_h}' href='{href}' "
                    f"preserveAspectRatio='xMidYMid meet' opacity='0.22'/>"
                )
            )
            idx += 1

    svg_parts.append("</svg>")
    svg_str = "".join(svg_parts)
    resp = Response(svg_str, mimetype="image/svg+xml")
    # Evitar cache para que al agregar logos se vea al instante
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@bp.route("/productos/<uuid:product_id>")
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    gallery_images = []
    if product.image_filename:
        gallery_images.append(product.image_filename)
    gallery_images.extend(img.filename for img in product.images)
    seen = set()
    unique_images = []
    for filename in gallery_images:
        if filename and filename not in seen:
            seen.add(filename)
            unique_images.append(filename)
    primary_image = unique_images[0] if unique_images else None
    return render_template(
        "product_detail.html",
        product=product,
        gallery_images=unique_images,
        primary_image=primary_image,
    )


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash("Sesión iniciada", "success")
            next_url = request.args.get("next") or url_for("main.index")
            return redirect(next_url)
        flash("Usuario o contraseña inválidos", "danger")
    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada", "info")
    return redirect(url_for("main.index"))

@bp.route("/admin/site-info/update", methods=["POST"])
@login_required
def site_info_update():
    # Solo admin
    if not getattr(current_user, "is_admin", False):
        flash("No tenés permisos para editar la información del local", "warning")
        return redirect(url_for("main.index"))
    info = SiteInfo.query.first()
    if not info:
        info = SiteInfo(store_name="Ferretería", address="", hours="", email=None, phone=None, instagram=None)
        db.session.add(info)
    info.store_name = (request.form.get("store_name") or "").strip() or info.store_name
    info.address = (request.form.get("address") or "").strip()
    info.hours = (request.form.get("hours") or "").strip()
    info.email = (request.form.get("email") or "").strip() or None
    info.phone = (request.form.get("phone") or "").strip() or None
    info.instagram = (request.form.get("instagram") or "").strip() or None
    info.whatsapp = (request.form.get("whatsapp") or "").strip() or None
    db.session.commit()
    flash("Información del local actualizada", "success")
    return redirect(url_for("main.index"))


@bp.route("/c/<slug>")
def category_page(slug):
    cat = Category.query.filter_by(slug=slug).first_or_404()

    # Parámetros de búsqueda/filtrado/paginación
    q = (request.args.get("q") or "").strip()
    subcat_id_raw = request.args.get("category_id") or None
    brand_id_raw = request.args.get("brand_id") or None
    per_page_raw = request.args.get("per_page") or "10"
    page_raw = request.args.get("page") or "1"
    stock = request.args.get('stock') or ''  # '', 'in', 'out'
    pmin_raw = request.args.get('pmin') or ''
    pmax_raw = request.args.get('pmax') or ''

    # Sanitizar per_page y page
    try:
        per_page = int(per_page_raw)
    except ValueError:
        per_page = 10
    if per_page not in (10, 20, 50):
        per_page = 10
    try:
        page = max(1, int(page_raw))
    except ValueError:
        page = 1

    # IDs de toda la rama de la categoría principal (incluye descendientes)
    tree_ids = _collect_category_ids(cat)

    # Filtro por subcategoría: si seleccionan una subcategoría dentro del árbol, usar su rama
    selected_category_id = None
    if subcat_id_raw:
        try:
            sel = uuid.UUID(subcat_id_raw)
            if sel in tree_ids:
                subcat = Category.query.get(sel)
                if subcat:
                    tree_ids = _collect_category_ids(subcat)
                    selected_category_id = str(sel)
        except Exception:
            pass

    qry = Product.query.filter(Product.category_id.in_(tree_ids))

    # Filtro por marca: solo marcas disponibles en esta rama
    if brand_id_raw:
        try:
            bid = uuid.UUID(brand_id_raw)
            qry = qry.filter(Product.brand_id == bid)
        except Exception:
            pass
    # Filtro stock
    if stock == 'in':
        qry = qry.filter(Product.in_stock.is_(True))
    elif stock == 'out':
        qry = qry.filter(Product.in_stock.is_(False))
    # Filtro por rango de precio
    pmin = _parse_decimal(pmin_raw)
    pmax = _parse_decimal(pmax_raw)
    if pmin is not None:
        qry = qry.filter(Product.price.isnot(None), Product.price >= pmin)
    if pmax is not None:
        qry = qry.filter(Product.price.isnot(None), Product.price <= pmax)

    # Texto (tokens AND, OR entre campos)
    if q:
        tokens = [t for t in q.split() if t]
        for tok in tokens:
            like = f"%{tok}%"
            qry = qry.filter(
                or_(
                    Product.name.ilike(like),
                    Product.short_desc.ilike(like),
                    Product.long_desc.ilike(like),
                    Product.sku.ilike(like),
                )
            )

    qry = qry.order_by(Product.created_at.desc())

    total = qry.count()
    pages = (total + per_page - 1) // per_page if total else 1
    if pages == 0:
        pages = 1
    if page > pages:
        page = pages
    products = qry.offset((page - 1) * per_page).limit(per_page).all()

    # Subcategorías disponibles dentro de la rama (para el select)
    # Incluimos la propia categoría principal y todos sus descendientes inmediatos (se puede profundizar si hay nietos)
    # Construiremos una lista plana de (id, name) recorriendo DFS
    def flatten_tree(root):
        lst = [root]
        stack = list(root.children)
        while stack:
            n = stack.pop()
            lst.append(n)
            if n.children:
                stack.extend(n.children)
        return lst

    all_nodes = [n for n in flatten_tree(cat)]
    subcategory_options = [n for n in all_nodes if n.id in tree_ids]

    # Marcas disponibles en la rama
    brands = (
        Brand.query
        .join(Product, Product.brand_id == Brand.id)
        .filter(Product.category_id.in_(tree_ids))
        .distinct()
        .order_by(Brand.name)
        .all()
    )

    # Breadcrumbs: Inicio > ... > Categoría actual
    crumbs = [("Inicio", url_for('main.index'))]
    # Subir por la cadena de padres
    chain = []
    ptr = cat
    while ptr is not None:
        chain.append(ptr)
        ptr = ptr.parent
    # Agregar los antecesores (excluyendo el actual) con links
    for node in reversed(chain[:-1]):
        crumbs.append((node.name, url_for('main.category_page', slug=node.slug)))
    # Actual sin link
    crumbs.append((cat.name, None))

    return render_template(
        "category.html",
        category=cat,
        products=products,
        q=q,
        brand_id=brand_id_raw,
        category_id=selected_category_id,
        per_page=per_page,
        page=page,
        pages=pages,
        total=total,
        subcategories=subcategory_options,
        brands=brands,
        stock=stock,
        pmin=pmin_raw,
        pmax=pmax_raw,
        breadcrumbs=crumbs,
    )


@bp.route("/contact")
def contact():
    info = SiteInfo.query.first()
    return render_template("contact.html", site_info=info)

@bp.route("/consultas", methods=["GET", "POST"])
def consultas():
    # Chequear si la funcionalidad está habilitada (admins pueden ver aunque esté deshabilitada)
    si_flag = SiteInfo.query.first()
    if si_flag and not getattr(si_flag, 'consultas_enabled', True):
        if not (current_user.is_authenticated and getattr(current_user, 'is_admin', False)):
            abort(404)
    site_info = SiteInfo.query.first()
    dest_email = site_info.email if site_info and site_info.email else None
    sent = False
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        email = (request.form.get("email") or "").strip()
        telefono = (request.form.get("telefono") or "").strip() or None
        consulta = (request.form.get("consulta") or "").strip()
        errors = []
        if not nombre:
            errors.append("El nombre y apellido es obligatorio.")
        if not email:
            errors.append("El email es obligatorio.")
        elif "@" not in email:
            errors.append("Email inválido.")
        if not consulta:
            errors.append("La consulta no puede estar vacía.")
        if len(consulta) > 500:
            errors.append("La consulta supera el máximo de 500 caracteres.")
        if not dest_email:
            errors.append("No hay email configurado del local aún.")
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            # Guardar adjuntos
            img1 = _save_consulta_image(request.files.get("image1"))
            img2 = _save_consulta_image(request.files.get("image2"))
            img3 = _save_consulta_image(request.files.get("image3"))
            c = Consulta(nombre=nombre, email=email, telefono=telefono, consulta=consulta, image1=img1, image2=img2, image3=img3)
            db.session.add(c)
            db.session.commit()
            # Enviar a local
            ok_store = _send_consulta_email(dest_email, nombre, email, telefono, consulta, [f for f in [img1, img2, img3] if f]) if dest_email else False
            # Auto-respuesta al usuario
            ok_reply = _send_auto_reply(email, nombre, site_info.store_name if site_info else "Ferretería", dest_email) if email and dest_email else False
            if ok_store:
                flash("Consulta enviada y registrada. Te responderemos pronto.", "success")
                sent = True
            else:
                flash("La consulta se registró pero no se envió email (revisar SMTP).", "warning")
            if not ok_reply and ok_store:
                flash("No se pudo enviar la confirmación al remitente.", "warning")
    return render_template("consultas.html", site_info=site_info, sent=sent)


@bp.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    code = (request.args.get("code") or "").strip()
    category_id_raw = request.args.get("category_id") or None
    brand_id_raw = request.args.get("brand_id") or None
    per_page_raw = request.args.get("per_page") or "10"
    page_raw = request.args.get("page") or "1"
    stock = request.args.get('stock') or ''
    pmin_raw = request.args.get('pmin') or ''
    pmax_raw = request.args.get('pmax') or ''

    # Sanitizar per_page y page
    try:
        per_page = int(per_page_raw)
    except ValueError:
        per_page = 10
    if per_page not in (10, 20, 50):
        per_page = 10
    try:
        page = max(1, int(page_raw))
    except ValueError:
        page = 1

    qry = Product.query

    # Filtro por categoría (incluye descendientes)
    if category_id_raw:
        try:
            sel_id = uuid.UUID(category_id_raw)
            cat = Category.query.get(sel_id)
        except Exception:
            cat = None
        if cat:
            ids = _collect_category_ids(cat)
            qry = qry.filter(Product.category_id.in_(ids))

    # Filtro por marca
    if brand_id_raw:
        try:
            bid = uuid.UUID(brand_id_raw)
            qry = qry.filter(Product.brand_id == bid)
        except Exception:
            pass

    # Filtro por código (SKU parcial)
    if code:
        like_code = f"%{code}%"
        qry = qry.filter(Product.sku.ilike(like_code))

    # Filtro por stock
    if stock == 'in':
        qry = qry.filter(Product.in_stock.is_(True))
    elif stock == 'out':
        qry = qry.filter(Product.in_stock.is_(False))

    # Filtro por rango de precio
    pmin = _parse_decimal(pmin_raw)
    pmax = _parse_decimal(pmax_raw)
    if pmin is not None:
        qry = qry.filter(Product.price.isnot(None), Product.price >= pmin)
    if pmax is not None:
        qry = qry.filter(Product.price.isnot(None), Product.price <= pmax)

    # Búsqueda por palabras (tokens con AND; OR entre campos)
    if q:
        tokens = [t for t in q.split() if t]
        for tok in tokens:
            like = f"%{tok}%"
            qry = qry.filter(
                or_(
                    Product.name.ilike(like),
                    Product.short_desc.ilike(like),
                    Product.long_desc.ilike(like),
                    Product.sku.ilike(like),
                )
            )

    qry = qry.order_by(Product.created_at.desc())

    total = qry.count()
    pages = (total + per_page - 1) // per_page if total else 1
    if pages == 0:
        pages = 1
    if page > pages:
        page = pages
    items = qry.offset((page - 1) * per_page).limit(per_page).all()

    roots = _category_roots_with_children()
    brands = Brand.query.order_by(Brand.name).all()
    breadcrumbs = [("Inicio", url_for('main.index')), ("Buscar", None)]

    return render_template(
        "search.html",
        q=q,
        code=code,
        category_id=category_id_raw,
        brand_id=brand_id_raw,
        per_page=per_page,
        page=page,
        pages=pages,
        total=total,
        products=items,
        roots=roots,
        brands=brands,
        has_filters=bool(q or code or category_id_raw or brand_id_raw or stock or pmin_raw or pmax_raw),
        stock=stock,
        pmin=pmin_raw,
        pmax=pmax_raw,
        breadcrumbs=breadcrumbs,
    )


@bp.route("/admin")
@login_required
def admin_home():
    return render_template("admin_home.html")


# --- Helpers ---
def admin_required(f):
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if not getattr(current_user, "is_admin", False):
            flash("No tenés permisos de administrador", "warning")
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)
    return wrapper


def _unique_category_slug(slug_base: str, exclude_id=None) -> str:
    """Return a slug unique across categories. If exclude_id is provided,
    that category is ignored (useful when editing).
    """
    slug = slug_base
    i = 1
    while True:
        q = Category.query.filter_by(slug=slug)
        if exclude_id is not None:
            q = q.filter(Category.id != exclude_id)
        exists = q.first() is not None
        if not exists:
            return slug
        slug = f"{slug_base}-{i}"
        i += 1


# --- Categorías (CRUD) ---
@bp.route("/admin/categories")
@admin_required
def categories_admin_list():
    roots = Category.query.filter_by(parent_id=None).order_by(Category.name).all()
    subs = Category.query.filter(Category.parent_id.isnot(None)).order_by(Category.name).all()
    return render_template("admin/categories_list.html", roots=roots, subs=subs)


@bp.route("/admin/categories/new", methods=["GET", "POST"])
@admin_required
def categories_admin_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        parent_id_raw = request.form.get("parent_id") or None
        parent_id = _safe_uuid(parent_id_raw)
        if not name:
            flash("El nombre es obligatorio", "danger")
            return redirect(url_for("main.categories_admin_new"))
        slug = slugify(name)
        slug = _unique_category_slug(slug)
        cat = Category(name=name, slug=slug, parent_id=parent_id)
        db.session.add(cat)
        try:
            db.session.commit()
            flash("Categoría creada", "success")
        except Exception:
            db.session.rollback()
            flash("No se pudo crear la categoría (slug duplicado).", "danger")
        return redirect(url_for("main.categories_admin_list"))
    roots = Category.query.filter_by(parent_id=None).order_by(Category.name).all()
    return render_template(
        "admin/category_form.html",
        roots=roots,
        form_action=url_for("main.categories_admin_new"),
        title="Nueva categoría",
    )


@bp.route("/admin/categories/<uuid:category_id>/edit", methods=["GET", "POST"])
@admin_required
def categories_admin_edit(category_id):
    cat = Category.query.get_or_404(category_id)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        parent_id_raw = request.form.get("parent_id") or None
        parent_id = _safe_uuid(parent_id_raw)
        if not name:
            flash("El nombre es obligatorio", "danger")
            return redirect(url_for("main.categories_admin_edit", category_id=cat.id))
        if parent_id == cat.id:
            flash("La categoría no puede ser su propio padre", "danger")
            return redirect(url_for("main.categories_admin_edit", category_id=cat.id))
        # Evitar ciclos: no permitir asignar como padre un descendiente
        if parent_id is not None:
            try:
                subtree_ids = set(_collect_category_ids(cat))
                subtree_ids.discard(cat.id)
                if parent_id in subtree_ids:
                    flash("No se puede asignar una subcategoría como padre (crearía un ciclo)", "danger")
                    return redirect(url_for("main.categories_admin_edit", category_id=cat.id))
            except Exception:
                pass
        cat.name = name
        base_slug = slugify(name)
        cat.slug = _unique_category_slug(base_slug, exclude_id=cat.id)
        cat.parent_id = parent_id
        try:
            db.session.commit()
            flash("Categoría actualizada", "success")
        except Exception:
            db.session.rollback()
            flash("No se pudo actualizar la categoría (slug duplicado).", "danger")
        return redirect(url_for("main.categories_admin_list"))
    roots = Category.query.filter_by(parent_id=None).order_by(Category.name).all()
    return render_template(
        "admin/category_form.html",
        roots=roots,
        category=cat,
        form_action=url_for("main.categories_admin_edit", category_id=cat.id),
        title="Editar categoría",
    )


@bp.route("/admin/categories/<uuid:category_id>/delete", methods=["POST"])
@admin_required
def categories_admin_delete(category_id):
    cat = Category.query.get_or_404(category_id)
    if cat.children:
        flash("No se puede eliminar: la categoría tiene subcategorías.", "danger")
        return redirect(url_for("main.categories_admin_list"))
    if cat.products:
        flash("No se puede eliminar: la categoría tiene productos.", "danger")
        return redirect(url_for("main.categories_admin_list"))
    db.session.delete(cat)
    db.session.commit()
    flash("Categoría eliminada", "success")
    return redirect(url_for("main.categories_admin_list"))


# --- Productos (CRUD) ---
@bp.route("/admin/products", methods=["GET", "POST"])
@admin_required
def products_admin_list():
    roots = _category_roots_with_children()
    brands = Brand.query.order_by(Brand.name).all()
    preview_rows = _get_bulk_preview_rows()
    if request.method == "GET" and request.args.get("clear_preview") == "1":
        _clear_bulk_preview_rows()
        preview_rows = []

    # Búsqueda y filtros para la sección "Buscar y Editar Productos"
    q = (request.args.get("q") or "").strip()
    category_id_raw = request.args.get("category_id") or None
    brand_id_raw = request.args.get("brand_id") or None
    per_page_raw = request.args.get("per_page") or "20"
    page_raw = request.args.get("page") or "1"

    try:
        per_page = int(per_page_raw)
    except ValueError:
        per_page = 20
    if per_page not in (20, 50, 100):
        per_page = 20
    try:
        page = max(1, int(page_raw))
    except ValueError:
        page = 1

    # Por defecto no mostramos productos hasta que haya algún criterio de búsqueda
    products_page = []
    total = 0
    pages = 1

    has_filters = bool(q or category_id_raw or brand_id_raw)

    if has_filters:
        search_q = (
            Product.query
            .outerjoin(Category, Product.category_id == Category.id)
            .add_entity(Category)
        )

        # Filtro por categoría
        if category_id_raw:
            try:
                cid = uuid.UUID(category_id_raw)
                search_q = search_q.filter(Product.category_id == cid)
            except Exception:
                pass

        # Filtro por marca
        if brand_id_raw:
            try:
                bid = uuid.UUID(brand_id_raw)
                search_q = search_q.filter(Product.brand_id == bid)
            except Exception:
                pass

        # Búsqueda inteligente: combina nombre, descripción y código (SKU)
        if q:
            tokens = [t for t in q.split() if t]
            for tok in tokens:
                like = f"%{tok}%"
                search_q = search_q.filter(
                    or_(
                        Product.name.ilike(like),
                        Product.short_desc.ilike(like),
                        Product.long_desc.ilike(like),
                        Product.sku.ilike(like),
                    )
                )

        search_q = search_q.order_by(Product.created_at.desc())
        total = search_q.count()
        pages = (total + per_page - 1) // per_page if total else 1
        if pages == 0:
            pages = 1
        if page > pages:
            page = pages
        products_page = search_q.offset((page - 1) * per_page).limit(per_page).all()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "preview":
            # Paso 1: generar filas a partir del producto base y cantidad
            base = {
                "name": (request.form.get("name") or "").strip(),
                "sku": (request.form.get("sku") or "").strip(),
                "price": (request.form.get("price") or "").strip(),
                "in_stock": bool(request.form.get("in_stock")),
                "category_id": request.form.get("category_id") or "",
            }
            qty_raw = request.form.get("quantity") or "1"
            try:
                qty = max(1, min(200, int(qty_raw)))
            except ValueError:
                qty = 1
            preview_rows = []
            for i in range(qty):
                preview_rows.append({
                    "name": base["name"],
                    "sku": base["sku"],
                    "price": base["price"],
                    "in_stock": base["in_stock"],
                    "category_id": base["category_id"],
                    "brand_id": request.form.get("brand_id") or "",
                    "image_filename": None,
                    "gallery_images": [],
                })
            _set_bulk_preview_rows(preview_rows)
            # Render sin redirigir, misma página con la tabla editable
            return render_template(
                "admin/products_list.html",
                roots=roots,
                brands=brands,
                preview_rows=preview_rows,
                products=[],
                q=q,
                category_id=category_id_raw,
                brand_id=brand_id_raw,
                per_page=per_page,
                page=page,
                pages=pages,
                total=0,
            )
        elif action == "excel_preview":
            payload = request.form.get("excel_payload") or "[]"
            try:
                rows = json.loads(payload)
            except Exception:
                rows = []
            preview_rows = []
            for row in rows:
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                sku = (row.get("sku") or "").strip() or None
                preview_rows.append({
                    "name": name,
                    "sku": sku,
                    "price": (row.get("price") or "").strip(),
                    "in_stock": bool(row.get("in_stock", True)),
                    "category_id": row.get("category_id") or "",
                    "brand_id": row.get("brand_id") or "",
                    "image_filename": None,
                    "gallery_images": [],
                })
            if not preview_rows:
                flash("No se encontraron productos válidos en el Excel subido.", "warning")
                return redirect(url_for("main.products_admin_list"))
            _set_bulk_preview_rows(preview_rows)
            return render_template(
                "admin/products_list.html",
                roots=roots,
                brands=brands,
                preview_rows=preview_rows,
                products=[],
                q=q,
                category_id=category_id_raw,
                brand_id=brand_id_raw,
                per_page=per_page,
                page=page,
                pages=1,
                total=0,
            )
        elif action == "save":
            # Paso 2: recibir items[i][field] y guardarlos
            delete_mode = request.form.get("delete_mode")  # 'selected', 'all' o None
            try:
                count = int(request.form.get("items_count", "0"))
            except ValueError:
                count = 0

            # Si el usuario eligió "Eliminar todo", no creamos nada
            if delete_mode == "all":
                flash("Se descartaron todos los productos del listado a crear.", "info")
                _clear_bulk_preview_rows()
                return redirect(url_for("main.products_admin_list"))

            created = 0
            for i in range(count):
                # Si se eligió "Eliminar seleccionados" y este ítem está tildado, saltarlo
                if delete_mode == "selected" and request.form.get(f"items[{i}][delete]"):
                    continue

                name = (request.form.get(f"items[{i}][name]") or "").strip()
                if not name:
                    continue
                sku = (request.form.get(f"items[{i}][sku]") or "").strip() or None
                price_raw = (request.form.get(f"items[{i}][price]") or "").strip()
                in_stock = bool(request.form.get(f"items[{i}][in_stock]"))
                cat_id_raw = request.form.get(f"items[{i}][category_id]") or None
                category_id = uuid.UUID(cat_id_raw) if cat_id_raw else None
                price = None
                if price_raw:
                    # Parse formato argentino (miles punto, decimal coma)
                    price_clean = price_raw.replace('.', '').replace(',', '.')
                    try:
                        price = Decimal(price_clean)
                    except (InvalidOperation, AttributeError):
                        price = None
                brand_id_raw = request.form.get(f"items[{i}][brand_id]") or None
                brand_id = uuid.UUID(brand_id_raw) if brand_id_raw else None
                row_meta = preview_rows[i] if preview_rows and i < len(preview_rows) else {}
                gallery_filenames = list(row_meta.get("gallery_images") or [])
                if not gallery_filenames and row_meta and row_meta.get("image_filename"):
                    gallery_filenames.append(row_meta.get("image_filename"))
                if gallery_filenames:
                    gallery_filenames = gallery_filenames[:MAX_GALLERY_IMAGES]
                primary_image = gallery_filenames[0] if gallery_filenames else (row_meta.get("image_filename") if row_meta else None)
                p = Product(
                    name=name,
                    sku=sku,
                    price=price,
                    in_stock=in_stock,
                    category_id=category_id,
                    brand_id=brand_id,
                    image_filename=primary_image,
                )
                db.session.add(p)
                if gallery_filenames:
                    for position, filename in enumerate(gallery_filenames, start=1):
                        db.session.add(ProductImage(product=p, filename=filename, position=position))
                created += 1
            if not created:
                flash("No se crearon productos. Revisá los datos.", "warning")
                _clear_bulk_preview_rows()
                return redirect(url_for("main.products_admin_list"))

            try:
                db.session.commit()
            except IntegrityError as exc:
                db.session.rollback()
                detail = ""
                orig = getattr(exc, "orig", None)
                if orig is not None:
                    diag = getattr(orig, "diag", None)
                    detail = getattr(diag, "detail", None) or str(orig)
                else:
                    detail = str(exc)
                sku_value = None
                if detail:
                    match = re.search(r"\(sku\)=\(([^)]+)\)", detail, re.IGNORECASE)
                    if match:
                        sku_value = match.group(1)
                if sku_value:
                    flash(f"No se pudieron crear los productos porque el SKU {sku_value} ya existe. Editá esa fila y volvé a intentar.", "danger")
                else:
                    flash("No se pudieron crear los productos: algunos SKU ya existen o están repetidos.", "danger")
                return redirect(url_for("main.products_admin_list"))

            flash(f"{created} producto(s) creados", "success")
            _clear_bulk_preview_rows()
        # Tras guardar, recargar búsqueda actualizada (primer página)
        return redirect(url_for("main.products_admin_list"))

    # GET simple: mostrar creador masivo + buscador con filtros y paginación
    return render_template(
        "admin/products_list.html",
        roots=roots,
        brands=brands,
        products=products_page,
        preview_rows=preview_rows,
        q=q,
        category_id=category_id_raw,
        brand_id=brand_id_raw,
        per_page=per_page,
        page=page,
        pages=pages,
        total=total,
    )


@bp.route("/admin/products/bulk/preview/<int:row_index>/edit", methods=["GET", "POST"])
@admin_required
def products_admin_preview_edit(row_index):
    rows = _get_bulk_preview_rows()
    if not rows or row_index < 0 or row_index >= len(rows):
        flash("No se encontró la fila a editar.", "warning")
        return redirect(url_for("main.products_admin_list"))

    current = rows[row_index]
    if request.method == "POST":
        remove_token = request.form.get("remove_gallery_token")
        clear_gallery = request.form.get("clear_gallery")
        if remove_token or clear_gallery:
            gallery_list = list(current.get("gallery_images") or [])
            if not gallery_list and current.get("image_filename"):
                gallery_list.append(current.get("image_filename"))
            if clear_gallery == "1":
                had_images = bool(gallery_list)
                gallery_list = []
                flash("Se eliminaron todas las imágenes del borrador." if had_images else "No había imágenes para eliminar.", "info")
            else:
                origin, identifier = _parse_gallery_remove_token(remove_token)
                removed = False
                if identifier and origin in {"session", "primary"}:
                    next_gallery = [fn for fn in gallery_list if fn != identifier]
                    if len(next_gallery) != len(gallery_list):
                        gallery_list = next_gallery
                        removed = True
                if removed:
                    flash("Imagen eliminada del borrador.", "success")
                else:
                    flash("No se encontró la imagen seleccionada.", "warning")
            limited_gallery = gallery_list[:MAX_GALLERY_IMAGES]
            current["gallery_images"] = limited_gallery
            current["image_filename"] = limited_gallery[0] if limited_gallery else None
            rows[row_index] = current
            _set_bulk_preview_rows(rows)
            return redirect(request.url)
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("El nombre es obligatorio.", "danger")
            return redirect(request.url)
        updated_row = {
            "name": name,
            "sku": (request.form.get("sku") or "").strip(),
            "price": (request.form.get("price") or "").strip(),
            "in_stock": bool(request.form.get("in_stock")),
            "category_id": request.form.get("category_id") or "",
            "brand_id": request.form.get("brand_id") or "",
        }
        existing_gallery = list(current.get("gallery_images") or [])
        if not existing_gallery and current.get("image_filename"):
            existing_gallery.append(current.get("image_filename"))
        gallery_files = request.files.getlist("gallery_images")
        gallery_urls = [u.strip() for u in request.form.getlist("gallery_image_urls[]") if u.strip()]
        added_gallery = 0
        added_from_urls = 0
        failed_urls = []
        slots_left = max(0, MAX_GALLERY_IMAGES - len(existing_gallery))
        for gallery_file in gallery_files:
            if slots_left <= 0:
                break
            if not gallery_file or not getattr(gallery_file, "filename", None):
                continue
            filename = _save_product_image(gallery_file)
            if not filename:
                continue
            existing_gallery.append(filename)
            slots_left -= 1
            added_gallery += 1
        for url_candidate in gallery_urls:
            if slots_left <= 0:
                break
            remote_file = _download_image_from_url(url_candidate)
            if not remote_file:
                failed_urls.append(url_candidate)
                continue
            filename = _save_product_image(remote_file)
            if not filename:
                failed_urls.append(url_candidate)
                continue
            existing_gallery.append(filename)
            slots_left -= 1
            added_from_urls += 1
        if gallery_files and added_gallery == 0 and slots_left == 0:
            flash(f"No se agregaron imágenes de galería: alcanzaste el máximo de {MAX_GALLERY_IMAGES}.", "warning")
        if gallery_urls and added_from_urls == 0 and slots_left == 0:
            flash(f"No se pudieron agregar imágenes desde URL porque alcanzaste el máximo de {MAX_GALLERY_IMAGES}.", "warning")
        if added_from_urls:
            flash(f"Se agregaron {added_from_urls} imagen(es) desde URL.", "success")
        if failed_urls:
            preview = ", ".join(failed_urls[:3])
            extra = len(failed_urls) - 3
            suffix = f" y {extra} más" if extra > 0 else ""
            flash(f"No se pudo subir la imagen desde: {preview}{suffix}", "warning")
        limited_gallery = existing_gallery[:MAX_GALLERY_IMAGES]
        updated_row["gallery_images"] = limited_gallery
        updated_row["image_filename"] = limited_gallery[0] if limited_gallery else current.get("image_filename")
        rows[row_index] = updated_row
        _set_bulk_preview_rows(rows)
        flash("Borrador actualizado.", "success")
        return redirect(url_for("main.products_admin_list"))

    def _prefill_price(value):
        if not value:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        try:
            normalized = raw.replace('.', '').replace(',', '.')
            return Decimal(normalized)
        except (InvalidOperation, AttributeError):
            return None

    gallery_list = list(current.get("gallery_images") or [])
    if not gallery_list and current.get("image_filename"):
        gallery_list.append(current.get("image_filename"))
    gallery_entries = _build_preview_gallery_entries(gallery_list)
    product = SimpleNamespace(
        name=current.get("name", ""),
        sku=current.get("sku") or "",
        price=_prefill_price(current.get("price")),
        in_stock=current.get("in_stock", True),
        short_desc=None,
        long_desc=None,
        category_id=_coerce_uuid(current.get("category_id")),
        brand_id=_coerce_uuid(current.get("brand_id")),
        image_filename=gallery_list[0] if gallery_list else None,
        images=gallery_entries,
    )
    roots = _category_roots_with_children()
    brands = Brand.query.order_by(Brand.name).all()
    return render_template(
        "admin/product_form.html",
        roots=roots,
        brands=brands,
        product=product,
        form_action=url_for("main.products_admin_preview_edit", row_index=row_index),
        title="Editar borrador en detalle",
        cancel_url=url_for("main.products_admin_list"),
        max_gallery_images=MAX_GALLERY_IMAGES,
        gallery_display=gallery_entries,
        gallery_context="preview",
        gallery_context_id=row_index,
        gallery_reorder_endpoint=url_for("main.products_preview_gallery_reorder", row_index=row_index),
    )


@bp.route("/admin/products/bulk/preview/<int:row_index>/gallery-reorder", methods=["POST"])
@admin_required
def products_preview_gallery_reorder(row_index):
    rows = _get_bulk_preview_rows()
    if not rows or row_index < 0 or row_index >= len(rows):
        return jsonify(success=False, message="Borrador no encontrado."), 404

    data = request.get_json(silent=True) or {}
    order = data.get("order") or []
    if not isinstance(order, list) or not order:
        return jsonify(success=False, message="Orden inválido."), 400

    row = rows[row_index]
    gallery_list = list(row.get("gallery_images") or [])
    if not gallery_list and row.get("image_filename"):
        gallery_list.append(row.get("image_filename"))

    current = [str(x) for x in gallery_list]
    requested = [str(x) for x in order]
    if set(requested) != set(current):
        return jsonify(success=False, message="La lista de imágenes no coincide con el borrador actual."), 400

    new_gallery = []
    used = set()
    for item in requested:
        if item in used:
            continue
        new_gallery.append(item)
        used.add(item)

    row["gallery_images"] = new_gallery[:MAX_GALLERY_IMAGES]
    row["image_filename"] = row["gallery_images"][0] if row["gallery_images"] else None
    rows[row_index] = row
    _set_bulk_preview_rows(rows)
    return jsonify(success=True, message="Orden actualizado."), 200


@bp.route("/admin/products/bulk-delete", methods=["POST"])
@admin_required
def products_admin_bulk_delete():
    mode = request.form.get("mode")  # 'selected' o 'all'

    # Parámetros de búsqueda para reconstruir el listado después
    q = (request.form.get("q") or "").strip()
    category_id_raw = request.form.get("category_id") or None
    brand_id_raw = request.form.get("brand_id") or None
    per_page_raw = request.form.get("per_page") or "20"
    page_raw = request.form.get("page") or "1"

    try:
        per_page = int(per_page_raw)
    except ValueError:
        per_page = 20
    if per_page not in (20, 50, 100):
        per_page = 20
    try:
        page = max(1, int(page_raw))
    except ValueError:
        page = 1

    deleted = 0
    if mode == "selected":
        ids = request.form.getlist("product_ids")
        if ids:
            for raw in ids:
                try:
                    pid = uuid.UUID(raw)
                except Exception:
                    continue
                p = Product.query.get(pid)
                if p:
                    db.session.delete(p)
                    deleted += 1
            if deleted:
                db.session.commit()
    elif mode == "all":
        # Borrar todos los productos que coinciden con el filtro actual
        qry = Product.query
        if category_id_raw:
            try:
                cid = uuid.UUID(category_id_raw)
                qry = qry.filter(Product.category_id == cid)
            except Exception:
                pass
        if brand_id_raw:
            try:
                bid = uuid.UUID(brand_id_raw)
                qry = qry.filter(Product.brand_id == bid)
            except Exception:
                pass
        if q:
            tokens = [t for t in q.split() if t]
            for tok in tokens:
                like = f"%{tok}%"
                qry = qry.filter(
                    or_(
                        Product.name.ilike(like),
                        Product.short_desc.ilike(like),
                        Product.long_desc.ilike(like),
                        Product.sku.ilike(like),
                    )
                )
        deleted = qry.delete(synchronize_session=False)
        if deleted:
            db.session.commit()

    if deleted:
        flash(f"Se eliminaron {deleted} producto(s)", "success")
    else:
        flash("No se eliminó ningún producto.", "info")

    return redirect(url_for(
        "main.products_admin_list",
        q=q,
        category_id=category_id_raw,
        brand_id=brand_id_raw,
        per_page=per_page,
        page=page,
    ))


@bp.route("/admin/products/inline-update", methods=["POST"])
@admin_required
def products_admin_inline_update():
    # Actualiza varios productos desde la tabla editable sin salir de la página
    q = (request.form.get("q") or "").strip()
    category_id_raw = request.form.get("category_id") or None
    brand_id_raw = request.form.get("brand_id") or None
    per_page_raw = request.form.get("per_page") or "20"
    page_raw = request.form.get("page") or "1"

    try:
        per_page = int(per_page_raw)
    except ValueError:
        per_page = 20
    if per_page not in (20, 50, 100):
        per_page = 20
    try:
        page = max(1, int(page_raw))
    except ValueError:
        page = 1

    updated = 0

    # Implementación: iterar por productos visibles en la página
    search_q = Product.query
    if category_id_raw:
        try:
            cid = uuid.UUID(category_id_raw)
            search_q = search_q.filter(Product.category_id == cid)
        except Exception:
            pass
    if brand_id_raw:
        try:
            bid = uuid.UUID(brand_id_raw)
            search_q = search_q.filter(Product.brand_id == bid)
        except Exception:
            pass
    if q:
        tokens = [t for t in q.split() if t]
        for tok in tokens:
            like = f"%{tok}%"
            search_q = search_q.filter(
                or_(
                    Product.name.ilike(like),
                    Product.short_desc.ilike(like),
                    Product.long_desc.ilike(like),
                    Product.sku.ilike(like),
                )
            )

    search_q = search_q.order_by(Product.created_at.desc())
    page_products = search_q.offset((page - 1) * per_page).limit(per_page).all()

    for p in page_products:
        prefix = f"items[{p.id}]"
        name = (request.form.get(f"{prefix}[name]") or "").strip()
        sku = (request.form.get(f"{prefix}[sku]") or "").strip() or None
        price_raw = (request.form.get(f"{prefix}[price]") or "").strip()
        in_stock = bool(request.form.get(f"{prefix}[in_stock]"))
        brand_raw = request.form.get(f"{prefix}[brand_id]") or None
        category_raw = request.form.get(f"{prefix}[category_id]") or None
        new_images = request.files.getlist(f"images_{p.id}[]")

        if not name:
            continue

        p.name = name
        p.sku = sku

        if price_raw:
            price_clean = price_raw.replace('.', '').replace(',', '.')
            try:
                p.price = Decimal(price_clean)
            except (InvalidOperation, AttributeError):
                p.price = None
        else:
            p.price = None

        p.in_stock = in_stock

        try:
            p.brand_id = uuid.UUID(brand_raw) if brand_raw else None
        except Exception:
            p.brand_id = None
        try:
            p.category_id = uuid.UUID(category_raw) if category_raw else None
        except Exception:
            p.category_id = None

        # Agregar nuevas imágenes hasta un máximo de 10 por producto
        existing_count = 0
        if p.image_filename:
            existing_count += 1
        existing_count += len(p.images)

        next_position = (p.images[-1].position + 1) if p.images else 1

        for image_file in new_images:
            if not image_file or not image_file.filename:
                continue
            if existing_count >= 10:
                break
            filename = _save_product_image(image_file)
            if not filename:
                continue
            pi = ProductImage(product_id=p.id, filename=filename, position=next_position)
            db.session.add(pi)
            existing_count += 1
            next_position += 1

        updated += 1

    if updated:
        db.session.commit()
        flash(f"Se actualizaron {updated} producto(s)", "success")
    else:
        flash("No se aplicaron cambios.", "info")

    return redirect(url_for(
        "main.products_admin_list",
        q=q,
        category_id=category_id_raw,
        brand_id=brand_id_raw,
        per_page=per_page,
        page=page,
    ))


def _category_roots_with_children():
    return Category.query.filter_by(parent_id=None).order_by(Category.name).all()


def _collect_category_ids(cat: Category):
    """Devuelve el id de la categoría y de todos sus descendientes."""
    ids = [cat.id]
    stack = list(cat.children)
    while stack:
        c = stack.pop()
        ids.append(c.id)
        if c.children:
            stack.extend(c.children)
    return ids

def _parse_decimal(val: str | None):
    """Parsea un string a Decimal soportando formato AR (miles con punto, decimales con coma). Devuelve None si inválido."""
    if not val:
        return None
    try:
        sval = val.replace('.', '').replace(',', '.')
        return Decimal(sval)
    except Exception:
        return None
def _safe_uuid(val):
    """Devuelve UUID o None; tolera valores vacíos, 'None', 'null', 'undefined' y cadenas inválidas sin lanzar excepción."""
    if not val:
        return None
    sval = str(val).strip().lower()
    if sval in {"none", "null", "undefined", ""}:
        return None
    try:
        return uuid.UUID(val)
    except Exception:
        return None

@bp.route('/brands')
def brands_public_list():
    brands = Brand.query.filter_by(visible=True).order_by(Brand.name).all()
    return render_template('brands_list_public.html', brands=brands)

@bp.route('/marca/<slug>')
def brand_page(slug):
    brand = Brand.query.filter_by(slug=slug, visible=True).first_or_404()
    # filtros similares a categoría pero solo dentro de esta marca
    q = (request.args.get('q') or '').strip()
    category_id_raw = request.args.get('category_id') or None
    per_page_raw = request.args.get('per_page') or '10'
    page_raw = request.args.get('page') or '1'
    stock = request.args.get('stock') or ''
    pmin_raw = request.args.get('pmin') or ''
    pmax_raw = request.args.get('pmax') or ''
    try:
        per_page = int(per_page_raw)
    except ValueError:
        per_page = 10
    if per_page not in (10,20,50):
        per_page = 10
    try:
        page = max(1,int(page_raw))
    except ValueError:
        page = 1
    qry = Product.query.filter(Product.brand_id==brand.id)
    # Limit categories list to those used by this brand
    brand_category_ids = [row[0] for row in db.session.query(Product.category_id).filter(Product.brand_id==brand.id, Product.category_id.isnot(None)).distinct().all()]
    if category_id_raw:
        try:
            cid = uuid.UUID(category_id_raw)
            if cid in brand_category_ids:
                qry = qry.filter(Product.category_id==cid)
        except Exception:
            pass
    # Stock filter
    if stock == 'in':
        qry = qry.filter(Product.in_stock.is_(True))
    elif stock == 'out':
        qry = qry.filter(Product.in_stock.is_(False))
    # Price range
    pmin = _parse_decimal(pmin_raw)
    pmax = _parse_decimal(pmax_raw)
    if pmin is not None:
        qry = qry.filter(Product.price.isnot(None), Product.price >= pmin)
    if pmax is not None:
        qry = qry.filter(Product.price.isnot(None), Product.price <= pmax)
    if q:
        tokens = [t for t in q.split() if t]
        for tok in tokens:
            like = f"%{tok}%"
            qry = qry.filter(or_(Product.name.ilike(like), Product.short_desc.ilike(like), Product.long_desc.ilike(like), Product.sku.ilike(like)))
    qry = qry.order_by(Product.created_at.desc())
    total = qry.count()
    pages = (total + per_page - 1)//per_page if total else 1
    if page>pages: page=pages
    products = qry.offset((page-1)*per_page).limit(per_page).all()
    categories = Category.query.filter(Category.id.in_(brand_category_ids)).order_by(Category.name).all()
    breadcrumbs = [("Inicio", url_for('main.index')), ("Marcas", url_for('main.brands_public_list')), (brand.name, None)]
    return render_template('brand.html', brand=brand, products=products, q=q, category_id=category_id_raw, per_page=per_page, page=page, pages=pages, total=total, categories=categories, stock=stock, pmin=pmin_raw, pmax=pmax_raw, breadcrumbs=breadcrumbs)

@bp.route('/api/products')
def api_products_by_ids():
    ids_raw = request.args.get('ids') or ''
    parts = [p for p in ids_raw.split(',') if p]
    uuids = []
    for p in parts[:30]:
        try:
            uuids.append(uuid.UUID(p))
        except Exception:
            pass
    if not uuids:
        return {"items": []}
    items = Product.query.filter(Product.id.in_(uuids)).all()
    def serialize(p: Product):
        return {
            "id": str(p.id),
            "name": p.name,
            "sku": p.sku,
            "price": float(p.price) if p.price is not None else None,
            "image": p.image_filename,
            "featured": p.featured,
        }
    return {"items": [serialize(p) for p in items]}

def _send_consulta_email(dest: str, nombre: str, email: str, telefono: str | None, consulta: str, attachments: list[str] | None = None) -> bool:
    """Envía la consulta por SMTP. Devuelve True si se envió, False si falló."""
    import smtplib
    from email.message import EmailMessage
    host = current_app.config.get("SMTP_HOST")
    port = current_app.config.get("SMTP_PORT")
    user = current_app.config.get("SMTP_USER")
    password = current_app.config.get("SMTP_PASSWORD")
    use_tls = current_app.config.get("SMTP_USE_TLS")
    use_ssl = current_app.config.get("SMTP_USE_SSL")
    if not host or not port:
        current_app.logger.warning("SMTP no configurado (host/port faltan)")
        return False
    msg = EmailMessage()
    msg["Subject"] = f"Consulta web - {nombre}"
    msg["From"] = user or dest
    msg["To"] = dest
    body = [
        f"Nombre y Apellido: {nombre}",
        f"Email remitente: {email}",
    ]
    if telefono:
        body.append(f"Teléfono: {telefono}")
    body.append("---")
    body.append(consulta)
    if attachments:
        body.append("\nAdjuntos:")
        for fn in attachments:
            body.append(f" - {fn}")
    msg.set_content("\n".join(body))
    current_app.logger.debug(f"Preparando envío SMTP dest={dest} host={host} port={port} tls={use_tls} ssl={use_ssl} user={'set' if user else 'none'} attach_count={len(attachments) if attachments else 0}")
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=15) as s:
                try:
                    s.ehlo()
                except Exception:
                    pass
                if user and password:
                    s.login(user, password)
                if attachments:
                    for fn in attachments:
                        try:
                            apath = os.path.join(current_app.static_folder, 'img', 'consultas', fn)
                            with open(apath, 'rb') as f:
                                data = f.read()
                            import mimetypes
                            ctype, _ = mimetypes.guess_type(apath)
                            if not ctype:
                                ctype = 'application/octet-stream'
                            maintype, subtype = ctype.split('/', 1)
                            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=fn)
                        except Exception as _e:
                            current_app.logger.warning(f"No se pudo adjuntar {fn}: {_e}")
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                try:
                    s.ehlo()
                except Exception:
                    pass
                if use_tls:
                    try:
                        s.starttls()
                        s.ehlo()
                    except Exception as _tls_e:
                        current_app.logger.error(f"Fallo STARTTLS: {_tls_e}")
                        raise
                if user and password:
                    s.login(user, password)
                if attachments:
                    for fn in attachments:
                        try:
                            apath = os.path.join(current_app.static_folder, 'img', 'consultas', fn)
                            with open(apath, 'rb') as f:
                                data = f.read()
                            import mimetypes
                            ctype, _ = mimetypes.guess_type(apath)
                            if not ctype:
                                ctype = 'application/octet-stream'
                            maintype, subtype = ctype.split('/', 1)
                            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=fn)
                        except Exception as _e:
                            current_app.logger.warning(f"No se pudo adjuntar {fn}: {_e}")
                s.send_message(msg)
        current_app.logger.info("Email de consulta enviado correctamente")
        return True
    except Exception as e:
        current_app.logger.error(f"Error enviando consulta: {e}")
        return False
def _send_auto_reply(dest_user: str, nombre: str, store_name: str, store_email: str | None) -> bool:
    """Envía una confirmación automática al remitente."""
    import smtplib
    from email.message import EmailMessage
    host = current_app.config.get("SMTP_HOST")
    port = current_app.config.get("SMTP_PORT")
    user = current_app.config.get("SMTP_USER")
    password = current_app.config.get("SMTP_PASSWORD")
    use_tls = current_app.config.get("SMTP_USE_TLS")
    use_ssl = current_app.config.get("SMTP_USE_SSL")
    if not host or not port or not dest_user:
        return False
    msg = EmailMessage()
    msg["Subject"] = f"Recibimos tu consulta - {store_name}"
    msg["From"] = user or store_email or dest_user
    msg["To"] = dest_user
    msg.set_content(
        f"Hola {nombre},\n\nRecibimos tu consulta y nos pondremos en contacto a la brevedad.\n\nSaludos,\n{store_name}"
    )
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=10) as s:
                if user and password:
                    s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=10) as s:
                if use_tls:
                    s.starttls()
                if user and password:
                    s.login(user, password)
                s.send_message(msg)
        return True
    except Exception as e:
        current_app.logger.warning(f"Auto-reply fallo: {e}")
        return False

def _save_consulta_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    allowed = {'.jpg', '.jpeg', '.png', '.webp'}
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in allowed:
        return None
    fname = f"{uuid.uuid4().hex}{ext}"
    dest_dir = _resolved_img_subdir('consultas')
    os.makedirs(dest_dir, exist_ok=True)
    file_storage.save(os.path.join(dest_dir, fname))
    return fname

@bp.route('/admin/consultas')
@admin_required
def consultas_admin_list():
    items = Consulta.query.order_by(Consulta.read_at.isnot(None), Consulta.created_at.desc()).all()
    si = SiteInfo.query.first()
    consultas_enabled = True if not si else getattr(si, 'consultas_enabled', True)
    return render_template('admin/consultas_list.html', consultas=items, consultas_enabled=consultas_enabled)

@bp.route('/admin/consultas/<uuid:consulta_id>')
@admin_required
def consultas_admin_detail(consulta_id):
    c = Consulta.query.get_or_404(consulta_id)
    if c.read_at is None:
        from datetime import datetime
        c.read_at = datetime.utcnow()
        db.session.commit()
    si = SiteInfo.query.first()
    consultas_enabled = True if not si else getattr(si, 'consultas_enabled', True)
    return render_template('admin/consulta_detail.html', consulta=c, consultas_enabled=consultas_enabled)

@bp.route('/admin/consultas/<uuid:consulta_id>/delete', methods=['POST'])
@admin_required
def consultas_admin_delete(consulta_id):
    c = Consulta.query.get_or_404(consulta_id)
    db.session.delete(c)
    db.session.commit()
    flash('Consulta eliminada', 'success')
    return redirect(url_for('main.consultas_admin_list'))

@bp.route('/admin/consultas/toggle', methods=['POST'])
@admin_required
def consultas_toggle():
    si = SiteInfo.query.first()
    if not si:
        flash('No existe SiteInfo para aplicar cambio', 'danger')
        return redirect(url_for('main.consultas_admin_list'))
    current = bool(getattr(si, 'consultas_enabled', True))
    si.consultas_enabled = not current
    db.session.commit()
    flash('Consultas habilitadas' if si.consultas_enabled else 'Consultas deshabilitadas', 'success')
    return redirect(url_for('main.consultas_admin_list'))


# --- Marcas (CRUD) ---
@bp.route("/admin/brands")
@admin_required
def brands_admin_list():
    brands = Brand.query.order_by(Brand.name).all()
    return render_template("admin/brands_list.html", brands=brands)


@bp.route("/admin/brands/new", methods=["GET", "POST"])
@admin_required
def brands_admin_new():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        visible = bool(request.form.get("visible"))
        if not name:
            flash("El nombre es obligatorio", "danger")
            return redirect(url_for("main.brands_admin_new"))
        slug = slugify(name)
        b = Brand(name=name, slug=slug, visible=visible)
        db.session.add(b)
        db.session.commit()
        flash("Marca creada", "success")
        return redirect(url_for("main.brands_admin_list"))
    return render_template("admin/brand_form.html", form_action=url_for("main.brands_admin_new"), title="Nueva marca")


@bp.route("/admin/brands/<uuid:brand_id>/edit", methods=["GET", "POST"])
@admin_required
def brands_admin_edit(brand_id):
    b = Brand.query.get_or_404(brand_id)
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        visible = bool(request.form.get("visible"))
        if not name:
            flash("El nombre es obligatorio", "danger")
            return redirect(url_for("main.brands_admin_edit", brand_id=b.id))
        b.name = name
        b.slug = slugify(name)
        b.visible = visible
        db.session.commit()
        flash("Marca actualizada", "success")
        return redirect(url_for("main.brands_admin_list"))
    return render_template("admin/brand_form.html", brand=b, form_action=url_for("main.brands_admin_edit", brand_id=b.id), title="Editar marca")


@bp.route("/admin/brands/<uuid:brand_id>/toggle", methods=["POST"])
@admin_required
def brands_admin_toggle(brand_id):
    b = Brand.query.get_or_404(brand_id)
    b.visible = not b.visible
    db.session.commit()
    flash("Estado de visibilidad actualizado", "success")
    return redirect(url_for("main.brands_admin_list"))


@bp.route("/admin/brands/<uuid:brand_id>/delete", methods=["POST"])
@admin_required
def brands_admin_delete(brand_id):
    b = Brand.query.get_or_404(brand_id)
    if b.products:
        flash("No se puede eliminar: la marca tiene productos asociados.", "danger")
        return redirect(url_for("main.brands_admin_list"))
    db.session.delete(b)
    db.session.commit()
    flash("Marca eliminada", "success")
    return redirect(url_for("main.brands_admin_list"))


@bp.route("/admin/products/new", methods=["GET", "POST"])
@admin_required
def products_admin_new():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        sku = (request.form.get("sku") or "").strip() or None
        price_raw = (request.form.get("price") or "").strip()
        in_stock = bool(request.form.get("in_stock"))
        short_desc = (request.form.get("short_desc") or "").strip() or None
        long_desc = (request.form.get("long_desc") or "").strip() or None
        category_id = _coerce_uuid(request.form.get("category_id"))
        brand_id = _coerce_uuid(request.form.get("brand_id"))

        if not name:
            flash("El nombre es obligatorio", "danger")
            return redirect(url_for("main.products_admin_new"))
        price = None
        if price_raw:
            price_raw_clean = price_raw.replace('.', '').replace(',', '.')
            try:
                price = Decimal(price_raw_clean)
            except (InvalidOperation, AttributeError):
                flash("Precio inválido", "danger")
                return redirect(url_for("main.products_admin_new"))

        gallery_files = request.files.getlist("gallery_images")
        gallery_urls = [u.strip() for u in request.form.getlist("gallery_image_urls[]") if u.strip()]

        p = Product(
            name=name,
            sku=sku,
            price=price,
            in_stock=in_stock,
            short_desc=short_desc,
            long_desc=long_desc,
            category_id=category_id,
            brand_id=brand_id,
            image_filename=None,
        )
        db.session.add(p)
        db.session.flush()
        added_gallery, failed_urls = _append_gallery_images(p, gallery_files, gallery_urls)
        skipped_gallery = getattr(p, "_skipped_gallery_due_limit", 0)
        _sync_primary_image_from_gallery(p)
        try:
            db.session.commit()
            if added_gallery:
                flash(f"Se agregaron {added_gallery} imagen(es) a la galería.", "info")
            if skipped_gallery:
                flash(f"Se alcanzó el máximo de {MAX_GALLERY_IMAGES} imágenes de galería. {skipped_gallery} archivo(s) no se cargaron.", "warning")
            if failed_urls:
                preview = ", ".join(failed_urls[:3])
                extra = len(failed_urls) - 3
                suffix = f" y {extra} más" if extra > 0 else ""
                flash(f"No se pudieron importar estas URL: {preview}{suffix}.", "warning")
            flash("Producto creado", "success")
        except IntegrityError as exc:
            db.session.rollback()
            detail = ""
            orig = getattr(exc, "orig", None)
            if orig is not None:
                diag = getattr(orig, "diag", None)
                detail = getattr(diag, "detail", None) or str(orig)
            else:
                detail = str(exc)
            sku_value = None
            if detail:
                m = re.search(r"\(sku\)=\(([^)]+)\)", detail, re.IGNORECASE)
                if m:
                    sku_value = m.group(1)
            if sku_value:
                flash(f"No se pudo crear el producto: el SKU '{sku_value}' ya existe.", "danger")
            else:
                flash("No se pudo crear el producto por un conflicto de integridad en la base de datos.", "danger")
        return redirect(url_for("main.products_admin_list"))

    roots = _category_roots_with_children()
    brands = Brand.query.order_by(Brand.name).all()
    prefill = None
    if request.method == "GET":
        name_arg = (request.args.get("name") or "").strip()
        sku_arg = (request.args.get("sku") or "").strip()
        price_arg = (request.args.get("price") or "").strip()
        cat_arg = (request.args.get("category_id") or "").strip()
        brand_arg = (request.args.get("brand_id") or "").strip()
        in_stock_arg = request.args.get("in_stock")

        price_prefill = None
        if price_arg:
            price_clean = price_arg.replace('.', '').replace(',', '.')
            try:
                price_prefill = Decimal(price_clean)
            except (InvalidOperation, AttributeError):
                price_prefill = None

        prefill_candidates = [name_arg, sku_arg, price_arg, cat_arg, brand_arg, in_stock_arg]
        if any(prefill_candidates):
            in_stock_prefill = True
            if in_stock_arg is not None:
                in_stock_prefill = str(in_stock_arg).lower() in {"1", "true", "on", "yes"}
            prefill = SimpleNamespace(
                name=name_arg or "",
                sku=sku_arg or None,
                price=price_prefill,
                category_id=_coerce_uuid(cat_arg),
                brand_id=_coerce_uuid(brand_arg),
                in_stock=in_stock_prefill,
                short_desc=None,
                long_desc=None,
                image_filename=None,
                images=[],
            )
    return render_template(
        "admin/product_form.html",
        roots=roots,
        brands=brands,
        product=prefill,
        form_action=url_for("main.products_admin_new"),
        title="Nuevo producto",
        max_gallery_images=MAX_GALLERY_IMAGES,
        gallery_context="none",
        gallery_context_id="",
    )


@bp.route("/admin/products/<uuid:product_id>/edit", methods=["GET", "POST"])
@admin_required
def products_admin_edit(product_id):
    p = Product.query.get_or_404(product_id)
    if request.method == "POST":
        remove_token = request.form.get("remove_gallery_token")
        clear_gallery = request.form.get("clear_gallery")
        if remove_token or clear_gallery:
            removed_any = False
            level = "info"
            message = ""
            if clear_gallery == "1":
                removed_any = bool(p.image_filename or p.images)
                p.image_filename = None
                for img in list(p.images):
                    db.session.delete(img)
                message = "Se eliminaron todas las imágenes de la galería." if removed_any else "El producto no tiene imágenes para eliminar."
                level = "success" if removed_any else "info"
            else:
                origin, identifier = _parse_gallery_remove_token(remove_token)
                if origin == "gallery" and identifier:
                    target = next((img for img in list(p.images) if str(img.id) == identifier), None)
                    if target:
                        db.session.delete(target)
                        removed_any = True
                elif origin == "primary" and identifier:
                    if p.image_filename == identifier:
                        p.image_filename = None
                        removed_any = True
                    # También quitamos cualquier registro de galería con ese filename por consistencia
                    for img in list(p.images):
                        if img.filename == identifier:
                            db.session.delete(img)
                            removed_any = True
                            break
                message = "Imagen eliminada del producto." if removed_any else "No se encontró la imagen seleccionada."
                level = "success" if removed_any else "warning"
            if removed_any:
                _sync_primary_image_from_gallery(p)
            db.session.commit()
            flash(message, level)
            return redirect(request.url)
        name = (request.form.get("name") or "").strip()
        sku = (request.form.get("sku") or "").strip() or None
        price_raw = (request.form.get("price") or "").strip()
        in_stock = bool(request.form.get("in_stock"))
        short_desc = (request.form.get("short_desc") or "").strip() or None
        long_desc = (request.form.get("long_desc") or "").strip() or None
        cat_id_raw = request.form.get("category_id") or None
        category_id = uuid.UUID(cat_id_raw) if cat_id_raw else None
        brand_id_raw = request.form.get("brand_id") or None
        brand_id = uuid.UUID(brand_id_raw) if brand_id_raw else None

        if not name:
            flash("El nombre es obligatorio", "danger")
            return redirect(url_for("main.products_admin_edit", product_id=p.id))
        price = None
        if price_raw:
            price_raw_clean = price_raw.replace('.', '').replace(',', '.')
            try:
                price = Decimal(price_raw_clean)
            except (InvalidOperation, AttributeError):
                flash("Precio inválido", "danger")
                return redirect(url_for("main.products_admin_edit", product_id=p.id))

        p.name = name
        p.sku = sku
        p.price = price
        p.in_stock = in_stock
        p.short_desc = short_desc
        p.long_desc = long_desc
        p.category_id = category_id
        p.brand_id = brand_id

        gallery_files = request.files.getlist("gallery_images")
        gallery_urls = [u.strip() for u in request.form.getlist("gallery_image_urls[]") if u.strip()]
        added_gallery, failed_urls = _append_gallery_images(p, gallery_files, gallery_urls)
        skipped_gallery = getattr(p, "_skipped_gallery_due_limit", 0)
        _sync_primary_image_from_gallery(p)
        try:
            db.session.commit()
            if added_gallery:
                flash(f"Se agregaron {added_gallery} imagen(es) a la galería.", "info")
            if skipped_gallery:
                flash(f"Se alcanzó el máximo de {MAX_GALLERY_IMAGES} imágenes de galería. {skipped_gallery} archivo(s) no se cargaron.", "warning")
            if failed_urls:
                preview = ", ".join(failed_urls[:3])
                extra = len(failed_urls) - 3
                suffix = f" y {extra} más" if extra > 0 else ""
                flash(f"No se pudieron importar estas URL: {preview}{suffix}.", "warning")
            flash("Producto actualizado", "success")
        except IntegrityError as exc:
            db.session.rollback()
            detail = ""
            orig = getattr(exc, "orig", None)
            if orig is not None:
                diag = getattr(orig, "diag", None)
                detail = getattr(diag, "detail", None) or str(orig)
            else:
                detail = str(exc)
            sku_value = None
            if detail:
                m = re.search(r"\(sku\)=\(([^)]+)\)", detail, re.IGNORECASE)
                if m:
                    sku_value = m.group(1)
            if sku_value:
                flash(f"No se pudo actualizar el producto: el SKU '{sku_value}' ya existe.", "danger")
            else:
                flash("No se pudo actualizar el producto por un conflicto de integridad en la base de datos.", "danger")
        return redirect(url_for("main.products_admin_list"))

    roots = _category_roots_with_children()
    brands = Brand.query.order_by(Brand.name).all()
    return render_template(
        "admin/product_form.html",
        roots=roots,
        brands=brands,
        product=p,
        form_action=url_for("main.products_admin_edit", product_id=p.id),
        title="Editar producto",
        max_gallery_images=MAX_GALLERY_IMAGES,
        gallery_display=_gallery_display_entries(p.images),
        gallery_context="product",
        gallery_context_id=str(p.id),
        gallery_reorder_endpoint=url_for("main.products_gallery_reorder", product_id=p.id),
    )


@bp.route("/admin/products/<uuid:product_id>/gallery-reorder", methods=["POST"])
@admin_required
def products_gallery_reorder(product_id):
    product = Product.query.get_or_404(product_id)
    data = request.get_json(silent=True) or {}
    order = data.get("order") or []
    if not isinstance(order, list) or not order:
        return jsonify(success=False, message="Orden inválido."), 400

    images_by_id = {str(img.id): img for img in list(product.images or [])}
    expected = set(images_by_id.keys())
    requested = [str(x) for x in order]
    if set(requested) != expected:
        return jsonify(success=False, message="La lista de imágenes no coincide con la galería actual."), 400

    for pos, image_id in enumerate(requested, start=1):
        images_by_id[image_id].position = pos

    _sync_primary_image_from_gallery(product)
    db.session.commit()
    return jsonify(success=True, message="Orden actualizado."), 200

# --- Helper imagen producto ---
def _download_image_from_url(image_url):
    if not image_url:
        return None
    url = image_url.strip()
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type and not content_type.startswith("image/"):
                current_app.logger.warning("URL %s no es una imagen (%s)", url, content_type)
                return None
            data = resp.read(MAX_REMOTE_IMAGE_SIZE + 1)
            if len(data) > MAX_REMOTE_IMAGE_SIZE:
                current_app.logger.warning("Imagen en %s supera el límite de %s bytes", url, MAX_REMOTE_IMAGE_SIZE)
                return None
    except Exception as exc:
        current_app.logger.warning("Fallo al descargar imagen desde %s: %s", url, exc)
        return None

    ext = mimetypes.guess_extension(content_type or "") or os.path.splitext(urlparse(url).path)[1]
    if ext == ".jpe":
        ext = ".jpg"
    if not ext:
        ext = ".jpg"
    ext = ext.lower()
    if ext not in ALLOWED_PRODUCT_IMAGE_EXTENSIONS:
        current_app.logger.warning("Extensión %s no permitida para %s", ext, url)
        return None

    stream = BytesIO(data)
    stream.seek(0)
    filename = f"remote{ext}"
    return FileStorage(stream=stream, filename=filename, content_type=content_type or "application/octet-stream")


def _save_product_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in ALLOWED_PRODUCT_IMAGE_EXTENSIONS:
        return None
    fname = f"{uuid.uuid4().hex}{ext}"
    dest_dir = _resolved_img_subdir('products')
    os.makedirs(dest_dir, exist_ok=True)
    file_storage.save(os.path.join(dest_dir, fname))
    return fname


def _sync_primary_image_from_gallery(product):
    if not getattr(product, "images", None):
        return
    ordered = sorted(
        (img for img in product.images if getattr(img, "filename", None)),
        key=lambda img: (img.position or 0),
    )
    if ordered:
        product.image_filename = ordered[0].filename


def _append_gallery_images(product, file_list=None, url_list=None):
    file_list = [f for f in (file_list or []) if f and getattr(f, "filename", None)]
    url_list = [(u or "").strip() for u in (url_list or []) if (u or "").strip()]

    existing_images = list(product.images)
    next_position = 1
    if existing_images:
        next_position = max((img.position or 0) for img in existing_images) + 1

    current_gallery_count = len(existing_images)
    slots_left = max(0, MAX_GALLERY_IMAGES - current_gallery_count)

    added = 0
    failed_urls = []
    skipped_by_limit = 0

    for gallery_file in file_list:
        if slots_left <= 0:
            skipped_by_limit += 1
            continue
        filename = _save_product_image(gallery_file)
        if not filename:
            continue
        db.session.add(ProductImage(product_id=product.id, filename=filename, position=next_position))
        next_position += 1
        slots_left -= 1
        added += 1

    for cleaned_url in url_list:
        if slots_left <= 0:
            skipped_by_limit += 1
            continue
        remote_file = _download_image_from_url(cleaned_url)
        if not remote_file:
            failed_urls.append(cleaned_url)
            continue
        filename = _save_product_image(remote_file)
        if not filename:
            failed_urls.append(cleaned_url)
            continue
        db.session.add(ProductImage(product_id=product.id, filename=filename, position=next_position))
        next_position += 1
        slots_left -= 1
        added += 1

    setattr(product, "_added_gallery_count", added)
    setattr(product, "_skipped_gallery_due_limit", skipped_by_limit)
    setattr(product, "_remaining_gallery_slots", slots_left)

    return added, failed_urls


def _make_gallery_remove_token(origin, identifier):
    origin = origin or "gallery"
    identifier = identifier or ""
    return f"{origin}|{identifier}"


def _parse_gallery_remove_token(token):
    if not token:
        return None, None
    if "|" not in token:
        return token, ""
    origin, payload = token.split("|", 1)
    return origin, payload


def _build_preview_gallery_entries(filenames):
    entries = []
    for fn in filenames:
        entries.append(
            SimpleNamespace(
                filename=fn,
                origin="session",
                image_id=fn,
                remove_token=_make_gallery_remove_token("session", fn),
            )
        )
    return entries


def _gallery_display_entries(gallery_records):
    ordered = sorted(
        (img for img in (gallery_records or []) if getattr(img, "filename", None)),
        key=lambda img: (img.position or 0),
    )
    entries = []
    for img in ordered:
        entries.append(
            SimpleNamespace(
                filename=img.filename,
                origin="gallery",
                image_id=str(img.id),
                remove_token=_make_gallery_remove_token("gallery", str(img.id)),
            )
        )
    return entries

def _save_slide_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    allowed = {'.jpg', '.jpeg', '.png', '.webp'}
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in allowed:
        return None
    fname = f"{uuid.uuid4().hex}{ext}"
    dest_dir = _resolved_img_subdir('slides')
    os.makedirs(dest_dir, exist_ok=True)
    file_storage.save(os.path.join(dest_dir, fname))
    return fname

def _resolved_img_subdir(subdir: str) -> str:
    """Devuelve el path donde guardar la imagen.
    Estrategia:
      - Siempre escribir en static/img/<subdir> para que sea servible inmediatamente.
      - Si volumen está habilitado y existe /data/uploads/<subdir>, copiar el archivo luego (lo hace el caller).
    Nota: si el symlink se crea en el próximo deploy, esas imágenes ya estarán en el volumen desde la copia."""
    return os.path.join(current_app.static_folder, 'img', subdir)


@bp.route("/admin/products/<uuid:product_id>/delete", methods=["POST"])
@admin_required
def products_admin_delete(product_id):
    p = Product.query.get_or_404(product_id)
    db.session.delete(p)
    db.session.commit()
    flash("Producto eliminado", "success")
    return redirect(url_for("main.products_admin_list"))

@bp.route("/admin/products/<uuid:product_id>/feature", methods=["POST"])
@admin_required
def products_admin_feature_toggle(product_id):
    p = Product.query.get_or_404(product_id)
    p.featured = not getattr(p, 'featured', False)
    db.session.commit()
    msg = "agregado a destacados" if p.featured else "quitado de destacados"
    flash(f"{p.name} {msg}", "success")
    # Volver a donde vino si mandaron 'next'
    next_url = request.form.get('next')
    return redirect(next_url or url_for('main.products_admin_list'))

# --- Slides (CRUD) ---
@bp.route("/admin/slides")
@admin_required
def slides_admin_list():
    slides = Slide.query.order_by(Slide.order.asc(), Slide.created_at.desc()).all()
    return render_template("admin/slides_list.html", slides=slides)


@bp.route("/admin/slides/new", methods=["GET", "POST"])
@admin_required
def slides_admin_new():
    if request.method == "POST":
        order = int(request.form.get("order") or 0)
        visible = bool(request.form.get("visible"))
        image_file = request.files.get("image")
        if not image_file or not image_file.filename:
            flash("La imagen es obligatoria", "danger")
            return redirect(url_for("main.slides_admin_new"))
        image_filename = _save_slide_image(image_file)
        if not image_filename:
            flash("Formato de imagen no soportado", "danger")
            return redirect(url_for("main.slides_admin_new"))
        s = Slide(order=order, visible=visible, image_filename=image_filename)
        db.session.add(s)
        db.session.commit()
        flash("Slide creado", "success")
        return redirect(url_for("main.slides_admin_list"))
    return render_template("admin/slide_form.html", form_action=url_for("main.slides_admin_new"), title="Nuevo slide")


@bp.route("/admin/slides/<uuid:slide_id>/edit", methods=["GET", "POST"])
@admin_required
def slides_admin_edit(slide_id):
    s = Slide.query.get_or_404(slide_id)
    if request.method == "POST":
        s.order = int(request.form.get("order") or 0)
        s.visible = bool(request.form.get("visible"))
        image_file = request.files.get("image")
        new_image = _save_slide_image(image_file)
        if new_image:
            s.image_filename = new_image
        db.session.commit()
        flash("Slide actualizado", "success")
        return redirect(url_for("main.slides_admin_list"))
    return render_template("admin/slide_form.html", slide=s, form_action=url_for("main.slides_admin_edit", slide_id=s.id), title="Editar slide")


@bp.route("/admin/slides/<uuid:slide_id>/toggle", methods=["POST"])
@admin_required
def slides_admin_toggle(slide_id):
    s = Slide.query.get_or_404(slide_id)
    s.visible = not s.visible
    db.session.commit()
    flash("Visibilidad actualizada", "success")
    return redirect(url_for("main.slides_admin_list"))


@bp.route("/admin/slides/<uuid:slide_id>/delete", methods=["POST"])
@admin_required
def slides_admin_delete(slide_id):
    s = Slide.query.get_or_404(slide_id)
    db.session.delete(s)
    db.session.commit()
    flash("Slide eliminado", "success")
    return redirect(url_for("main.slides_admin_list"))


@bp.route("/admin/slides/bulk", methods=["POST"])
@admin_required
def slides_admin_bulk():
    files = request.files.getlist("images")
    if not files:
        flash("No seleccionaste imágenes", "warning")
        return redirect(url_for("main.slides_admin_list"))
    last = Slide.query.order_by(Slide.order.desc()).first()
    base_order = last.order if last and isinstance(last.order, int) else -1
    created = 0
    for idx, f in enumerate(files):
        if not f or not f.filename:
            continue
        image_filename = _save_slide_image(f)
        if not image_filename:
            continue
        s = Slide(order=base_order + idx + 1, visible=True, image_filename=image_filename)
        db.session.add(s)
        created += 1
    if created:
        db.session.commit()
        flash(f"{created} slide(s) cargados", "success")
    else:
        flash("No se cargaron slides (formatos no válidos)", "warning")
    return redirect(url_for("main.slides_admin_list"))


@bp.route("/admin/products/gallery-url-upload", methods=["POST"])
@admin_required
def products_gallery_url_upload():
    data = request.get_json(silent=True) or {}
    raw_url = (data.get("url") or "").strip()
    if not raw_url:
        return jsonify(success=False, message="Ingresá una URL válida."), 400
    context = data.get("context") or ""
    if context not in {"preview", "product"}:
        return jsonify(success=False, message="Contexto inválido."), 400

    def _build_thumb_response(filename, remaining, message=None, remove_token=None):
        img_url = url_for("static", filename=f"img/products/{filename}") if filename else None
        return jsonify(
            success=True,
            image_url=img_url,
            filename=filename,
            remaining=max(0, remaining),
            remove_token=remove_token,
            message=message or "Imagen agregada desde URL.",
        ), 200

    if context == "preview":
        try:
            row_index = int(data.get("row_index", -1))
        except (TypeError, ValueError):
            row_index = -1
        rows = _get_bulk_preview_rows()
        if not rows or row_index < 0 or row_index >= len(rows):
            return jsonify(success=False, message="Borrador no encontrado."), 404
        row = rows[row_index]
        gallery = list(row.get("gallery_images") or [])
        if not gallery and row.get("image_filename"):
            gallery.append(row.get("image_filename"))
        if len(gallery) >= MAX_GALLERY_IMAGES:
            return jsonify(success=False, message=f"Alcanzaste el máximo de {MAX_GALLERY_IMAGES} imágenes."), 400
        remote_file = _download_image_from_url(raw_url)
        if not remote_file:
            return jsonify(success=False, message="No se pudo descargar la imagen desde la URL indicada."), 400
        filename = _save_product_image(remote_file)
        if not filename:
            return jsonify(success=False, message="El archivo descargado no es un formato soportado."), 400
        gallery.append(filename)
        gallery = gallery[:MAX_GALLERY_IMAGES]
        row["gallery_images"] = gallery
        row["image_filename"] = gallery[0]
        rows[row_index] = row
        _set_bulk_preview_rows(rows)
        remaining = MAX_GALLERY_IMAGES - len(gallery)
        remove_token = _make_gallery_remove_token("session", filename)
        return _build_thumb_response(filename, remaining, "Imagen agregada al borrador.", remove_token)

    # context == "product"
    product_id = data.get("product_id")
    pid = _coerce_uuid(product_id)
    if not pid:
        return jsonify(success=False, message="Producto inválido."), 400
    product = Product.query.get(pid)
    if not product:
        return jsonify(success=False, message="Producto no encontrado."), 404
    current_count = len(product.images or [])
    if current_count >= MAX_GALLERY_IMAGES:
        return jsonify(success=False, message=f"Alcanzaste el máximo de {MAX_GALLERY_IMAGES} imágenes."), 400
    remote_file = _download_image_from_url(raw_url)
    if not remote_file:
        return jsonify(success=False, message="No se pudo descargar la imagen desde la URL indicada."), 400
    filename = _save_product_image(remote_file)
    if not filename:
        return jsonify(success=False, message="El archivo descargado no es un formato soportado."), 400
    next_position = 1
    if product.images:
        next_position = max((img.position or 0) for img in product.images) + 1
    new_image = ProductImage(product=product, filename=filename, position=next_position)
    db.session.add(new_image)
    db.session.flush()
    if not product.image_filename:
        product.image_filename = filename
    remaining = MAX_GALLERY_IMAGES - min(MAX_GALLERY_IMAGES, current_count + 1)
    db.session.commit()
    remove_token = _make_gallery_remove_token("gallery", str(new_image.id))
    return _build_thumb_response(filename, remaining, "Imagen agregada al producto.", remove_token)
