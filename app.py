"""
========================================================
Chatbot Vendedor Multicanal (CLP, Chile) - Aerocámaras
========================================================
Framework: FastAPI
Canales: Sitio Web (REST), WhatsApp & Instagram (Meta Cloud API Webhooks),
         Telegram (webhook), (extensible a otros).
Persistencia: SQLite (leads, sesiones, pedidos)
NLU: Reglas + etiquetas (intents) + estado conversacional (FSM)

Requisitos (requirements.txt):
------------------------------
fastapi==0.115.2
uvicorn[standard]==0.30.6
requests==2.32.3
python-dotenv==1.0.1
pydantic==2.9.2
python-telegram-bot==21.6
SQLAlchemy==2.0.36

Variables de entorno (.env):
----------------------------
# Meta (WhatsApp e Instagram vía Cloud API)
META_VERIFY_TOKEN=mi_token_verificacion_meta
META_ACCESS_TOKEN=EAAB... (permanent/long-lived)
META_WA_PHONE_ID=xxxxxxxxxxxxxxx         # phone-number-id
META_IG_BUSINESS_ID=xxxxxxxxxxxxxxx      # opcional si respondes a IG desde Graph

# Telegram
TELEGRAM_BOT_TOKEN=xxxxxxxxx:YYYYYYYYYYYYYYYYYYYY
TELEGRAM_WEBHOOK_URL=https://tu-dominio.com/telegram/webhook
TELEGRAM_SECRET_TOKEN=cualquier_cadena_larga_y_unica

# App
APP_BASE_URL=https://tu-dominio.com
APP_ENV=prod

Ejecución:
----------
uvicorn app:app --host 0.0.0.0 --port 8000 --reload

Notas:
------
- Para WhatsApp/Instagram: configura el webhook en Meta (GET verification + POST events).
- Para Telegram: setWebhook apuntando a /telegram/webhook (esta app expone el endpoint).
- Para "Sitio Web": usa /webchat/send como endpoint de mensajería (simple).
- El cierre de venta genera un resumen y un "link de pago" de ejemplo. Integra Webpay/Khipu/MercadoPago donde indica TODO.
- Los precios están en CLP e incluyen IVA (19%) en la etiqueta final mostrada al cliente. Ajusta según tu política.
"""

import os
import json
import threading
import time
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime
from dotenv import load_dotenv

import requests
from fastapi import FastAPI, Request, HTTPException, Query, Header
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.background import BackgroundTasks
from pydantic import BaseModel, Field

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Float
from sqlalchemy.orm import sessionmaker, declarative_base

# ============= Carga de configuración =============
load_dotenv()

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "verify123")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
META_WA_PHONE_ID = os.getenv("META_WA_PHONE_ID", "")
META_IG_BUSINESS_ID = os.getenv("META_IG_BUSINESS_ID", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "")
TELEGRAM_SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN", "")

# ============= FastAPI =============
app = FastAPI(title="Chatbot Aerocámaras (CLP, Chile)")

