# chatbot-aerocamaras-cl

Chatbot vendedor **multicanal** (Telegram, WhatsApp, Instagram y Web) para **aerocámaras plegables** (humanas y mascotas), con **tono técnico-médico y vendedor empático**, precios en **CLP** y **flujo de cierre de ventas**.

## 🚀 Inicio rápido

### Local (desarrollo)

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env  # edita valores
uvicorn app:app --host 0.0.0.0 --port 8000
```

**Nota:** Para desarrollo local, el bot usa **polling automático** (no requiere webhook). Se inicia automáticamente al arrancar la aplicación si no hay `TELEGRAM_WEBHOOK_URL` configurado.

### Railway (producción)

1. Conecta tu repositorio de GitHub a Railway
2. Configura las variables de entorno en Railway:
   - `TELEGRAM_BOT_TOKEN`: Tu token de BotFather
   - `TELEGRAM_WEBHOOK_URL`: `https://tu-app.railway.app/telegram/webhook`
   - `TELEGRAM_SECRET_TOKEN`: Un token secreto único y largo
   - `APP_BASE_URL`: `https://tu-app.railway.app`
   - `APP_ENV`: `prod`
3. Railway detectará automáticamente el `Procfile` y desplegará la aplicación
4. Una vez desplegado, configura el webhook de Telegram usando el script `config_telegram_webhook.ps1` o manualmente

Asegura HTTPS público para el webhook (Railway lo proporciona automáticamente).

## 🔗 Conectar Telegram

### Desarrollo local (polling automático)

El bot usa **polling automático** en desarrollo local. Solo configura:
1. Crea/regenera el token en **@BotFather** y colócalo en `.env` (`TELEGRAM_BOT_TOKEN`)
2. Deja `TELEGRAM_WEBHOOK_URL` vacío o no lo configures
3. Inicia la aplicación y el polling comenzará automáticamente

### Producción (webhook)

Para producción en Railway (o cualquier servidor con HTTPS):

1. Crea/regenera el token en **@BotFather** y colócalo en las variables de entorno
2. Configura `TELEGRAM_WEBHOOK_URL` con la URL de tu aplicación (ej: `https://tu-app.railway.app/telegram/webhook`)
3. Configura el webhook usando el script PowerShell:
   ```powershell
   .\config_telegram_webhook.ps1 -WebhookUrl "https://tu-app.railway.app/telegram/webhook"
   ```

   O manualmente con curl:
   ```bash
   curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
     -H "Content-Type: application/json" \
     -d '{"url": "https://tu-app.railway.app/telegram/webhook", "secret_token": "TU_SECRET_TOKEN"}'
   ```

4. Verifica el webhook:
   ```bash
   curl -X GET "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"
   ```

## 🧠 Flujo conversacional (FSM)

`START → QUALIFY → (HUMAN_DETAIL | PET_DETAIL) → COLLECT_DATA → CLOSE → DONE`

- Califica si es **Persona** (Adulto/Pediátrico) o **Mascota** (Gato/Perro Pequeño/Mediano/Grande).
- Añade al carrito, solicita **nombre, comuna/ciudad, teléfono/email**, genera **resumen** y link de pago **demo**.
- Soporta preguntas: **precio**, **envío**, **garantía**, **uso**, **talla/modelo** y **cierre**.

## 🧾 Catálogo (CLP)

Define productos y precios en `app.py` (constante `CATALOGO`).

## 💳 Pago

`generate_payment_link` devuelve un **placeholder**. Integra **Webpay/Khipu/MercadoPago** según prefieras.

## 🛡️ Seguridad

- **No** publiques tu token de Telegram. Si se filtró, **revócalo** y genera uno nuevo.
- Puedes activar validación del webhook con `TELEGRAM_SECRET_TOKEN`.

## 📂 Estructura

```
chatbot-aerocamaras-cl/
├─ app.py                 # Aplicación principal FastAPI
├─ requirements.txt       # Dependencias Python
├─ .env.example          # Plantilla de variables de entorno
├─ .gitignore            # Archivos ignorados por Git
├─ Procfile              # Configuración para Railway
├─ runtime.txt           # Versión de Python para Railway
├─ README.md             # Este archivo
├─ run.sh                # Script de ejecución
├─ config_telegram_webhook.ps1  # Script para configurar webhook
├─ docker-compose.yml    # Configuración Docker Compose
└─ docker/
   └─ Dockerfile         # Imagen Docker
```

## 🐳 Docker (opcional)

```bash
docker compose up --build
```

## ✅ Prueba local (Webchat)

```bash
curl -X POST http://localhost:8000/webchat/send -H "Content-Type: application/json" -d '{"user_id":"test","text":"Hola"}'
```

---

Hecho para abrir directo en **Cursor**. ¡Éxitos con las ventas!


## ⌨️ Teclado rápido (ReplyKeyboard)
El bot muestra un teclado contextual según el estado (Persona/Mascota, Adulto/Pediátrico, tamaños, Finalizar, etc.).
No necesitas hacer nada extra: ya está activo en el endpoint de Telegram.
