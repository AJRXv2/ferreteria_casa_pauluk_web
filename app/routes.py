import uuid
from decimal import Decimal, InvalidOperation
from functools import wraps
import os
import base64
import mimetypes
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, current_app, abort, Response
from flask_login import login_user, logout_user, login_required, current_user
from .models import Category, Product, User, Brand, SiteInfo, Slide, Consulta
from sqlalchemy.exc import ProgrammingError, OperationalError
from sqlalchemy import or_
from . import db, slugify

bp = Blueprint("main", __name__)


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
    if os.path.isdir(brands_dir):
        for fn in sorted(os.listdir(brands_dir)):
            ext = os.path.splitext(fn)[1].lower()
            if ext in allowed_ext:
                files.append(os.path.join(brands_dir, fn))

    # Si no hay logos, devolvemos un tile vacío transparente mínimo
    if not files:
        svg_empty = """
        <svg xmlns='http://www.w3.org/2000/svg' width='32' height='32' viewBox='0 0 32 32'>
        </svg>
        """
        resp = Response(svg_empty, mimetype="image/svg+xml")
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp

    # Parámetros del tile y grilla
    tile_w = 360
    tile_h = 360
    cols = 3
    rows = 3
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
        cat = Category(name=name, slug=slug, parent_id=parent_id)
        db.session.add(cat)
        db.session.commit()
        flash("Categoría creada", "success")
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
        cat.slug = slugify(name)
        cat.parent_id = parent_id
        db.session.commit()
        flash("Categoría actualizada", "success")
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
    products = (
        Product.query
        .outerjoin(Category, Product.category_id == Category.id)
        .add_entity(Category)
        .order_by(Product.created_at.desc())
        .all()
    )
    roots = _category_roots_with_children()
    brands = Brand.query.order_by(Brand.name).all()

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
                })
            # Render sin redirigir, misma página con la tabla editable
            return render_template(
                "admin/products_list.html",
                products=products,
                roots=roots,
                brands=brands,
                preview_rows=preview_rows,
            )
        elif action == "save":
            # Paso 2: recibir items[i][field] y guardarlos
            try:
                count = int(request.form.get("items_count", "0"))
            except ValueError:
                count = 0
            created = 0
            for i in range(count):
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
                # Imagen
                image_file = request.files.get(f"image_{i}")
                image_filename = _save_product_image(image_file)
                p = Product(
                    name=name,
                    sku=sku,
                    price=price,
                    in_stock=in_stock,
                    category_id=category_id,
                    brand_id=brand_id,
                    image_filename=image_filename,
                )
                db.session.add(p)
                created += 1
            if created:
                db.session.commit()
                flash(f"{created} producto(s) creados", "success")
            else:
                flash("No se crearon productos. Revisá los datos.", "warning")
            # Volver a listar en la misma página
            products = (
                Product.query
                .outerjoin(Category, Product.category_id == Category.id)
                .add_entity(Category)
                .order_by(Product.created_at.desc())
                .all()
            )
        return render_template("admin/products_list.html", products=products, roots=roots, brands=brands)

    # GET simple
    return render_template("admin/products_list.html", products=products, roots=roots, brands=brands)


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
        cat_id_raw = request.form.get("category_id") or None
        category_id = uuid.UUID(cat_id_raw) if cat_id_raw else None
        brand_id_raw = request.form.get("brand_id") or None
        brand_id = uuid.UUID(brand_id_raw) if brand_id_raw else None

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

        image_file = request.files.get("image")
        image_filename = _save_product_image(image_file)
        p = Product(
            name=name,
            sku=sku,
            price=price,
            in_stock=in_stock,
            short_desc=short_desc,
            long_desc=long_desc,
            category_id=category_id,
            brand_id=brand_id,
            image_filename=image_filename,
        )
        db.session.add(p)
        db.session.commit()
        flash("Producto creado", "success")
        return redirect(url_for("main.products_admin_list"))

    roots = _category_roots_with_children()
    brands = Brand.query.order_by(Brand.name).all()
    return render_template(
        "admin/product_form.html",
        roots=roots,
        brands=brands,
        form_action=url_for("main.products_admin_new"),
        title="Nuevo producto",
    )


@bp.route("/admin/products/<uuid:product_id>/edit", methods=["GET", "POST"])
@admin_required
def products_admin_edit(product_id):
    p = Product.query.get_or_404(product_id)
    if request.method == "POST":
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

        # Imagen (si se sube una nueva, reemplaza la anterior)
        image_file = request.files.get("image")
        new_image = _save_product_image(image_file)
        p.name = name
        p.sku = sku
        p.price = price
        p.in_stock = in_stock
        p.short_desc = short_desc
        p.long_desc = long_desc
        p.category_id = category_id
        p.brand_id = brand_id
        if new_image:
            p.image_filename = new_image
        db.session.commit()
        flash("Producto actualizado", "success")
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
    )

# --- Helper imagen producto ---
def _save_product_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    allowed = {'.jpg', '.jpeg', '.png', '.webp'}
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in allowed:
        return None
    fname = f"{uuid.uuid4().hex}{ext}"
    dest_dir = _resolved_img_subdir('products')
    os.makedirs(dest_dir, exist_ok=True)
    file_storage.save(os.path.join(dest_dir, fname))
    return fname

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
    """Retorna el directorio donde guardar imágenes.
    Si volumen está habilitado y la carpeta existe en UPLOAD_ROOT, usarla.
    Caso contrario fallback a static/img/<subdir>."""
    try:
        upload_root = os.getenv('UPLOAD_ROOT')
        enabled = os.getenv('ENABLE_UPLOAD_VOLUME_LINKS', 'false').lower() == 'true'
        if enabled and upload_root:
            candidate = os.path.join(upload_root, subdir)
            if os.path.isdir(candidate):
                return candidate
    except Exception:
        pass
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