# ============= Base de datos (SQLite) =============
engine = create_engine(
    "sqlite:///chatbot.db", connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True)
    channel = Column(String(50))
    user_id = Column(String(128))
    name = Column(String(128))
    phone = Column(String(64))
    email = Column(String(128))
    city = Column(String(128))
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class SessionState(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True)
    channel = Column(String(50))
    user_id = Column(String(128))
    state = Column(String(64))  # estado FSM
    context = Column(Text)  # JSON con datos de conversación
    updated_at = Column(DateTime, default=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    channel = Column(String(50))
    user_id = Column(String(128))
    order_json = Column(Text)  # JSON con carrito/resumen
    total_clp = Column(Float)
    status = Column(String(32), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)

# ============= Catálogo (CLP, Chile) - Información real de aeroprochile.cl =============
CATALOGO = {
    "humana": {
        "bolso": {
            "sku": "AERO-H-BOL",
            "nombre": "Aerocámara Plegable + bolso transportador",
            "precio_clp": 21990,  # referencial
            "url": "https://aeroprochile.cl/producto/aerocamara-plegable-sin-mascarilla/",
        },
        "mascarilla": {
            "sku": "AERO-H-MASK",
            "nombre": "Aerocámara plegable con mascarilla",
            "precio_clp": 25990,  # referencial
            "url": "https://aeroprochile.cl/producto/aerocamara-plegable-con-mascarilla/",
        },
        "adaptador_circular": {
            "sku": "AERO-H-ADC",
            "nombre": "Aerocámara plegable con adaptador circular",
            "precio_clp": 21990,  # referencial
            "url": "https://aeroprochile.cl/producto/aerocamara-plegable-con-adaptador-circular/",
        },
        "recambio": {
            "sku": "AERO-H-REC",
            "nombre": "Aerocámara plegable para recambio",
            "precio_clp": 12990,  # referencial (ver tienda)
            "url": "https://aeroprochile.cl/producto/aerocamara-plegable-para-recambio-envio-gratis-compras-superiores-30-000/",
        },
    },
    "mascota": {
        # precios varían por talla; el bot lo explicará y pedirá talla
        "aeropet_variable": {
            "sku": "AERO-M-VAR",
            "nombre": "Aerocámara para mascotas (tallas S–L)",
            "precio_min": 20990,
            "precio_max": 36990,
            "precio_variable": True,
            "url": "https://aeroprochile.cl/producto/aerocamara-de-mascota-envio-gratis/",
        },
    },
}
IVA = 0.19


# ============= Helpers de sesión y contexto =============
def db() -> sessionmaker:
    return SessionLocal


def get_session(channel: str, user_id: str) -> SessionState:
    s = db()()
    try:
        sess = s.query(SessionState).filter_by(channel=channel, user_id=user_id).first()
        if not sess:
            sess = SessionState(
                channel=channel, user_id=user_id, state="START", context=json.dumps({})
            )
            s.add(sess)
            s.commit()
            s.refresh(sess)
        return sess
    finally:
        s.close()


def save_session(
    sess: SessionState, state: Optional[str] = None, ctx: Optional[Dict] = None
):
    s = db()()
    try:
        if state is not None:
            sess.state = state
        if ctx is not None:
            sess.context = json.dumps(ctx)
        sess.updated_at = datetime.utcnow()
        s.merge(sess)
        s.commit()
    finally:
        s.close()


def update_context(sess: SessionState, updates: Dict[str, Any]):
    ctx = json.loads(sess.context or "{}")
    ctx.update(updates)
    save_session(sess, ctx=ctx)


def get_context(sess: SessionState) -> Dict[str, Any]:
    return json.loads(sess.context or "{}")


# ============= Estilo de respuesta (tono técnico + empático) =============
def asis_prefix() -> str:
    return "Hola, soy EMA 👋\n\n"


def vendedor_prefix() -> str:
    return ""


def style_msg(text: str) -> str:
    return f"{asis_prefix()}{vendedor_prefix()}{text}"


# ============= NLG Variantes (evitar respuestas robóticas) =============
NLG_VARIANTS = {
    "greet": [
        "¿Buscas aerocámara para PERSONA o MASCOTA?",
        "¿Es para uso en PERSONA o MASCOTA?",
        "¿Aerocámara para PERSONA o MASCOTA?",
    ],
    "transition_qualify": [
        "¿Es para PERSONA o MASCOTA?",
        "¿Para PERSONA o MASCOTA?",
        "¿Buscas para PERSONA o MASCOTA?",
    ],
    "missing_data": [
        "Perfecto, me faltan: {missing}.",
        "Genial, solo me falta: {missing}.",
        "Casi listo, me faltan: {missing}.",
    ],
    "finalize": [
        "¡Listo! Te envié el resumen y el enlace de pago. ¿Necesitas instrucciones de uso?",
        "Perfecto, tu pedido está listo. Encontrarás el enlace de pago arriba. ¿Alguna duda sobre el uso?",
        "Excelente. Ya tienes el resumen y link de pago. ¿Te paso las instrucciones de uso?",
    ],
}


def get_variant(key: str, **kwargs) -> str:
    """Obtiene una variante aleatoria de NLG_VARIANTS."""
    import random

    variants = NLG_VARIANTS.get(key, [])
    if not variants:
        return ""
    msg = random.choice(variants)
    return msg.format(**kwargs) if kwargs else msg


# ============= Telegram ReplyKeyboard =============
def build_keyboard(state: str | None) -> dict | None:
    """Devuelve un reply_markup con teclado rápido según el estado."""
    rows: list[list[str]] = []
    st = (state or "").upper()
    if st in ("START", "QUALIFY", ""):
        rows = [["Persona", "Mascota"], ["Precio", "Envío"], ["Hablar con asesor"]]
    elif st == "HUMAN_DETAIL":
        rows = [
            ["Bolso", "Mascarilla"],
            ["Adaptador Circular", "Recambio"],
            ["Ver precios", "Envío"],
            ["Volver"],
        ]
    elif st == "PET_DETAIL":
        rows = [
            ["Talla S", "Talla M", "Talla L"],
            ["Ver precios", "Envío"],
            ["Volver"],
        ]
    elif st == "COLLECT_DATA":
        rows = [["Enviar datos"], ["Envío", "Garantía"], ["Hablar con asesor"]]
    elif st == "CLOSE":
        rows = [
            ["Finalizar", "Agregar otra unidad"],
            ["Instrucciones", "Envío"],
            ["Garantía"],
        ]
    elif st == "DONE":
        # En DONE removemos el teclado
        return {"remove_keyboard": True}
    if not rows:
        return None
    return {
        "keyboard": [[{"text": b} for b in r] for r in rows],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


# ============= Telegram Inline Keyboard =============
def build_inline_keyboard(state: str | None, ctx: Optional[Dict] = None) -> dict | None:
    """Devuelve un inline_keyboard según el estado."""
    st = (state or "").upper()
    buttons = []

    if st in ("QUALIFY", "HUMAN_DETAIL", "PET_DETAIL"):
        buttons.append(
            [
                {
                    "text": "Ver precios",
                    "callback_data": f"see_prices:{ctx.get('family', 'all') if ctx else 'all'}",
                },
                {"text": "Hablar con asesor", "callback_data": "handoff"},
            ]
        )
    elif st == "CLOSE":
        buttons.append(
            [
                {"text": "Finalizar", "callback_data": "finalize_order"},
                {"text": "Agregar otra unidad", "callback_data": "add_unit:menu"},
            ]
        )
        # Agregar botón de ver precios también
        family = ctx.get("family", "") if ctx else ""
        if family:
            buttons.append(
                [{"text": "Ver precios", "callback_data": f"see_prices:{family}"}]
            )

    if not buttons:
        return None
    return {"inline_keyboard": buttons}


# ============= NLU simple (reglas) =============
def classify_intent(text: str) -> str:
    t = (text or "").strip().lower()

    # Aeropro (productos específicos del sitio)
    if any(k in t for k in ["bolso", "transportador"]):
        return "prod_bolso"
    if any(k in t for k in ["mascarilla"]):
        return "prod_mascarilla"
    if any(k in t for k in ["adaptador circular", "circular"]):
        return "prod_adaptador"
    if any(k in t for k in ["recambio"]):
        return "prod_recambio"
    if any(
        k in t
        for k in [
            "mascota",
            "aeropet",
            "perro",
            "gato",
            "talla s",
            "talla m",
            "talla l",
        ]
    ):
        # Verificar que no sea solo "want_pet" (ya está cubierto abajo)
        if "aeropet" in t or "talla" in t:
            return "prod_mascota"

    if any(
        k in t
        for k in [
            "hola",
            "buenas",
            "buenos días",
            "buenas tardes",
            "buenas noches",
            "start",
            "/start",
        ]
    ):
        return "greet"
    if any(
        k in t for k in ["humana", "persona", "adulto", "pediátrico", "niño", "niña"]
    ):
        return "want_human"
    if any(k in t for k in ["mascota", "perro", "gato"]):
        return "want_pet"
    if any(k in t for k in ["precio", "cuánto", "cuanto", "vale", "cost", "precios"]):
        return "ask_price"
    if any(
        k in t
        for k in [
            "comprar",
            "orden",
            "pedido",
            "quiero",
            "cómpralo",
            "lo compro",
            "pagar",
        ]
    ):
        return "buy"
    if any(
        k in t
        for k in [
            "envío",
            "retiro",
            "despacho",
            "costo envío",
            "envio",
            "tiempo de envío",
        ]
    ):
        return "shipping"
    if any(k in t for k in ["garantía", "devolución", "cambio", "garantia"]):
        return "warranty"
    if any(
        k in t
        for k in [
            "ayuda",
            "asesoría",
            "uso",
            "cómo usar",
            "como usar",
            "instrucciones",
            "instrucción",
            "tutorial",
        ]
    ):
        return "faq_uso"
    if any(k in t for k in ["tamaño", "medida", "size", "modelo", "talla"]):
        return "sizing"
    # FAQ intents
    if any(
        k in t
        for k in [
            "material",
            "bpa",
            "plástico",
            "plastico",
            "de qué está hecho",
            "que material",
        ]
    ):
        return "faq_materials"
    if any(
        k in t
        for k in [
            "limpieza",
            "limpiar",
            "lavar",
            "cómo limpiar",
            "como limpiar",
            "higiene",
        ]
    ):
        return "faq_cleaning"
    if any(
        k in t
        for k in [
            "compatible",
            "compatibilidad",
            "inhalador",
            "pmpi",
            "dpi",
            "puedo usar con",
        ]
    ):
        return "faq_compatibility"
    if any(k in t for k in ["stock", "disponible", "hay", "tienen", "existencia"]):
        return "faq_stock"
    if any(
        k in t
        for k in [
            "boleta",
            "factura",
            "facturación",
            "facturacion",
            "rut",
            "documento",
            "tributario",
        ]
    ):
        return "faq_documents"
    if any(k in t for k in ["teléfono", "telefono", "correo", "email", "contacto"]):
        return "faq_contacto"
    if any(k in t for k in ["dirección", "direccion", "sucursal", "oficina"]):
        return "faq_sucursal"
    # Nuevos intents FAQ específicos
    if any(
        k in t
        for k in [
            "sin mascarilla",
            "por qué sin mascarilla",
            "porque sin mascarilla",
            "sin mascarilla por qué",
        ]
    ):
        return "faq_mascarilla_sin"
    if any(
        k in t
        for k in ["edad", "qué edad", "que edad", "para qué edad", "desde qué edad"]
    ):
        return "faq_edad"
    if any(
        k in t
        for k in [
            "cómo lavar",
            "como lavar",
            "lavado detallado",
            "pasos lavado",
            "instrucciones lavado",
        ]
    ):
        return "faq_lavado_detalle"
    if any(
        k in t
        for k in [
            "talla mascota",
            "qué talla mascota",
            "que talla mascota",
            "medir hocico",
            "talla para mascota",
        ]
    ):
        return "faq_talla_mascota"
    if any(
        k in t
        for k in ["vannair", "van air", "compatible vannair", "adaptador vannair"]
    ):
        return "faq_vannair"
    # Hooks de teclado
    if any(k in t for k in ["ver precios"]):
        return "ask_price"
    if any(k in t for k in ["volver"]):
        return "greet"
    if any(k in t for k in ["nuevo pedido"]):
        return "greet"
    if any(k in t for k in ["hablar con asesor", "asesor", "humano", "persona real"]):
        return "handoff"
    if any(k in t for k in ["finalizar", "finalizar pedido", "cerrar", "completar"]):
        return "finalize"
    if any(k in t for k in ["instagram", "whatsapp", "telegram", "web"]):
        return "channel_info"
    return "unknown"


# ============= Respuestas de producto / pricing =============
def format_price(clp: float) -> str:
    return f"${int(round(clp, 0)):,}".replace(",", ".")


def list_options_human() -> str:
    items = CATALOGO["humana"]
    lines = [
        f"- {v['nombre']}: {format_price(v['precio_clp'])} (SKU {v['sku']})"
        for v in items.values()
    ]
    return "\\n".join(lines)


def list_options_pet() -> str:
    """Lista productos para mascotas, manejando precios variables."""
    items = CATALOGO["mascota"]
    lines = []
    for v in items.values():
        if v.get("precio_variable"):
            lines.append(
                f"- {v['nombre']}: {format_price(v['precio_min'])} – {format_price(v['precio_max'])} (SKU {v['sku']})"
            )
        else:
            lines.append(
                f"- {v['nombre']}: {format_price(v['precio_clp'])} (SKU {v['sku']})"
            )
    return "\\n".join(lines)


def list_options_site() -> str:
    """Lista todos los productos del sitio con links (como en la web)."""
    lines = []
    for key, v in CATALOGO["humana"].items():
        lines.append(
            f"- {v['nombre']}: {format_price(v['precio_clp'])} · Ver: {v.get('url', '')}"
        )
    pet = CATALOGO["mascota"]["aeropet_variable"]
    lines.append(
        f"- {pet['nombre']}: {format_price(pet['precio_min'])} – {format_price(pet['precio_max'])} · Ver: {pet['url']}"
    )
    return "\\n".join(lines)


def shipping_text() -> str:
    return (
        "🚚 Envío GRATIS a todo Chile\n"
        "⏱️ RM: 1 día | Regiones: 2-5 días\n"
        "¿En qué comuna estás?"
    )


def warranty_text() -> str:
    return "Garantía 6 meses. Cambios/devoluciones según Ley Pro-Consumidor."


def howto_text(tipo: str) -> str:
    if tipo == "humana":
        return "Agita inhalador, acóplalo, sella en boca, 1 puff, inhala 5-6 veces."
    else:
        return "Acopla inhalador, sella en hocico, 1 puff, permite 5-6 respiraciones."


# ============= FAQ (Preguntas frecuentes) =============
def faq_materials() -> str:
    return (
        "Grado médico, libres de BPA. Válvula sensible que se activa con la inhalación."
    )


def faq_cleaning() -> str:
    return "Desarma, lava con agua tibia y jabón neutro, seca al aire. Ideal después de cada uso."


def faq_compatibility() -> str:
    return "Compatible con pMDI. Para DPI consulta con tu médico."


def faq_stock() -> str:
    return "Stock disponible. Para pedidos mayoristas, solicita cotización."


def faq_documents() -> str:
    return "Emitimos boleta o factura. Para facturación necesitamos tu RUT."


# FAQ adicionales del sitio
FAQ = {
    "contacto": "📞 +569 9837 4924\n⏰ Lun-Sáb 9:00-21:00\n✉️ comunicaciones@aeroprochile.cl",
    "sucursales": "🏪 Retiro en:\n• Las Condes (2 sucursales)\n• Los Álamos, Biobío\nTambién en Mercado Libre.",
    "uso_web": "Agita inhalador, acóplalo, sella bien y realiza 5-6 respiraciones lentas.",
    "mascarilla_sin": "Para mayores de 6 años. La boquilla directa es más efectiva. ¿Te interesa la versión con mascarilla?",
    "edad_uso": "Recomendado para mayores de 6 años.",
    "lavado": "Lávala 1 vez por semana. Agua fría y jabón suave, seca al aire. ¿Más detalles?",
    "talla_mascota": "Mide el hocico (comisura del labio al borde):\n• S: hasta 5 cm\n• M: hasta 7 cm\n• L: hasta 9 cm",
    "vannair": "Sí, tenemos adaptador circular compatible con Vannair. ¿Te interesa?",
}


# ============= Detección de comunas (Chile) =============
COMUNAS_RM = [
    "santiago",
    "providencia",
    "las condes",
    "ñuñoa",
    "puente alto",
    "maipú",
    "maipu",
    "vitacura",
    "san miguel",
    "la florida",
    "san bernardo",
    "la pintana",
    "melipilla",
    "talagante",
    "peñaflor",
    "el bosque",
    "la cisterna",
    "cerro navia",
    "conchalí",
    "estación central",
    "independencia",
    "la granja",
    "la reina",
    "macul",
    "pedro aguirre cerda",
    "peñalolén",
    "quilicura",
    "quinta normal",
    "recoleta",
    "renca",
    "san joaquín",
    "san ramón",
    "santiago centro",
]
COMUNAS_V = [
    "valparaíso",
    "valparaiso",
    "viña del mar",
    "viña",
    "quilpué",
    "villa alemana",
    "con con",
    "quintero",
]
COMUNAS_VI = [
    "concepción",
    "conce",
    "talcahuano",
    "los ángeles",
    "chillán",
    "coronel",
    "san pedro",
    "arauco",
]
COMUNAS_OTRAS = [
    "temuco",
    "valdivia",
    "osorno",
    "puerto montt",
    "coquimbo",
    "la serena",
    "antofagasta",
    "iquique",
    "arica",
    "punta arenas",
    "coyhaique",
    "copiapó",
    "copiao",
    "calama",
    "rancagua",
]


def detect_city(text: str) -> tuple[Optional[str], Optional[str]]:
    """Detecta si el texto menciona una comuna y retorna (comuna, zona)."""
    t = text.lower().strip()
    for c in COMUNAS_RM:
        if c in t:
            return (c.title(), "RM")
    for c in COMUNAS_V:
        if c in t:
            return (c.title(), "V")
    for c in COMUNAS_VI:
        if c in t:
            return (c.title(), "VI")
    for c in COMUNAS_OTRAS:
        if c in t:
            return (c.title(), "OTRAS")
    return (None, None)


def shipping_info_by_city(city: str, zone: str) -> str:
    """Retorna información de envío según zona."""
    if zone == "RM":
        return f"📍 {city}\n" "🚚 Envío GRATIS\n" "⏱️ 1 día (compra antes 23:00)"
    elif zone in ["V", "VI"]:
        return f"📍 {city}\n" "🚚 Envío GRATIS\n" "⏱️ 48 horas"
    else:
        return f"📍 {city}\n" "🚚 Envío GRATIS\n" "⏱️ 2-5 días"


# ============= Carrito / pedido =============
def add_to_cart(ctx: Dict, sku: str, qty: int = 1) -> Tuple[Dict, Dict]:
    item = None
    for fam in CATALOGO.values():
        for v in fam.values():
            if v["sku"] == sku:
                item = v
                break
        if item:
            break
    if not item:
        raise ValueError("SKU no encontrado")
    cart = ctx.get("cart", [])
    cart.append(
        {
            "sku": item["sku"],
            "nombre": item["nombre"],
            "precio_clp": item["precio_clp"],
            "qty": qty,
        }
    )
    ctx["cart"] = cart
    return ctx, item


def cart_total(cart: List[Dict]) -> float:
    return sum(i["precio_clp"] * i.get("qty", 1) for i in cart)


def summarize_order(ctx: Dict) -> str:
    cart = ctx.get("cart", [])
    if not cart:
        return "Tu carrito está vacío."
    lines = ["Resumen de tu pedido:"]
    for i in cart:
        lines.append(
            f"• {i['nombre']} x{i.get('qty',1)} — {format_price(i['precio_clp']*i.get('qty',1))}"
        )
    total = cart_total(cart)
    lines.append(f"Total (CLP): {format_price(total)}")
    return "\\n".join(lines)


def generate_payment_link(order_id: int, total: float) -> str:
    return f"{APP_BASE_URL}/pagar?order_id={order_id}&monto={int(total)}"


def persist_order(channel: str, user_id: str, ctx: Dict) -> Tuple[int, float]:
    s = db()()
    try:
        total = cart_total(ctx.get("cart", []))
        ord = Order(
            channel=channel,
            user_id=user_id,
            order_json=json.dumps(ctx.get("cart", [])),
            total_clp=total,
        )
        s.add(ord)
        s.commit()
        s.refresh(ord)
        return ord.id, total
    finally:
        s.close()


def persist_lead(
    channel: str,
    user_id: str,
    name: str = "",
    phone: str = "",
    email: str = "",
    city: str = "",
    notes: str = "",
):
    s = db()()
    try:
        lead = Lead(
            channel=channel,
            user_id=user_id,
            name=name,
            phone=phone,
            email=email,
            city=city,
            notes=notes,
        )
        s.add(lead)
        s.commit()
    finally:
        s.close()


# ============= Política de conversación (FSM) =============
def next_message_logic(channel: str, user_id: str, user_text: str) -> str:
    sess = get_session(channel, user_id)
    ctx = get_context(sess)
    intent = classify_intent(user_text)

    # Atajos directos por producto (responde con precio/URL y agrega al carrito si corresponde)
    if intent == "prod_bolso":
        item = CATALOGO["humana"]["bolso"]
        return style_msg(
            f"{item['nombre']} cuesta {format_price(item['precio_clp'])}. ¿Deseas añadirlo al carrito? Ver: {item['url']}"
        )
    if intent == "prod_mascarilla":
        item = CATALOGO["humana"]["mascarilla"]
        return style_msg(
            f"{item['nombre']} cuesta {format_price(item['precio_clp'])}. ¿Lo agrego al carrito? Ver: {item['url']}"
        )
    if intent == "prod_adaptador":
        item = CATALOGO["humana"]["adaptador_circular"]
        return style_msg(
            f"{item['nombre']} cuesta {format_price(item['precio_clp'])}. ¿Lo agrego al carrito? Ver: {item['url']}"
        )
    if intent == "prod_recambio":
        item = CATALOGO["humana"]["recambio"]
        return style_msg(
            f"{item['nombre']} cuesta {format_price(item['precio_clp'])} (si ya tienes bolso). ¿Lo agrego? Ver: {item['url']}"
        )
    if intent == "prod_mascota":
        item = CATALOGO["mascota"]["aeropet_variable"]
        return style_msg(
            f"{item['nombre']}: {format_price(item['precio_min'])} - {format_price(item['precio_max'])} según talla.\n"
            f"Indica talla (S/M/L). Ver: {item['url']}"
        )

    if sess.state == "START":
        update_context(sess, {"cart": []})
        save_session(sess, state="QUALIFY")
        greet_msg = get_variant("greet")
        if not greet_msg:
            greet_msg = style_msg("¿Para PERSONA o MASCOTA?")
        return greet_msg

    if sess.state == "QUALIFY":
        if intent == "handoff":
            return style_msg("Te derivo a un asesor. Déjame tu TELÉFONO o EMAIL.")

        # FAQ en QUALIFY
        if intent == "faq_materials":
            return style_msg(faq_materials())
        if intent == "faq_cleaning":
            return style_msg(faq_cleaning())
        if intent == "faq_compatibility":
            return style_msg(faq_compatibility())
        if intent == "faq_stock":
            return style_msg(faq_stock())
        if intent == "faq_documents":
            return style_msg(faq_documents())
        if intent == "faq_contacto":
            return style_msg(FAQ["contacto"])
        if intent == "faq_sucursal":
            return style_msg(FAQ["sucursales"])
        if intent == "faq_uso":
            return style_msg(FAQ["uso_web"])
        if intent == "faq_mascarilla_sin":
            return style_msg(FAQ["mascarilla_sin"])
        if intent == "faq_edad":
            return style_msg(FAQ["edad_uso"])
        if intent == "faq_lavado_detalle":
            return style_msg(FAQ["lavado"])
        if intent == "faq_talla_mascota":
            return style_msg(FAQ["talla_mascota"])
        if intent == "faq_vannair":
            return style_msg(FAQ["vannair"])
        if intent in ["want_human", "want_pet", "sizing"]:
            txt = user_text.lower()
            if any(k in txt for k in ["humana", "persona", "adulto", "pediá"]):
                update_context(sess, {"family": "humana"})
                save_session(sess, state="HUMAN_DETAIL")
                return style_msg(
                    f"Opciones para PERSONAS:\n{list_options_human()}\n\n¿Qué modelo prefieres?"
                )
            if any(k in txt for k in ["mascota", "perro", "gato"]):
                update_context(sess, {"family": "mascota"})
                save_session(sess, state="PET_DETAIL")
                return style_msg(
                    f"Opciones para MASCOTAS:\n{list_options_pet()}\n\n¿Qué talla? S/M/L"
                )
            return style_msg("¿PERSONA o MASCOTA?")

        if intent == "ask_price":
            return style_msg(
                f"Modelos disponibles:\n{list_options_site()}\n\n¿Cuál te interesa?"
            )
        if intent == "buy":
            save_session(sess, state="QUALIFY")
            return style_msg("Primero elige: ¿PERSONA o MASCOTA?")

        return style_msg(
            get_variant("transition_qualify") or "¿Es para PERSONA o MASCOTA?"
        )

    if sess.state == "HUMAN_DETAIL":
        txt = user_text.lower()

        # FAQ
        if intent == "faq_materials":
            return style_msg(faq_materials())
        if intent == "faq_cleaning":
            return style_msg(faq_cleaning())
        if intent == "faq_compatibility":
            return style_msg(faq_compatibility())
        if intent == "faq_stock":
            return style_msg(faq_stock())
        if intent == "faq_documents":
            return style_msg(faq_documents())
        if intent == "faq_contacto":
            return style_msg(FAQ["contacto"])
        if intent == "faq_sucursal":
            return style_msg(FAQ["sucursales"])
        if intent == "faq_uso":
            return style_msg(FAQ["uso_web"])
        if intent == "ask_price":
            return style_msg(f"Precios para PERSONAS:\n{list_options_human()}")
        if "volver" in txt:
            save_session(sess, state="QUALIFY")
            return style_msg(
                get_variant("transition_qualify") or "¿Es para PERSONA o MASCOTA?"
            )

        # Detectar productos específicos del nuevo catálogo
        if any(k in txt for k in ["bolso", "transportador"]):
            sku = CATALOGO["humana"]["bolso"]["sku"]
            ctx, item = add_to_cart(ctx, sku)
            update_context(sess, ctx)
            save_session(sess, state="COLLECT_DATA")
            return style_msg(
                f"✓ Agregado: {item['nombre']} ({format_price(item['precio_clp'])})\n"
                f"{summarize_order(ctx)}\n\n"
                "Necesito: NOMBRE, COMUNA y TELÉFONO o EMAIL."
            )
        if "mascarilla" in txt:
            sku = CATALOGO["humana"]["mascarilla"]["sku"]
            ctx, item = add_to_cart(ctx, sku)
            update_context(sess, ctx)
            save_session(sess, state="COLLECT_DATA")
            return style_msg(
                f"✓ Agregado: {item['nombre']} ({format_price(item['precio_clp'])})\n"
                f"{summarize_order(ctx)}\n\n"
                "Necesito: NOMBRE, COMUNA y TELÉFONO o EMAIL."
            )
        if any(k in txt for k in ["adaptador", "circular"]):
            sku = CATALOGO["humana"]["adaptador_circular"]["sku"]
            ctx, item = add_to_cart(ctx, sku)
            update_context(sess, ctx)
            save_session(sess, state="COLLECT_DATA")
            return style_msg(
                f"✓ Agregado: {item['nombre']} ({format_price(item['precio_clp'])})\n"
                f"{summarize_order(ctx)}\n\n"
                "Necesito: NOMBRE, COMUNA y TELÉFONO o EMAIL."
            )
        if "recambio" in txt:
            sku = CATALOGO["humana"]["recambio"]["sku"]
            ctx, item = add_to_cart(ctx, sku)
            update_context(sess, ctx)
            save_session(sess, state="COLLECT_DATA")
            return style_msg(
                f"✓ Agregado: {item['nombre']} ({format_price(item['precio_clp'])})\n"
                f"{summarize_order(ctx)}\n\n"
                "Necesito: NOMBRE, COMUNA y TELÉFONO o EMAIL."
            )
        if intent == "sizing":
            return style_msg(
                "¿Qué modelo prefieres? Bolso, Mascarilla, Adaptador o Recambio?"
            )
        return style_msg(
            "¿Qué modelo prefieres? Bolso, Mascarilla, Adaptador o Recambio?"
        )

    if sess.state == "PET_DETAIL":
        txt = user_text.lower()

        # FAQ
        if intent == "faq_materials":
            return style_msg(faq_materials())
        if intent == "faq_cleaning":
            return style_msg(faq_cleaning())
        if intent == "faq_compatibility":
            return style_msg(faq_compatibility())
        if intent == "faq_stock":
            return style_msg(faq_stock())
        if intent == "faq_documents":
            return style_msg(faq_documents())
        if intent == "faq_contacto":
            return style_msg(FAQ["contacto"])
        if intent == "faq_sucursal":
            return style_msg(FAQ["sucursales"])
        if intent == "faq_uso":
            return style_msg(FAQ["uso_web"])
        if intent == "ask_price":
            return style_msg(f"Precios para MASCOTAS:\n{list_options_pet()}")
        if "volver" in txt:
            save_session(sess, state="QUALIFY")
            return style_msg(
                get_variant("transition_qualify") or "¿Es para PERSONA o MASCOTA?"
            )

        # Detectar tallas para aeropet (precio variable)
        # Mapeo aproximado: S = precio_min, M = precio medio, L = precio_max
        item_base = CATALOGO["mascota"]["aeropet_variable"]
        precio_final = None
        talla_detectada = None

        if any(k in txt for k in ["talla s", "s", "peque", "pequeño", "pequeña"]):
            talla_detectada = "S"
            precio_final = item_base["precio_min"]
        elif any(k in txt for k in ["talla m", "m", "med", "mediano", "mediana"]):
            talla_detectada = "M"
            # Precio medio entre min y max
            precio_final = (item_base["precio_min"] + item_base["precio_max"]) // 2
        elif any(k in txt for k in ["talla l", "l", "gran", "grande"]):
            talla_detectada = "L"
            precio_final = item_base["precio_max"]
        else:
            talla_detectada = None

        if talla_detectada and precio_final:
            # Crear un item temporal con el precio específico de la talla
            item_temp = {
                "sku": f"{item_base['sku']}-{talla_detectada}",
                "nombre": f"{item_base['nombre']} - Talla {talla_detectada}",
                "precio_clp": precio_final,
            }
            cart = ctx.get("cart", [])
            cart.append(
                {
                    "sku": item_temp["sku"],
                    "nombre": item_temp["nombre"],
                    "precio_clp": item_temp["precio_clp"],
                    "qty": 1,
                }
            )
            ctx["cart"] = cart
            update_context(sess, ctx)
            save_session(sess, state="COLLECT_DATA")
            return style_msg(
                f"✓ Agregado: {item_temp['nombre']} ({format_price(item_temp['precio_clp'])})\n"
                f"{summarize_order(ctx)}\n\n"
                "Necesito: NOMBRE, COMUNA y TELÉFONO o EMAIL."
            )
        if intent == "sizing":
            return style_msg("¿Qué talla? S/M/L")
        return style_msg("¿Qué talla? S/M/L")

    if sess.state == "COLLECT_DATA":
        if intent == "handoff":
            return style_msg(
                "Un asesor te contactará. Déjame TELÉFONO o EMAIL y comuna."
            )

        # Manejar FAQ en COLLECT_DATA también
        if intent == "faq_materials":
            return style_msg(faq_materials())
        if intent == "faq_cleaning":
            return style_msg(faq_cleaning())
        if intent == "faq_compatibility":
            return style_msg(faq_compatibility())
        if intent == "faq_stock":
            return style_msg(faq_stock())
        if intent == "faq_documents":
            return style_msg(faq_documents())
        if intent == "faq_contacto":
            return style_msg(FAQ["contacto"])
        if intent == "faq_sucursal":
            return style_msg(FAQ["sucursales"])
        if intent == "faq_uso":
            return style_msg(FAQ["uso_web"])

        name = ctx.get("name")
        city = ctx.get("city")
        phone = ctx.get("phone")
        email = ctx.get("email")

        t = user_text.strip()

        # Detección mejorada de datos
        # Email: @ y punto
        if "@" in t and "." in t:
            email = t
        # Comuna: usar detección mejorada
        elif detect_city(t)[0]:
            detected_city, zone = detect_city(t)
            city = detected_city
            # Actualizar context con zona si es útil
            update_context(sess, {"shipping_zone": zone})
        # Teléfono: ≥ 8 dígitos
        elif (
            any(
                c.isdigit()
                for c in t.replace("+", "").replace("-", "").replace(" ", "")
            )
            and len(t.replace("+", "").replace("-", "").replace(" ", "")) >= 8
        ):
            phone = t
        # Nombre: al menos 3 caracteres, una palabra
        else:
            if len(t.split()) >= 1 and len(t) >= 3:
                name = t if not name else name

        update_context(
            sess, {"name": name, "city": city, "phone": phone, "email": email}
        )

        missing = []
        if not name:
            missing.append("NOMBRE")
        if not city:
            missing.append("COMUNA/CIUDAD")
        if not (phone or email):
            missing.append("TELÉFONO o EMAIL")

        if missing:
            missing_str = ", ".join(missing)
            reply = get_variant("missing_data", missing=missing_str)
            if not reply:
                reply = style_msg(f"Faltan: {missing_str}.")
            return reply

        persist_lead(
            channel,
            user_id,
            name=name or "",
            phone=phone or "",
            email=email or "",
            city=city or "",
        )
        order_id, total = persist_order(channel, user_id, get_context(sess))
        pay_link = generate_payment_link(order_id, total)

        save_session(sess, state="CLOSE")

        # Información de envío mejorada si hay zona
        zone = ctx.get("shipping_zone")
        shipping_msg = shipping_info_by_city(city, zone) if zone else shipping_text()

        return style_msg(
            f"{summarize_order(get_context(sess))}\n\n"
            f"Cliente: {name} — {city} — {phone or email}\n\n"
            f"{shipping_msg}\n{warranty_text()}\n\n"
            f"Link de pago: {pay_link}\n"
            "¿Agregar otra unidad o finalizar?"
        )

    if sess.state == "CLOSE":
        if intent == "handoff":
            return style_msg("Te conecto con un asesor. Confirma tu TELÉFONO o EMAIL.")
        if intent == "buy":
            # Intentar detectar qué producto quiere agregar
            txt_lower = user_text.lower()
            family = ctx.get("family", "")
            if family == "humana":
                if any(k in txt_lower for k in ["bolso", "transportador"]):
                    ctx, item = add_to_cart(ctx, "AERO-H-BOL", 1)
                    update_context(sess, ctx)
                    save_session(sess)
                    return style_msg(
                        f"Agregado: {item['nombre']}\n\n{summarize_order(get_context(sess))}"
                    )
                elif "mascarilla" in txt_lower:
                    ctx, item = add_to_cart(ctx, "AERO-H-MASK", 1)
                    update_context(sess, ctx)
                    save_session(sess)
                    return style_msg(
                        f"Agregado: {item['nombre']}\n\n{summarize_order(get_context(sess))}"
                    )
                elif any(k in txt_lower for k in ["adaptador", "circular"]):
                    ctx, item = add_to_cart(ctx, "AERO-H-ADC", 1)
                    update_context(sess, ctx)
                    save_session(sess)
                    return style_msg(
                        f"Agregado: {item['nombre']}\n\n{summarize_order(get_context(sess))}"
                    )
                elif "recambio" in txt_lower:
                    ctx, item = add_to_cart(ctx, "AERO-H-REC", 1)
                    update_context(sess, ctx)
                    save_session(sess)
                    return style_msg(
                        f"Agregado: {item['nombre']}\n\n{summarize_order(get_context(sess))}"
                    )
            elif family == "mascota":
                item_base = CATALOGO["mascota"]["aeropet_variable"]
                precio_final = None
                talla_detectada = None

                if any(
                    k in txt_lower
                    for k in ["talla s", " s", "peque", "pequeño", "pequeña"]
                ):
                    talla_detectada = "S"
                    precio_final = item_base["precio_min"]
                elif any(
                    k in txt_lower
                    for k in ["talla m", " m", "med", "mediano", "mediana"]
                ):
                    talla_detectada = "M"
                    precio_final = (
                        item_base["precio_min"] + item_base["precio_max"]
                    ) // 2
                elif any(k in txt_lower for k in ["talla l", " l", "gran", "grande"]):
                    talla_detectada = "L"
                    precio_final = item_base["precio_max"]

                if talla_detectada and precio_final:
                    item_temp = {
                        "sku": f"{item_base['sku']}-{talla_detectada}",
                        "nombre": f"{item_base['nombre']} - Talla {talla_detectada}",
                        "precio_clp": precio_final,
                    }
                    cart = ctx.get("cart", [])
                    cart.append(
                        {
                            "sku": item_temp["sku"],
                            "nombre": item_temp["nombre"],
                            "precio_clp": item_temp["precio_clp"],
                            "qty": 1,
                        }
                    )
                    ctx["cart"] = cart
                    update_context(sess, ctx)
                    save_session(sess)
                    return style_msg(
                        f"Agregado: {item_temp['nombre']}\n\n{summarize_order(get_context(sess))}"
                    )
            return style_msg("Indica el modelo a agregar o usa 'Finalizar'.")
        if intent == "finalize" or "finalizar" in user_text.lower():
            save_session(sess, state="DONE")
            finalize_msg = get_variant("finalize")
            if not finalize_msg:
                finalize_msg = style_msg(
                    "✓ Pedido listo. ¿Necesitas instrucciones de uso?"
                )
            return finalize_msg
        if intent == "howto" or intent == "faq_uso":
            fam = get_context(sess).get("family", "humana")
            uso_msg = FAQ.get("uso_web", "")
            return style_msg(uso_msg)
        if intent == "shipping":
            zone = ctx.get("shipping_zone")
            city = ctx.get("city", "")
            if zone and city:
                return style_msg(shipping_info_by_city(city, zone))
            return style_msg(shipping_text())
        if intent == "warranty":
            return style_msg(warranty_text())
        # FAQ en CLOSE también
        if intent == "faq_materials":
            return style_msg(faq_materials())
        if intent == "faq_cleaning":
            return style_msg(faq_cleaning())
        if intent == "faq_compatibility":
            return style_msg(faq_compatibility())
        if intent == "faq_stock":
            return style_msg(faq_stock())
        if intent == "faq_documents":
            return style_msg(faq_documents())
        if intent == "faq_contacto":
            return style_msg(FAQ["contacto"])
        if intent == "faq_sucursal":
            return style_msg(FAQ["sucursales"])
        if intent == "faq_uso":
            return style_msg(FAQ["uso_web"])
        if intent == "faq_mascarilla_sin":
            return style_msg(FAQ["mascarilla_sin"])
        if intent == "faq_edad":
            return style_msg(FAQ["edad_uso"])
        if intent == "faq_lavado_detalle":
            return style_msg(FAQ["lavado"])
        if intent == "faq_talla_mascota":
            return style_msg(FAQ["talla_mascota"])
        if intent == "faq_vannair":
            return style_msg(FAQ["vannair"])
        return style_msg("¿Alguna duda antes de finalizar?")

    # Intentos sin estado específico
    if intent == "channel_info":
        return style_msg("Disponible en Web, WhatsApp, Instagram y Telegram.")
    if intent == "ask_price":
        return style_msg("¿Para PERSONA o MASCOTA?")
    if intent == "howto":
        return style_msg("¿Para PERSONA o MASCOTA?")
    if intent == "faq_materials":
        return style_msg(faq_materials())
    if intent == "faq_cleaning":
        return style_msg(faq_cleaning())
    if intent == "faq_compatibility":
        return style_msg(faq_compatibility())
    if intent == "faq_stock":
        return style_msg(faq_stock())
    if intent == "faq_documents":
        return style_msg(faq_documents())
    if intent == "faq_contacto":
        return style_msg(FAQ["contacto"])
    if intent == "faq_sucursal":
        return style_msg(FAQ["sucursales"])
    if intent == "faq_uso":
        return style_msg(FAQ["uso_web"] + " (Fuente: página Aerocámara)")
    if intent == "faq_mascarilla_sin":
        return style_msg(FAQ["mascarilla_sin"])
    if intent == "faq_edad":
        return style_msg(FAQ["edad_uso"])
    if intent == "faq_lavado_detalle":
        return style_msg(FAQ["lavado"])
    if intent == "faq_talla_mascota":
        return style_msg(FAQ["talla_mascota"])
    if intent == "faq_vannair":
        return style_msg(FAQ["vannair"])
    if intent == "shipping":
        return style_msg(shipping_text())
    if intent == "warranty":
        return style_msg(warranty_text())
    if intent == "howto":
        return style_msg(FAQ["uso_web"])

    # Atajo de comuna directa
    detected_city, zone = detect_city(user_text)
    if detected_city:
        shipping_info = shipping_info_by_city(detected_city, zone)
        return style_msg(
            f"📍 {detected_city}\n{shipping_info}\n\n¿Continuar con tu pedido?"
        )

    return style_msg("No entendí. ¿Para PERSONA o MASCOTA?")


# ============= Canal: Sitio Web (REST simple) =============
class WebChatMsg(BaseModel):
    user_id: str = Field(..., description="ID único del usuario en el sitio")
    text: str


@app.post("/webchat/send")
def webchat_send(msg: WebChatMsg):
    reply = next_message_logic(channel="web", user_id=msg.user_id, user_text=msg.text)
    return {"reply": reply}


# ============= Canales Meta (WhatsApp + Instagram) =============
@app.get("/meta/webhook")
def meta_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    if hub_mode == "subscribe" and hub_verify_token == META_VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


def meta_send_message(to: str, body: str, channel: str = "whatsapp"):
    if not META_ACCESS_TOKEN:
        print("META_ACCESS_TOKEN not set; skipping send")
        return

    url = None
    data = {}
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    if channel == "whatsapp":
        if not META_WA_PHONE_ID:
            print("META_WA_PHONE_ID not set; skipping whatsapp send")
            return
        url = f"https://graph.facebook.com/v20.0/{META_WA_PHONE_ID}/messages"
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        }
    elif channel == "instagram":
        url = f"https://graph.facebook.com/v20.0/me/messages"
        data = {"recipient": {"id": to}, "message": {"text": body}}
    else:
        print("Canal Meta no soportado")
        return

    try:
        requests.post(url, headers=headers, json=data, timeout=15)
    except Exception as e:
        print("Error META send:", e)


@app.post("/meta/webhook")
async def meta_webhook(request: Request):
    payload = await request.json()
    try:
        if "entry" in payload:
            for entry in payload["entry"]:
                changes = entry.get("changes", [])
                for change in changes:
                    value = change.get("value", {})
                    if value.get("messaging_product") == "whatsapp":
                        messages = value.get("messages", [])
                        for m in messages:
                            from_ = m.get("from")
                            text = m.get("text", {}).get("body", "")
                            reply = next_message_logic("whatsapp", from_, text)
                            meta_send_message(from_, reply, "whatsapp")
                    elif "messaging" in value or change.get("field") == "messages":
                        messaging = value.get("messaging", [])
                        for m in messaging:
                            sender = m.get("sender", {}).get("id")
                            text = m.get("message", {}).get("text", "")
                            if sender and text:
                                reply = next_message_logic("instagram", sender, text)
                                meta_send_message(sender, reply, "instagram")
    except Exception as e:
        print("Error meta_webhook:", e)
    return JSONResponse({"status": "ok"})


# ============= Canal: Telegram (webhook) =============
@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request, x_telegram_bot_api_secret_token: str | None = Header(None)
):
    expected = TELEGRAM_SECRET_TOKEN
    if expected and x_telegram_bot_api_secret_token != expected:
        print(
            f"ERROR: Invalid secret token. Expected: {expected[:10]}..., Got: {x_telegram_bot_api_secret_token[:10] if x_telegram_bot_api_secret_token else 'None'}..."
        )
        return JSONResponse(
            {"ok": False, "error": "invalid secret token"}, status_code=403
        )

    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN no configurado en webhook")
        return JSONResponse({"ok": True})

    update = await request.json()
    print(f"DEBUG: Webhook recibido - update keys: {update.keys()}")

    try:
        # Manejar callback_query (inline buttons)
        callback_query = update.get("callback_query")
        if callback_query:
            chat_id = str(callback_query["message"]["chat"]["id"])
            user_id = str(callback_query["from"]["id"])
            message_id = callback_query["message"]["message_id"]
            callback_id = callback_query["id"]
            callback_data = callback_query.get("data", "")

            print(
                f"DEBUG: Callback recibido - chat_id={chat_id}, callback_data='{callback_data}'"
            )

            reply_msg, inline_kb, reply_kb = handle_callback(
                callback_data, "telegram", user_id, chat_id, message_id, callback_id
            )

            if reply_msg:
                telegram_send_message(
                    chat_id,
                    reply_msg,
                    ctx=get_context(get_session("telegram", user_id)),
                    inline_keyboard=inline_kb,
                    reply_keyboard=reply_kb,
                )

            return JSONResponse({"ok": True})

        # Manejar mensajes de texto
        message = update.get("message") or update.get("edited_message")
        if message and "text" in message:
            chat_id = str(message["chat"]["id"])
            user_id = str(message["from"]["id"])
            text = message["text"]

            # Sanitizar texto antes de loggear (no loggear PII completo)
            safe_text = text[:50] + "..." if len(text) > 50 else text
            print(f"DEBUG: Procesando mensaje de chat_id={chat_id}, text='{safe_text}'")

            # Logging de métricas
            import time

            start_time = time.time()

            reply = next_message_logic("telegram", user_id, text)

            elapsed_time = time.time() - start_time
            _sess = get_session("telegram", user_id)
            print(
                f"METRICS: intent={classify_intent(text)}, state={_sess.state}, response_time={elapsed_time:.2f}s"
            )

            print(f"DEBUG: Respuesta generada: '{reply[:50]}...' (length={len(reply)})")

            telegram_send_message(
                chat_id, reply, state=_sess.state, ctx=get_context(_sess)
            )
        else:
            print(
                f"DEBUG: No hay mensaje de texto en el update. Keys: {message.keys() if message else 'No message'}"
            )
    except Exception as e:
        print(f"ERROR telegram_webhook exception: {e}")
        import traceback

        traceback.print_exc()
    return JSONResponse({"ok": True})


