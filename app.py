
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
engine = create_engine("sqlite:///chatbot.db", connect_args={"check_same_thread": False})
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
    context = Column(Text)      # JSON con datos de conversación
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

# ============= Catálogo (CLP, Chile) =============
CATALOGO = {
    "humana": {
        "adulto": {"sku": "AERO-H-ADUL", "nombre": "Aerocámara Plegable Humana Adulto", "precio_clp": 26990},
        "pediatrico": {"sku": "AERO-H-PED", "nombre": "Aerocámara Plegable Humana Pediátrica", "precio_clp": 24990},
    },
    "mascota": {
        "gato_peq": {"sku": "AERO-M-GP", "nombre": "Aerocámara Plegable Mascotas (Gato/Perro Pequeño)", "precio_clp": 22990},
        "perro_med": {"sku": "AERO-M-PM", "nombre": "Aerocámara Plegable Mascotas (Perro Mediano)", "precio_clp": 24990},
        "perro_grande": {"sku": "AERO-M-PG", "nombre": "Aerocámara Plegable Mascotas (Perro Grande)", "precio_clp": 27990},
    }
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
            sess = SessionState(channel=channel, user_id=user_id, state="START", context=json.dumps({}))
            s.add(sess)
            s.commit()
            s.refresh(sess)
        return sess
    finally:
        s.close()

def save_session(sess: SessionState, state: Optional[str] = None, ctx: Optional[Dict] = None):
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
    return ("[Asesor Médico-Veterinario] Hola, soy tu asesor de Aerocámaras Plegables en Chile. "
            "Te acompaño paso a paso para recomendar el tamaño correcto y cerrar tu compra de forma segura y rápida. ")

def vendedor_prefix() -> str:
    return ("[Vendedor Amable] ¡Excelente! Te explico en simple y vamos atajando dudas. ")

def style_msg(text: str) -> str:
    return f"{asis_prefix()}{vendedor_prefix()}{text}"

# ============= Telegram ReplyKeyboard =============
def build_keyboard(state: str | None) -> dict | None:
    """Devuelve un reply_markup con teclado rápido según el estado."""
    rows: list[list[str]] = []
    st = (state or '').upper()
    if st in ('START', 'QUALIFY', ''):
        rows = [["Persona", "Mascota"], ["Precio", "Envío"], ["Hablar con asesor"]]
    elif st == 'HUMAN_DETAIL':
        rows = [["Adulto", "Pediátrico"], ["Ver precios", "Envío"], ["Volver"]]
    elif st == 'PET_DETAIL':
        rows = [["Gato/Perro Pequeño"], ["Perro Mediano", "Perro Grande"], ["Ver precios", "Envío"], ["Volver"]]
    elif st == 'COLLECT_DATA':
        rows = [["Enviar datos"], ["Envío", "Garantía"], ["Hablar con asesor"]]
    elif st == 'CLOSE':
        rows = [["Finalizar", "Agregar otra unidad"], ["Instrucciones", "Envío"], ["Garantía"]]
    elif st == 'DONE':
        rows = [["Instrucciones"], ["Nuevo pedido"]]
    if not rows:
        return None
    return {"keyboard": [[{"text": b} for b in r] for r in rows], "resize_keyboard": True, "one_time_keyboard": False}


# ============= NLU simple (reglas) =============
def classify_intent(text: str) -> str:
    t = (text or "").strip().lower()
    if any(k in t for k in ["hola", "buenas", "buenos días", "buenas tardes", "buenas noches", "start", "/start"]):
        return "greet"
    if any(k in t for k in ["humana", "persona", "adulto", "pediátric", "niño", "niña"]):
        return "want_human"
    if any(k in t for k in ["mascota", "perro", "gato"]):
        return "want_pet"
    if any(k in t for k in ["precio", "cuánto", "cuanto", "vale", "cost"]):
        return "ask_price"
    if any(k in t for k in ["comprar", "orden", "pedido", "quiero", "cómpralo", "lo compro", "pagar"]):
        return "buy"
    if any(k in t for k in ["envío", "retiro", "despacho", "costo envío"]):
        return "shipping"
    if any(k in t for k in ["garantía", "devolución", "cambio"]):
        return "warranty"
    if any(k in t for k in ["ayuda", "asesoría", "uso", "cómo usar"]):
        return "howto"
    if any(k in t for k in ["tamaño", "medida", "size", "modelo"]):
        return "sizing"
    # Hooks de teclado
    if any(k in t for k in ["ver precios"]):
        return "ask_price"
    if any(k in t for k in ["volver"]):
        return "greet"
    if any(k in t for k in ["nuevo pedido"]):
        return "greet"
    if any(k in t for k in ["hablar con asesor"]):
        return "handoff"
    if any(k in t for k in ["instagram", "whatsapp", "telegram", "web"]):
        return "channel_info"
    return "unknown"

# ============= Respuestas de producto / pricing =============
def format_price(clp: float) -> str:
    return f"${int(round(clp, 0)):,}".replace(",", ".")

def list_options_human() -> str:
    items = CATALOGO["humana"]
    lines = [f"- {v['nombre']}: {format_price(v['precio_clp'])} (SKU {v['sku']})" for v in items.values()]
    return "\\n".join(lines)

def list_options_pet() -> str:
    items = CATALOGO["mascota"]
    lines = [f"- {v['nombre']}: {format_price(v['precio_clp'])} (SKU {v['sku']})" for v in items.values()]
    return "\\n".join(lines)

def shipping_text() -> str:
    return ("Despachamos a todo Chile. En RM, 24–48 h hábiles; regiones, 48–96 h hábiles aprox. "
            "Costo referencial desde $3.000 (según comuna/ciudad y peso). Retiro en bodega RM previa coordinación.")

def warranty_text() -> str:
    return ("Garantía legal 6 meses por fallas de fabricación. Cambios/devoluciones según Ley Pro-Consumidor en Chile. "
            "Soporte técnico y educación de uso incluidos.")

def howto_text(tipo: str) -> str:
    if tipo == "humana":
        return ("Para personas: agita el inhalador, acóplalo a la aerocámara, sella en boca, presiona 1 puff, "
                "inhala lenta y profundamente 5–6 veces. En pediatría, sella en boca/nariz con mascarilla y cuenta respiraciones.")
    else:
        return ("Para mascotas: acopla el inhalador, sella suavemente la mascarilla en hocico, administra 1 puff, "
                "permite 5–6 respiraciones tranquilas. Refuerza con caricias/premios para habituación positiva.")

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
    cart.append({"sku": item["sku"], "nombre": item["nombre"], "precio_clp": item["precio_clp"], "qty": qty})
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
        lines.append(f"• {i['nombre']} x{i.get('qty',1)} — {format_price(i['precio_clp']*i.get('qty',1))}")
    total = cart_total(cart)
    lines.append(f"Total (CLP): {format_price(total)}")
    return "\\n".join(lines)

def generate_payment_link(order_id: int, total: float) -> str:
    return f"{APP_BASE_URL}/pagar?order_id={order_id}&monto={int(total)}"

def persist_order(channel: str, user_id: str, ctx: Dict) -> Tuple[int, float]:
    s = db()()
    try:
        total = cart_total(ctx.get("cart", []))
        ord = Order(channel=channel, user_id=user_id, order_json=json.dumps(ctx.get("cart", [])), total_clp=total)
        s.add(ord)
        s.commit()
        s.refresh(ord)
        return ord.id, total
    finally:
        s.close()

def persist_lead(channel: str, user_id: str, name: str = "", phone: str = "", email: str = "", city: str = "", notes: str = ""):
    s = db()()
    try:
        lead = Lead(channel=channel, user_id=user_id, name=name, phone=phone, email=email, city=city, notes=notes)
        s.add(lead)
        s.commit()
    finally:
        s.close()

# ============= Política de conversación (FSM) =============
def next_message_logic(channel: str, user_id: str, user_text: str) -> str:
    sess = get_session(channel, user_id)
    ctx = get_context(sess)
    intent = classify_intent(user_text)

    if sess.state == "START":
        update_context(sess, {"cart": []})
        save_session(sess, state="QUALIFY")
        return style_msg(
            "¿Buscas aerocámara para PERSONA o para MASCOTA? "
            "Si es para persona, indícame ADULTO o PEDIÁTRICO. "
            "Si es para mascota, indícame GATO/PERRO y tamaño (pequeño, mediano, grande)."
        )

    if sess.state == "QUALIFY":
        if intent == "handoff":
            return style_msg("Listo, te derivo a un asesor humano. Déjame tu número o correo y te contactamos a la brevedad.")
        if intent in ["want_human", "want_pet", "sizing"]:
            txt = user_text.lower()
            if any(k in txt for k in ["humana", "persona", "adulto", "pediá"]):
                update_context(sess, {"family": "humana"})
                save_session(sess, state="HUMAN_DETAIL")
                return style_msg(
                    "Perfecto. Opciones para PERSONAS:\\n"
                    f"{list_options_human()}\\n\\n"
                    "¿Prefieres ADULTO o PEDIÁTRICO?"
                )
            if any(k in txt for k in ["mascota", "perro", "gato"]):
                update_context(sess, {"family": "mascota"})
                save_session(sess, state="PET_DETAIL")
                return style_msg(
                    "Excelente. Opciones para MASCOTAS:\\n"
                    f"{list_options_pet()}\\n\\n"
                    "¿Es GATO/Perro pequeño, Perro mediano o Perro grande?"
                )
            return style_msg("¿Persona (adulto/pediátrico) o Mascota (gato/perro pequeño/mediano/grande)?")

        if intent == "ask_price":
            return style_msg("Con gusto: dime si es para PERSONA o MASCOTA y te muestro precios exactos.")
        if intent == "buy":
            save_session(sess, state="QUALIFY")
            return style_msg("Para ayudarte a comprar, primero definamos el modelo (Persona o Mascota).")

    if sess.state == "HUMAN_DETAIL":
        txt = user_text.lower()
        if "adult" in txt:
            sku = CATALOGO["humana"]["adulto"]["sku"]
            ctx, item = add_to_cart(ctx, sku)
            update_context(sess, ctx)
            save_session(sess, state="COLLECT_DATA")
            return style_msg(
                f"Agregué {item['nombre']} al carrito ({format_price(item['precio_clp'])}).\\n"
                f"{summarize_order(ctx)}\\n\\n"
                "Para emitir la orden necesito tu NOMBRE, COMUNA/CIUDAD y TELÉFONO o EMAIL."
            )
        if any(k in txt for k in ["pediatr", "niñ"]):
            sku = CATALOGO["humana"]["pediatrico"]["sku"]
            ctx, item = add_to_cart(ctx, sku)
            update_context(sess, ctx)
            save_session(sess, state="COLLECT_DATA")
            return style_msg(
                f"Agregué {item['nombre']} al carrito ({format_price(item['precio_clp'])}).\\n"
                f"{summarize_order(ctx)}\\n\\n"
                "Para avanzar, indícame tu NOMBRE, COMUNA/CIUDAD y TELÉFONO o EMAIL."
            )
        if intent == "sizing":
            return style_msg("¿ADULTO o PEDIÁTRICO?")

    if sess.state == "PET_DETAIL":
        txt = user_text.lower()
        if any(k in txt for k in ["gato", "peque"]):
            sku = CATALOGO["mascota"]["gato_peq"]["sku"]
        elif "med" in txt:
            sku = CATALOGO["mascota"]["perro_med"]["sku"]
        elif any(k in txt for k in ["gran", "grande"]):
            sku = CATALOGO["mascota"]["perro_grande"]["sku"]
        else:
            sku = None

        if sku:
            ctx, item = add_to_cart(ctx, sku)
            update_context(sess, ctx)
            save_session(sess, state="COLLECT_DATA")
            return style_msg(
                f"Agregué {item['nombre']} al carrito ({format_price(item['precio_clp'])}).\\n"
                f"{summarize_order(ctx)}\\n\\n"
                "Para emitir la orden necesito el NOMBRE del responsable, COMUNA/CIUDAD y TELÉFONO o EMAIL."
            )
        if intent == "sizing":
            return style_msg("¿Gato/Perro pequeño, Perro mediano o Perro grande?")
        if intent == "ask_price":
            return style_msg(f"Claro, estas son las opciones:\\n{list_options_pet()}\\n¿Cuál prefieres?")

    if sess.state == "COLLECT_DATA":
        if intent == "handoff":
            return style_msg("Un asesor te contactará. Por favor deja TELÉFONO o EMAIL y comuna para priorizar el contacto.")
        name = ctx.get("name")
        city = ctx.get("city")
        phone = ctx.get("phone")
        email = ctx.get("email")

        t = user_text.strip()
        if "@" in t and "." in t:
            email = t
        elif any(k in t.lower() for k in ["rm", "santiago", "providencia", "las condes", "ñuñoa", "puente alto", "maipú", "maipu", "valparaíso", "viña", "conce", "concepción"]):
            city = t
        elif any(c.isdigit() for c in t) and len(t) >= 8:
            phone = t
        else:
            if len(t.split()) >= 1 and len(t) >= 3:
                name = t if not name else name

        update_context(sess, {"name": name, "city": city, "phone": phone, "email": email})

        missing = []
        if not name: missing.append("NOMBRE")
        if not city: missing.append("COMUNA/CIUDAD")
        if not (phone or email): missing.append("TELÉFONO o EMAIL")

        if missing:
            return style_msg(f"Perfecto, me faltan: {', '.join(missing)}.")

        persist_lead(channel, user_id, name=name or "", phone=phone or "", email=email or "", city=city or "")
        order_id, total = persist_order(channel, user_id, get_context(sess))
        pay_link = generate_payment_link(order_id, total)

        save_session(sess, state="CLOSE")
        return style_msg(
            f"{summarize_order(get_context(sess))}\\n\\n"
            f"Datos de cliente: {name} — {city} — {phone or email}\\n\\n"
            f"{shipping_text()}\\n{warranty_text()}\\n\\n"
            f"Para cerrar, te dejo link de pago seguro (demo): {pay_link}\\n"
            "Una vez confirmado, coordinamos despacho. ¿Deseas agregar otra unidad o accesorio?"
        )

    if sess.state == "CLOSE":
        if intent == "handoff":
            return style_msg("Te conecto con un asesor. ¿Podrías confirmar tu TELÉFONO o EMAIL?")
        if intent == "buy":
            return style_msg("Indícame el modelo o tamaño que deseas agregar, o escribe 'finalizar' para cerrar.")
        if "finalizar" in user_text.lower():
            save_session(sess, state="DONE")
            return style_msg("¡Listo! Te envié el resumen y el enlace de pago. ¿Necesitas instrucciones de uso o soporte?")
        if intent == "howto":
            fam = get_context(sess).get("family", "humana")
            return style_msg(howto_text("humana" if fam == "humana" else "mascota"))
        if intent == "shipping":
            return style_msg(shipping_text())
        if intent == "warranty":
            return style_msg(warranty_text())
        return style_msg("¿Hay alguna duda técnica o de precio que quieras resolver antes de finalizar?")

    if intent == "channel_info":
        return style_msg("Estoy disponible en Sitio Web, WhatsApp, Instagram y Telegram. ¿Por cuál prefieres continuar?")
    if intent == "ask_price":
        return style_msg("¿Para PERSONA o MASCOTA? Así te doy el precio exacto y la recomendación correcta.")
    if intent == "howto":
        return style_msg("¿Es para PERSONA o para MASCOTA? Te explico el uso paso a paso acorde a tu caso.")
    return style_msg("No me quedó claro. ¿Es para PERSONA (adulto/pediátrico) o MASCOTA (gato/perro y tamaño)?")

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
        "Content-Type": "application/json"
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
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(None)):
    expected = TELEGRAM_SECRET_TOKEN
    if expected and x_telegram_bot_api_secret_token != expected:
        return JSONResponse({"ok": False, "error": "invalid secret token"}, status_code=403)

    if not TELEGRAM_BOT_TOKEN:
        return JSONResponse({"ok": True})
    update = await request.json()
    try:
        message = update.get("message") or update.get("edited_message")
        if message and "text" in message:
            chat_id = str(message["chat"]["id"])
            text = message["text"]
            reply = next_message_logic("telegram", chat_id, text)
            # obtiene estado actual para decidir teclado
            _sess = get_session("telegram", chat_id)
            telegram_send_message(chat_id, reply, state=_sess.state)
    except Exception as e:
        print("Error telegram_webhook:", e)
    return JSONResponse({"ok": True})

