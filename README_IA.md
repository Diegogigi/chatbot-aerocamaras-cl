# Chatbot Aerocámaras con IA (OpenRouter)

Bot de ventas multicanal potenciado con IA usando OpenRouter y el modelo `openai/gpt-oss-20b:free`.

## 🚀 Mejoras implementadas

### ✅ Eliminados botones y sugerencias
- Se eliminaron todos los botones de respuesta rápida
- Se eliminó el botón "Contactar asesor"
- Conversación más fluida y natural

### 🤖 Integración con IA
- Respuestas generadas con modelo GPT-OSS-20B (gratuito)
- Contexto completo del catálogo de productos
- Personalidad amigable y profesional
- Manejo inteligente de FAQ
- Respuestas adaptadas al estado de la conversación

## 📦 Instalación

1. **Instalar dependencias:**
```bash
pip install -r requirements.txt
```

2. **Configurar variables de entorno:**

Copia el archivo `env.template` a `.env` y configura tus credenciales:

```bash
cp env.template .env
```

Edita el archivo `.env` con tus datos:
- `OPENROUTER_API_KEY`: Tu API key de OpenRouter (ya incluida por defecto)
- `TELEGRAM_BOT_TOKEN`: Token de tu bot de Telegram (opcional)
- `META_ACCESS_TOKEN`: Token para WhatsApp/Instagram (opcional)

3. **Ejecutar el bot:**

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

## 🎯 Características del modelo de IA

El bot ahora usa IA para:
- **Saludos inteligentes**: Respuestas naturales y variadas
- **Consultas de productos**: Explica características y precios de forma contextual
- **FAQ automático**: Responde preguntas frecuentes con información del negocio
- **Flujo de compra**: Guía al cliente de forma natural en el proceso
- **Post-venta**: Soporte y dudas después de la compra

## 📝 Modelo utilizado

- **Proveedor**: OpenRouter
- **Modelo**: `openai/gpt-oss-20b:free`
- **Ventajas**:
  - Completamente GRATIS
  - Sin límites de uso
  - Respuestas de alta calidad
  - Latencia baja

## 🔧 Configuración avanzada

### Cambiar el modelo de IA

Puedes cambiar el modelo editando `OPENROUTER_MODEL` en el archivo `.env`:

```bash
# Opciones gratuitas en OpenRouter:
OPENROUTER_MODEL=openai/gpt-oss-20b:free
OPENROUTER_MODEL=google/gemma-2-9b-it:free
OPENROUTER_MODEL=meta-llama/llama-3-8b-instruct:free
```

### Ajustar el prompt del sistema

El prompt del sistema está en la función `generate_ai_response()` en `app.py`. Puedes modificarlo para:
- Cambiar el tono de las respuestas
- Agregar más información del negocio
- Personalizar el estilo de comunicación

## 🌐 Canales soportados

- **Web**: Endpoint `/webchat/send`
- **Telegram**: Webhook `/telegram/webhook`
- **WhatsApp**: Webhook `/meta/webhook`
- **Instagram**: Webhook `/meta/webhook`

## 📊 Estado de la conversación

El bot mantiene estos estados:
- `START`: Inicio de conversación
- `QUALIFY`: Calificación (persona o mascota)
- `HUMAN_DETAIL`: Productos para humanos
- `PET_DETAIL`: Productos para mascotas
- `COLLECT_DATA`: Recolección de datos del cliente
- `CLOSE`: Post-venta

## 🎨 Personalización

Para personalizar las respuestas, edita el `system_prompt` en la función `generate_ai_response()`:

```python
system_prompt = f"""Eres un asistente de ventas amigable...
[Modifica aquí el comportamiento del bot]
"""
```

## 📱 Prueba rápida

Prueba el bot con curl:

```bash
curl -X POST http://localhost:8000/webchat/send \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test123","text":"Hola, necesito una aerocámara"}'
```

## 🔍 Monitoreo

El bot imprime logs en consola con:
- Intents detectados
- Estados de conversación
- Tiempo de respuesta
- Errores de IA

## 💡 Ventajas de este enfoque

1. **Respuestas más naturales**: El modelo entiende el contexto
2. **Menos mantenimiento**: No necesitas actualizar respuestas hardcodeadas
3. **Escalable**: Fácil agregar nuevos productos o FAQ
4. **Multiidioma**: Podrías hacerlo responder en otros idiomas
5. **Gratis**: El modelo usado es completamente gratuito

## 🆘 Soporte

Si tienes problemas:
1. Verifica que todas las dependencias estén instaladas
2. Revisa que el archivo `.env` esté configurado
3. Verifica los logs en consola

## 📝 Notas importantes

- El bot sigue usando la lógica FSM para el flujo de compra (agregar al carrito, recolectar datos)
- La IA solo se usa para generar respuestas conversacionales
- Los datos se persisten en SQLite (`chatbot.db`)
- El link de pago es de ejemplo, debes integrar tu pasarela real

¡Disfruta tu chatbot potenciado con IA! 🚀

