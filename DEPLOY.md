# 🚀 Guía de Despliegue - Railway

## Paso 1: Subir a GitHub

### Opción A: Usar el script (recomendado)
```powershell
.\setup_github.ps1 -RepoName "chatbot-aerocamaras-cl"
```

### Opción B: Manual

1. **Crear el repositorio en GitHub:**
   - Ve a https://github.com/new
   - Nombre: `chatbot-aerocamaras-cl` (o el que prefieras)
   - Crea el repositorio (público o privado)

2. **Conectar y subir el código:**
   ```powershell
   # Conectar con GitHub
   git remote add origin https://github.com/TU_USUARIO/chatbot-aerocamaras-cl.git
   
   # Cambiar a 'main' si tu repositorio usa 'main' en lugar de 'master'
   git branch -M main
   
   # Subir el código
   git push -u origin main
   ```

## Paso 2: Desplegar en Railway

### 2.1 Crear cuenta y proyecto

1. Ve a [Railway.app](https://railway.app)
2. Inicia sesión con GitHub
3. Haz clic en **"New Project"**
4. Selecciona **"Deploy from GitHub repo"**
5. Elige tu repositorio `chatbot-aerocamaras-cl`

### 2.2 Configurar variables de entorno

Railway detectará automáticamente el `Procfile` y desplegará tu aplicación. Pero necesitas configurar las variables de entorno:

1. En tu proyecto de Railway, ve a **"Variables"**
2. Agrega las siguientes variables:

```
TELEGRAM_BOT_TOKEN=8445036013:AAHJ9Ooi2GSDIakM6g_wXQYiYmnVNKbBxpY
TELEGRAM_SECRET_TOKEN=telegram_secret_token_aerocamaras_2024_secure
APP_ENV=prod
```

**⚠️ IMPORTANTE:** No configures `TELEGRAM_WEBHOOK_URL` ni `APP_BASE_URL` todavía. Primero necesitas obtener la URL de tu aplicación.

### 2.3 Obtener la URL de tu aplicación

1. Después de que Railway despliegue tu aplicación, verás un dominio tipo: `tu-app-production.up.railway.app`
2. Copia esta URL completa

### 2.4 Configurar las URLs restantes

Vuelve a **"Variables"** en Railway y agrega:

```
TELEGRAM_WEBHOOK_URL=https://tu-app-production.up.railway.app/telegram/webhook
APP_BASE_URL=https://tu-app-production.up.railway.app
```

Railway reiniciará automáticamente tu aplicación con las nuevas variables.

## Paso 3: Configurar el Webhook de Telegram

Una vez que tu aplicación esté desplegada y funcionando:

### Opción A: Usar el script PowerShell

```powershell
.\config_telegram_webhook.ps1 -WebhookUrl "https://tu-app-production.up.railway.app/telegram/webhook"
```

### Opción B: Usar curl o PowerShell manualmente

```powershell
$token = "8445036013:AAHJ9Ooi2GSDIakM6g_wXQYiYmnVNKbBxpY"
$webhookUrl = "https://tu-app-production.up.railway.app/telegram/webhook"
$secretToken = "telegram_secret_token_aerocamaras_2024_secure"

$body = @{
    url = $webhookUrl
    secret_token = $secretToken
} | ConvertTo-Json

Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/setWebhook" `
    -Method Post `
    -Body $body `
    -ContentType "application/json"
```

### Verificar el webhook

```powershell
$token = "8445036013:AAHJ9Ooi2GSDIakM6g_wXQYiYmnVNKbBxpY"
Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/getWebhookInfo"
```

Deberías ver tu URL configurada.

## Paso 4: Probar el bot

1. Abre Telegram y busca tu bot
2. Envía un mensaje (ej: "Hola")
3. El bot debería responder automáticamente

## 🔧 Troubleshooting

### El bot no responde

1. **Verifica los logs en Railway:**
   - Ve a tu proyecto → "Deployments" → Selecciona el deployment más reciente → "View Logs"
   - Busca errores relacionados con Telegram

2. **Verifica que el webhook esté configurado:**
   ```powershell
   $token = "8445036013:AAHJ9Ooi2GSDIakM6g_wXQYiYmnVNKbBxpY"
   Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/getWebhookInfo"
   ```

3. **Verifica las variables de entorno en Railway:**
   - Asegúrate de que todas las variables estén correctamente configuradas
   - Verifica que no haya espacios extra o caracteres incorrectos

### Error 403 en el webhook

- Verifica que `TELEGRAM_SECRET_TOKEN` en Railway coincida exactamente con el que usaste al configurar el webhook

### La aplicación no inicia

- Verifica que el `Procfile` esté correcto: `web: uvicorn app:app --host 0.0.0.0 --port $PORT`
- Verifica los logs en Railway para ver errores específicos

## 📝 Notas importantes

- **Seguridad:** Nunca subas tu `.env` a GitHub. Ya está en `.gitignore`
- **Base de datos:** Railway creará una nueva base de datos SQLite en cada deploy. Si necesitas persistencia, considera usar una base de datos externa (PostgreSQL, etc.)
- **Dominio personalizado:** Railway te permite configurar un dominio personalizado si lo deseas
- **Escalado:** Railway maneja automáticamente el escalado según el tráfico

## 🎉 ¡Listo!

Tu chatbot debería estar funcionando en producción. Si necesitas hacer cambios:

1. Haz commit de tus cambios
2. Haz push a GitHub
3. Railway desplegará automáticamente la nueva versión