def telegram_send_message(
    chat_id: str,
    text: str,
    state: str | None = None,
    ctx: Optional[Dict] = None,
    inline_keyboard: Optional[dict] = None,
    reply_keyboard: Optional[dict] = None,
):
    """Envía mensaje a Telegram con soporte para ReplyKeyboard e InlineKeyboard."""
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN no configurado")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    data = {"chat_id": chat_id, "text": text}
    reply_markup = {}

    # Prioridad: inline_keyboard explícito > build_inline_keyboard > reply_keyboard explícito > build_keyboard
    if inline_keyboard:
        reply_markup = inline_keyboard
    elif state:
        inline_kb = build_inline_keyboard(state, ctx)
        if inline_kb:
            reply_markup = inline_kb

    # Si no hay inline, usar reply keyboard
    if not reply_markup:
        if reply_keyboard:
            reply_markup = reply_keyboard
        elif state:
            kb = build_keyboard(state)
            if kb:
                reply_markup = kb

    if reply_markup:
        data["reply_markup"] = reply_markup

    try:
        # Sanitizar texto antes de loggear (no loggear PII)
        safe_text = text[:50] + "..." if len(text) > 50 else text
        print(f"DEBUG: Enviando mensaje a chat_id={chat_id}, text_length={len(text)}")
        response = requests.post(url, json=data, timeout=15)
        response_data = response.json()
        if response_data.get("ok"):
            print(f"DEBUG: Mensaje enviado exitosamente a chat_id={chat_id}")
        else:
            print(f"ERROR Telegram API: {response_data}")
    except Exception as e:
        print(f"ERROR Telegram send exception: {e}")
        import traceback

        traceback.print_exc()


