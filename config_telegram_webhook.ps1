# Script para configurar el webhook de Telegram
# Uso: .\config_telegram_webhook.ps1 -WebhookUrl "https://tu-url-publica.com/telegram/webhook"

param(
    [Parameter(Mandatory=$true)]
    [string]$WebhookUrl
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

# Verificar que la URL termine con /telegram/webhook
if (-not $WebhookUrl.EndsWith("/telegram/webhook")) {
    Write-Host "Advertencia: La URL debería terminar con /telegram/webhook" -ForegroundColor Yellow
}

# Configurar el webhook
$setWebhookUrl = "https://api.telegram.org/bot$token/setWebhook"
$body = @{
    url = $WebhookUrl
    secret_token = $secretToken
} | ConvertTo-Json

Write-Host "Configurando webhook de Telegram..." -ForegroundColor Cyan
Write-Host "URL: $WebhookUrl" -ForegroundColor Cyan
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
        
        Write-Host "URL actual: $($webhookInfo.result.url)" -ForegroundColor Yellow
        Write-Host "Pendiente de actualización: $($webhookInfo.result.pending_update_count)" -ForegroundColor Yellow
    } else {
        Write-Host "❌ Error al configurar webhook: $($response.description)" -ForegroundColor Red
    }
} catch {
    Write-Host "❌ Error al conectar con la API de Telegram:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
}

