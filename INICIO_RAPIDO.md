# 🚀 Inicio Rápido - Chatbot con IA

## 1️⃣ Instalar dependencias

```bash
pip install -r requirements.txt
```

## 2️⃣ Configurar variables de entorno

Crea un archivo `.env` en la raíz del proyecto (puedes copiar `env.template`):

```bash
# Copia el template
copy env.template .env
# o en Linux/Mac:
cp env.template .env
```

**La API key de OpenRouter ya está incluida en el template**, pero puedes obtener tu propia key gratis en:
👉 https://openrouter.ai/

## 3️⃣ Ejecutar el bot

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Verás algo como:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

## 4️⃣ Probar el bot

### Opción A: Script de prueba (recomendado)

Abre otra terminal y ejecuta:

```bash
python test_bot.py
```

### Opción B: Con curl

```bash
curl -X POST http://localhost:8000/webchat/send \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"test123\",\"text\":\"Hola\"}"
```

### Opción C: Con Telegram

1. Crea un bot en Telegram con [@BotFather](https://t.me/botfather)
2. Copia el token y agrégalo al `.env`:
   ```
   TELEGRAM_BOT_TOKEN=tu_token_aqui
   ```
3. Reinicia el bot
4. Habla con tu bot en Telegram

## 5️⃣ Verificar que funciona

Deberías ver respuestas naturales generadas por IA, por ejemplo:

```
👤 Usuario: Hola
🤖 Bot: ¡Hola! 👋 Me da mucho gusto ayudarte. ¿Buscas una aerocámara 
       para una persona o para una mascota?

👤 Usuario: Para mi hijo
🤖 Bot: ¡Perfecto! 😊 Tenemos varias opciones para personas. Déjame 
       mostrarte:
       
       1. Aerocámara con bolso transportador - $21.990
       2. Aerocámara con mascarilla - $25.990
       3. Con adaptador circular - $21.990
       
       ¿Cuál te interesa más? También puedo ayudarte a elegir la mejor 
       según la edad de tu hijo.
```

## 🎉 ¡Listo!

Tu chatbot con IA está funcionando. Ahora puedes:
- Personalizarlo editando el prompt en `app.py`
- Conectarlo a WhatsApp, Instagram o Telegram
- Modificar el catálogo de productos
- Ajustar el flujo de conversación

## ❓ Problemas comunes

### Error: "No module named 'openai'"
```bash
pip install openai
```

### Error: "Connection refused"
Asegúrate de que el bot esté corriendo:
```bash
uvicorn app:app --reload
```

### El bot no responde con IA
Verifica que la API key de OpenRouter esté en el `.env`:
```
OPENROUTER_API_KEY=sk-or-v1-...
```

## 📚 Siguiente paso

Lee el archivo `README_IA.md` para conocer todas las funcionalidades avanzadas.