def telegram_answer_callback(
    callback_id: str, text: str = "", show_alert: bool = False
):
    """Responde a un callback_query de Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    data = {
        "callback_query_id": callback_id,
        "text": text[:200],  # Max 200 chars
        "show_alert": show_alert,
    }
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"ERROR answering callback: {e}")


def telegram_edit_message(
    chat_id: str, message_id: int, text: str, inline_keyboard: Optional[dict] = None
):
    """Edita un mensaje existente en Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
    data = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if inline_keyboard:
        data["reply_markup"] = inline_keyboard
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"ERROR editing message: {e}")


def handle_callback(
    callback_data: str,
    channel: str,
    user_id: str,
    chat_id: str,
    message_id: int,
    callback_id: str,
) -> tuple[str, Optional[dict], Optional[dict]]:
    """Maneja callbacks de inline buttons. Retorna (mensaje, inline_keyboard, reply_keyboard)."""
    sess = get_session(channel, user_id)
    ctx = get_context(sess)

    if callback_data == "finalize_order":
        save_session(sess, state="DONE")
        reply_msg = get_variant("finalize")
        if not reply_msg:
            reply_msg = style_msg("✓ Pedido listo. ¿Necesitas instrucciones de uso?")
        telegram_answer_callback(callback_id, "Pedido finalizado ✓")
        return (reply_msg, None, {"remove_keyboard": True})

    elif callback_data.startswith("add_unit:"):
        sku_param = callback_data.split(":", 1)[1] if ":" in callback_data else "menu"
        if sku_param == "menu":
            # Mostrar opciones para agregar
            family = ctx.get("family", "")
            if family == "humana":
                reply_msg = style_msg(
                    "¿Qué modelo? Bolso, Mascarilla, Adaptador o Recambio"
                )
            elif family == "mascota":
                reply_msg = style_msg("¿Qué talla? S/M/L")
            else:
                reply_msg = style_msg("Elige: ¿PERSONA o MASCOTA?")
            telegram_answer_callback(callback_id, "Elige el producto a agregar")
            return (reply_msg, None, None)
        else:
            # Agregar SKU específico
            ctx, item = add_to_cart(ctx, sku_param, 1)
            update_context(sess, ctx)
            save_session(sess)
            telegram_answer_callback(callback_id, f"Agregado: {item['nombre']}")
            reply_msg = style_msg(f"{summarize_order(get_context(sess))}")
            inline_kb = build_inline_keyboard("CLOSE", get_context(sess))
            return (reply_msg, inline_kb, None)

    elif callback_data.startswith("see_prices:"):
        family_param = callback_data.split(":", 1)[1] if ":" in callback_data else "all"
        if family_param == "humana" or family_param == "all":
            reply_msg = style_msg(f"Precios para PERSONAS:\n{list_options_human()}")
        elif family_param == "mascota" or family_param == "all":
            reply_msg = style_msg(f"Precios para MASCOTAS:\n{list_options_pet()}")
        else:
            reply_msg = style_msg(
                f"Precios:\n{list_options_human()}\n\n{list_options_pet()}"
            )
        telegram_answer_callback(callback_id, "Aquí están los precios")
        return (reply_msg, None, None)

    elif callback_data == "handoff":
        save_session(sess, state="COLLECT_DATA")
        reply_msg = style_msg(
            "Te derivo a un asesor. Déjame TELÉFONO o EMAIL y comuna."
        )
        telegram_answer_callback(callback_id, "Te contactaremos pronto")
        return (reply_msg, None, None)

    telegram_answer_callback(callback_id, "Acción procesada")
    return ("", None, None)


