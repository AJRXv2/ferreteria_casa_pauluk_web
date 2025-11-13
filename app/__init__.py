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

    # Seed categorías base si no existen (solo si la tabla ya existe)
    with app.app_context():
        from .models import Category, User, SiteInfo  # noqa: E402

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
            now = datetime.now()
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
                    exists = User.query.filter_by(username="admin").first()
                    if not exists:
                        admin = User(username="admin", is_admin=True)
                        admin.set_password("admin123")
                        db.session.add(admin)
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
