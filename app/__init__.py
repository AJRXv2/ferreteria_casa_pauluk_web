import os
import re
import unicodedata
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import inspect
from .config import Config
from flask_login import LoginManager

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "main.login"


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[\s_-]+", "-", value)


def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "..", "static"),
    )
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    from .routes import bp as main_bp  # noqa: E402
    app.register_blueprint(main_bp)

    # Opcional: enlazar subcarpetas de static/img a un volumen persistente (UPLOAD_ROOT)
    def _link_static_to_volume_if_configured():
        """Enlaza carpetas de imágenes a un volumen persistente si está habilitado.
        Registra logs detallados para diagnosticar problemas de montaje o permisos."""
        try:
            enabled = os.getenv("ENABLE_UPLOAD_VOLUME_LINKS", "false").lower() == "true"
            upload_root = os.getenv("UPLOAD_ROOT")
            img_src = os.path.join(app.static_folder, "img")
            direct_mount = os.getenv("STATIC_IMG_DIRECT_MOUNT", "false").lower() == "true"
            if direct_mount:
                app.logger.info(f"[uploads-volume] modo direct-mount activo; se asume volumen ya montado en {img_src}. No se hacen symlinks.")
                return
            if not enabled or not upload_root:
                app.logger.info(f"[uploads-volume] deshabilitado (ENABLE_UPLOAD_VOLUME_LINKS={enabled}, UPLOAD_ROOT={upload_root})")
                return
            app.logger.info(f"[uploads-volume] inicio enlace. upload_root={upload_root} img_src={img_src}")
            subdirs = ["products", "slides", "consultas", "brands"]
            os.makedirs(upload_root, exist_ok=True)
            for name in subdirs:
                os.makedirs(os.path.join(upload_root, name), exist_ok=True)
            app.logger.info(f"[uploads-volume] subdirs asegurados: {', '.join(subdirs)}")
            # Copiar semilla si volumen recién creado
            try:
                if not any(os.scandir(upload_root)) and os.path.isdir(img_src):
                    import shutil
                    for name in subdirs:
                        s = os.path.join(img_src, name)
                        d = os.path.join(upload_root, name)
                        if os.path.isdir(s) and not any(os.scandir(d)):
                            for entry in os.listdir(s):
                                sp = os.path.join(s, entry)
                                dp = os.path.join(d, entry)
                                try:
                                    if os.path.isdir(sp):
                                        shutil.copytree(sp, dp, dirs_exist_ok=True)
                                    else:
                                        shutil.copy2(sp, dp)
                                    app.logger.info(f"[uploads-volume] semilla copiada {sp} -> {dp}")
                                except Exception as ce:
                                    app.logger.warning(f"[uploads-volume] fallo copiando semilla {sp}: {ce}")
            except Exception as e_seed:
                app.logger.warning(f"[uploads-volume] error fase semilla: {e_seed}")
            # Crear / reemplazar enlaces
            for name in subdirs:
                target = os.path.join(upload_root, name)
                link_path = os.path.join(img_src, name)
                try:
                    if os.path.islink(link_path):
                        cur = os.readlink(link_path)
                        if cur != target:
                            os.unlink(link_path)
                            os.symlink(target, link_path)
                            app.logger.info(f"[uploads-volume] symlink actualizado {link_path} -> {target}")
                        else:
                            app.logger.info(f"[uploads-volume] symlink OK {link_path} -> {cur}")
                        continue

                    # Si existe carpeta física, copiar su contenido al volumen y reemplazarla
                    if os.path.isdir(link_path):
                        import shutil
                        try:
                            for entry in os.listdir(link_path):
                                src_entry = os.path.join(link_path, entry)
                                dst_entry = os.path.join(target, entry)
                                try:
                                    if os.path.isdir(src_entry):
                                        shutil.copytree(src_entry, dst_entry, dirs_exist_ok=True)
                                    else:
                                        shutil.copy2(src_entry, dst_entry)
                                except Exception as ce2:
                                    app.logger.warning(f"[uploads-volume] fallo copiando {src_entry}: {ce2}")
                            app.logger.info(f"[uploads-volume] contenido copiado al volumen desde {link_path}")
                        except Exception as e_copy:
                            app.logger.warning(f"[uploads-volume] error copiando contenido previo {link_path}: {e_copy}")

                        try:
                            shutil.rmtree(link_path)
                            app.logger.info(f"[uploads-volume] carpeta original eliminada {link_path}")
                        except Exception as e_rm:
                            app.logger.warning(f"[uploads-volume] no se pudo eliminar {link_path}: {e_rm}")
                            continue

                    if not os.path.exists(target):
                        os.makedirs(target, exist_ok=True)
                    try:
                        os.symlink(target, link_path)
                        app.logger.info(f"[uploads-volume] symlink creado {link_path} -> {target}")
                    except FileExistsError:
                        app.logger.warning(f"[uploads-volume] todavía existe {link_path} impidiendo symlink; se seguirá usando almacenamiento local")
                except Exception as e_link:
                    app.logger.warning(f"[uploads-volume] fallo symlink {link_path}: {e_link}")
        except Exception as e_outer:
            app.logger.warning(f"[uploads-volume] error general enlace: {e_outer}")
    _link_static_to_volume_if_configured()
    with app.app_context():
        from .models import Category, User, SiteInfo  # restaurar import perdido para seed y contexto

        @app.context_processor
        def inject_nav_categories():
            # categorías raíz y contador de consultas sin leer
            from .models import Category, Consulta  # local import to avoid circular
            unread = 0
            try:
                roots = Category.query.filter_by(parent_id=None).order_by(Category.name).all()
            except Exception as e_root:
                app.logger.warning(f"Fallo obteniendo categorías raíz: {e_root}")
                try:
                    db.session.rollback()
                except Exception:
                    pass
                roots = []
            # Evitar warnings antes de que exista la tabla 'consultas'
            try:
                if inspect(db.engine).has_table("consultas"):
                    unread = Consulta.query.filter(Consulta.read_at.is_(None)).count()
                else:
                    unread = 0
            except Exception as e_unread:
                app.logger.warning(f"Fallo contando consultas unread: {e_unread}")
                try:
                    db.session.rollback()
                except Exception:
                    pass
                unread = 0
            # Flag consultas_enabled
            consultas_enabled = True
            try:
                if inspect(db.engine).has_table("site_info"):
                    from .models import SiteInfo
                    si = SiteInfo.query.first()
                    if si:
                        consultas_enabled = bool(getattr(si, "consultas_enabled", True))
            except Exception as e_flag:
                app.logger.warning(f"Fallo obteniendo flag consultas_enabled: {e_flag}")
                try:
                    db.session.rollback()
                except Exception:
                    pass
                consultas_enabled = True
            return {"nav_categories": roots, "consultas_unread": unread, "consultas_enabled": consultas_enabled}
        @app.context_processor
        def inject_store_status():
            from datetime import datetime
            from .models import SiteInfo
            si = SiteInfo.query.first()
            tz_name = app.config.get("STORE_TIMEZONE")
            tzinfo = None
            if tz_name:
                try:
                    from zoneinfo import ZoneInfo  # Python 3.9+
                    tzinfo = ZoneInfo(tz_name)
                except Exception as tz_exc:
                    app.logger.warning(f"Zona horaria {tz_name} inválida: {tz_exc}")
                    tzinfo = None
            now = datetime.now(tzinfo) if tzinfo else datetime.now()
            status = None
            # Intento simple: buscar patrones HH:MM en si.hours y decidir abierto si uno coincide
            def parse_ranges(text):
                import re
                ranges = []
                for part in text.split('|'):
                    # Extraer horas tipo 08:00-12:00
                    for rng in re.findall(r'(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})', part):
                        ranges.append(rng)
                return ranges
            open_now = False
            if si and si.hours:
                try:
                    for a,b in parse_ranges(si.hours):
                        h1,m1 = [int(x) for x in a.split(':')]
                        h2,m2 = [int(x) for x in b.split(':')]
                        start = now.replace(hour=h1, minute=m1, second=0, microsecond=0)
                        end = now.replace(hour=h2, minute=m2, second=0, microsecond=0)
                        if start <= now <= end:
                            open_now = True
                            break
                except Exception:
                    pass
            status = 'open' if open_now else 'closed'
            return {"store_status": status, "site_info": si}

        try:
            if inspect(db.engine).has_table("categories") and Category.query.count() == 0:
                for name in ["Pintureria", "Electricidad", "Ferreteria", "Herramientas"]:
                    c = Category(name=name, slug=slugify(name))
                    db.session.add(c)
                db.session.commit()
            # Crear usuario admin por defecto (idempotente, tolerante a concurrencia)
            if inspect(db.engine).has_table("users"):
                try:
                    from sqlalchemy.exc import IntegrityError
                    target_user = User.query.filter_by(username="PaulukN").first()
                    if not target_user:
                        # Si existe el usuario 'admin' viejo, lo actualizamos
                        old_admin = User.query.filter_by(username="admin").first()
                        if old_admin:
                            old_admin.username = "PaulukN"
                            old_admin.set_password("RRA2000")
                            db.session.commit()
                        else:
                            # Si no, creamos el nuevo
                            new_user = User(username="PaulukN", is_admin=True)
                            new_user.set_password("RRA2000")
                            db.session.add(new_user)
                            db.session.commit()
                except IntegrityError:
                    # Otro worker pudo crearlo en paralelo; ignorar
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
            # Seed SiteInfo por defecto
            if inspect(db.engine).has_table("site_info") and SiteInfo.query.count() == 0:
                info = SiteInfo(
                    store_name="Ferretería Casa Pauluk",
                    address="Moreno 199, Tres Isletas, Chaco, Argentina",
                    hours="Lunes a Viernes: 08:00-12:00 / 16:00-20:00 | Sábados: 08:00-12:30 / 16:30-20:00",
                    email=None,
                    phone=None,
                    instagram=None,
                )
                db.session.add(info)
                db.session.commit()
            # Upgrade nombre si existe antiguo sin 'Casa Pauluk'
            if inspect(db.engine).has_table("site_info"):
                current_info = SiteInfo.query.first()
                if current_info and "casa pauluk" not in current_info.store_name.lower():
                    # Solo modificar si es exactamente 'Ferretería' o muy corto
                    if current_info.store_name.strip().lower() in {"ferretería", "ferreteria"}:
                        current_info.store_name = "Ferretería Casa Pauluk"
                        db.session.commit()
        except Exception as _e:  # si aún no hay tablas o falla algo, limpiar transacción
            # Importante: si ocurre un error en una transacción SQLAlchemy queda en estado 'aborted'
            # y posteriores queries disparan psycopg 'InFailedSqlTransaction'. Hacemos rollback.
            try:
                db.session.rollback()
            except Exception:
                pass
            app.logger.warning(f"Seed omitido o falló inicialización: {_e}")

    from .models import User  # noqa: E402

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.get(user_id)
        except Exception:
            return None

    # Filtro Jinja para formato argentino de moneda / números
    @app.template_filter("ar_currency")
    def ar_currency(value):  # value puede ser Decimal, int, str
        try:
            from decimal import Decimal
            val = Decimal(str(value))
        except Exception:
            return value
        # Formato base con separador miles coma, decimal punto
        base = f"{val:,.2f}"  # ejemplo 1234.50 -> '1,234.50'
        # Convertir a sistema argentino: miles punto, decimal coma
        conv = base.replace(',', 'X').replace('.', ',').replace('X', '.')
        return f"$ {conv}"  # incluir símbolo peso

    @app.template_filter("ar_number")
    def ar_number(value):
        try:
            from decimal import Decimal
            val = Decimal(str(value))
        except Exception:
            return value
        base = f"{val:,.2f}"
        return base.replace(',', 'X').replace('.', ',').replace('X', '.')
    return app