def telegram_get_updates(offset: int = 0):
    """Obtiene actualizaciones de Telegram usando polling"""
    if not TELEGRAM_BOT_TOKEN:
        return []
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"offset": offset, "timeout": 10}
    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        if data.get("ok"):
            return data.get("result", [])
    except Exception as e:
        print("Error telegram_get_updates:", e)
    return []


def process_telegram_update(update: Dict):
    """Procesa una actualización de Telegram"""
    message = update.get("message") or update.get("edited_message")
    if message and "text" in message:
        chat_id = str(message["chat"]["id"])
        user_id = str(message["from"]["id"])
        text = message["text"]
        reply = next_message_logic("telegram", user_id, text)
        _sess = get_session("telegram", user_id)
        telegram_send_message(chat_id, reply, state=_sess.state, ctx=get_context(_sess))


def telegram_polling_loop():
    """Loop de polling para Telegram (desarrollo local)"""
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN no configurado, polling deshabilitado")
        return

    # Verificar si hay webhook configurado
    try:
        webhook_info = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo",
            timeout=5,
        )
        webhook_data = webhook_info.json()
        if webhook_data.get("ok") and webhook_data.get("result", {}).get("url"):
            print("Webhook ya configurado, polling no iniciado")
            return
    except:
        pass

    print("Iniciando polling de Telegram para desarrollo local...")
    offset = 0
    while True:
        try:
            updates = telegram_get_updates(offset)
            for update in updates:
                process_telegram_update(update)
                offset = update.get("update_id", 0) + 1
            time.sleep(1)
        except KeyboardInterrupt:
            print("Polling detenido por el usuario")
            break
        except Exception as e:
            print(f"Error en polling loop: {e}")
            time.sleep(5)


