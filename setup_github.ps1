# Script para configurar y subir el proyecto a GitHub
# Uso: .\setup_github.ps1 -RepoName "nombre-del-repo" -RemoteUrl "https://github.com/usuario/repo.git"

param(
    [Parameter(Mandatory=$false)]
    [string]$RepoName = "chatbot-aerocamaras-cl",
    
    [Parameter(Mandatory=$false)]
    [string]$RemoteUrl = ""
)

Write-Host "🚀 Configurando repositorio para GitHub..." -ForegroundColor Cyan

# Verificar si ya existe un remote
$existingRemote = git remote -v 2>$null
if ($existingRemote) {
    Write-Host "⚠️  Ya existe un remote configurado:" -ForegroundColor Yellow
    Write-Host $existingRemote
    $response = Read-Host "¿Deseas cambiar el remote? (s/n)"
    if ($response -eq "s" -or $response -eq "S") {
        git remote remove origin 2>$null
    } else {
        Write-Host "✅ Manteniendo remote existente" -ForegroundColor Green
        exit 0
    }
}

# Si no se proporcionó URL, pedirla
if (-not $RemoteUrl) {
    Write-Host ""
    Write-Host "📝 Opciones para crear el repositorio:" -ForegroundColor Cyan
    Write-Host "1. Crear un nuevo repositorio en GitHub.com manualmente"
    Write-Host "2. O proporcionar la URL del repositorio existente"
    Write-Host ""
    $RemoteUrl = Read-Host "Ingresa la URL del repositorio (ej: https://github.com/usuario/$RepoName.git)"
}

# Configurar remote
if ($RemoteUrl) {
    Write-Host ""
    Write-Host "🔗 Configurando remote: $RemoteUrl" -ForegroundColor Cyan
    git remote add origin $RemoteUrl
    
    Write-Host ""
    Write-Host "✅ Remote configurado correctamente" -ForegroundColor Green
    Write-Host ""
    Write-Host "📤 Para subir el código, ejecuta:" -ForegroundColor Yellow
    Write-Host "   git push -u origin master" -ForegroundColor White
    Write-Host ""
    Write-Host "💡 O si tu rama principal es 'main':" -ForegroundColor Yellow
    Write-Host "   git branch -M main" -ForegroundColor White
    Write-Host "   git push -u origin main" -ForegroundColor White
} else {
    Write-Host "❌ No se proporcionó URL del repositorio" -ForegroundColor Red
}

