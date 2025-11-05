# Script para configurar el webhook de Telegram en Railway
# Uso: .\config_telegram_railway.ps1 -RailwayUrl "https://tu-app.railway.app"

param(
    [Parameter(Mandatory=$true)]
    [string]$RailwayUrl
)

# Leer el token desde .env
$envContent = Get-Content .env
$token = ""
$secretToken = ""

foreach ($line in $envContent) {
    if ($line -match "^TELEGRAM_BOT_TOKEN=(.+)$") {
        $token = $matches[1].Trim()
    }
    if ($line -match "^TELEGRAM_SECRET_TOKEN=(.+)$") {
        $secretToken = $matches[1].Trim()
    }
}

if (-not $token) {
    Write-Host "Error: No se encontró TELEGRAM_BOT_TOKEN en .env" -ForegroundColor Red
    exit 1
}

if (-not $secretToken) {
    Write-Host "Error: No se encontró TELEGRAM_SECRET_TOKEN en .env" -ForegroundColor Red
    exit 1
}

# Construir la URL del webhook
$webhookUrl = "$RailwayUrl/telegram/webhook"

# Configurar el webhook
$setWebhookUrl = "https://api.telegram.org/bot$token/setWebhook"
$body = @{
    url = $webhookUrl
    secret_token = $secretToken
} | ConvertTo-Json

Write-Host "Configurando webhook de Telegram para Railway..." -ForegroundColor Cyan
Write-Host "URL de Railway: $RailwayUrl" -ForegroundColor Cyan
Write-Host "Webhook URL: $webhookUrl" -ForegroundColor Cyan
Write-Host ""

try {
    $response = Invoke-RestMethod -Uri $setWebhookUrl -Method Post -Body $body -ContentType "application/json"
    
    if ($response.ok) {
        Write-Host "✅ Webhook configurado exitosamente!" -ForegroundColor Green
        Write-Host "Descripción: $($response.description)" -ForegroundColor Green
        
        # Verificar el webhook
        Write-Host ""
        Write-Host "Verificando webhook configurado..." -ForegroundColor Cyan
        $getWebhookUrl = "https://api.telegram.org/bot$token/getWebhookInfo"
        $webhookInfo = Invoke-RestMethod -Uri $getWebhookUrl
        
        Write-Host "✅ URL actual: $($webhookInfo.result.url)" -ForegroundColor Green
        Write-Host "Actualizaciones pendientes: $($webhookInfo.result.pending_update_count)" -ForegroundColor Yellow
        
        Write-Host ""
        Write-Host "🎉 ¡Listo! Ahora puedes chatear con tu bot en Telegram." -ForegroundColor Green
        Write-Host ""
        Write-Host "Para encontrar tu bot:" -ForegroundColor Cyan
        Write-Host "1. Abre Telegram" -ForegroundColor White
        Write-Host "2. Busca el bot usando el token o nombre que configuraste en @BotFather" -ForegroundColor White
        Write-Host "3. Envía un mensaje como 'Hola' o '/start'" -ForegroundColor White
    } else {
        Write-Host "❌ Error al configurar webhook: $($response.description)" -ForegroundColor Red
    }
} catch {
    Write-Host "❌ Error al conectar con la API de Telegram:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
}