def telegram_send_message(chat_id: str, text: str, state: str | None = None):
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN no configurado")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    kb = build_keyboard(state)
    data = {"chat_id": chat_id, "text": text}
    if kb:
        data["reply_markup"] = kb
    try:
        requests.post(url, json=data, timeout=15)
    except Exception as e:
        print("Error Telegram send:", e)

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
        text = message["text"]
        reply = next_message_logic("telegram", chat_id, text)
        _sess = get_session("telegram", chat_id)
        telegram_send_message(chat_id, reply, state=_sess.state)

def telegram_polling_loop():
    """Loop de polling para Telegram (desarrollo local)"""
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN no configurado, polling deshabilitado")
        return
    
    # Verificar si hay webhook configurado
    try:
        webhook_info = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo", timeout=5)
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
        return [{
            "id": r.id,
            "channel": r.channel,
            "user_id": r.user_id,
            "name": r.name,
            "phone": r.phone,
            "email": r.email,
            "city": r.city,
            "notes": r.notes,
            "created_at": r.created_at.isoformat()
        } for r in rows]
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
            raise HTTPException(status_code=400, detail=f"Error: {data.get('description')}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# ============= Mensajes de prueba rápida =============
@app.get("/")
def root():
    return {"status": "ok", "message": "Chatbot Aerocámaras (CLP) activo"}