# Iniciar polling en background si no hay webhook configurado
_polling_thread = None


def start_telegram_polling():
    """Inicia el polling de Telegram en un thread separado"""
    global _polling_thread
    if _polling_thread is None or not _polling_thread.is_alive():
        _polling_thread = threading.Thread(target=telegram_polling_loop, daemon=True)
        _polling_thread.start()


@app.on_event("startup")
async def startup_event():
    """Inicia el polling de Telegram al arrancar la app si no hay webhook"""
    if TELEGRAM_BOT_TOKEN and not TELEGRAM_WEBHOOK_URL:
        start_telegram_polling()


# ============= Admin utilidades =============
@app.get("/admin/order/{order_id}")
def admin_get_order(order_id: int):
    s = db()()
    try:
        o = s.query(Order).filter_by(id=order_id).first()
        if not o:
            raise HTTPException(status_code=404, detail="Order not found")
        return {
            "id": o.id,
            "channel": o.channel,
            "user_id": o.user_id,
            "status": o.status,
            "total_clp": o.total_clp,
            "items": json.loads(o.order_json or "[]"),
            "created_at": o.created_at.isoformat(),
        }
    finally:
        s.close()


@app.get("/admin/lead")
def admin_list_leads():
    s = db()()
    try:
        rows = s.query(Lead).order_by(Lead.created_at.desc()).all()
        return [
            {
                "id": r.id,
                "channel": r.channel,
                "user_id": r.user_id,
                "name": r.name,
                "phone": r.phone,
                "email": r.email,
                "city": r.city,
                "notes": r.notes,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    finally:
        s.close()


# ============= Endpoint para iniciar polling manualmente =============
@app.post("/telegram/start-polling")
def start_polling():
    """Inicia el polling de Telegram manualmente"""
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN no configurado")
    start_telegram_polling()
    return {"status": "ok", "message": "Polling iniciado"}


@app.post("/telegram/delete-webhook")
def delete_webhook():
    """Elimina el webhook de Telegram para usar polling"""
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN no configurado")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook"
    try:
        response = requests.post(url, params={"drop_pending_updates": True}, timeout=10)
        data = response.json()
        if data.get("ok"):
            start_telegram_polling()
            return {"status": "ok", "message": "Webhook eliminado, polling iniciado"}
        else:
            raise HTTPException(
                status_code=400, detail=f"Error: {data.get('description')}"
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ============= Mensajes de prueba rápida =============
@app.get("/")
def root():
    return {"status": "ok", "message": "Chatbot Aerocámaras (CLP) activo"}
