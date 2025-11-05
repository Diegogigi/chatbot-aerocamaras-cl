# Script para hacer push a GitHub
# Ejecuta este script DESPUÉS de crear el repositorio en GitHub

Write-Host "🚀 Subiendo código a GitHub..." -ForegroundColor Cyan
Write-Host ""

# Verificar que el remote esté configurado
try {
    $remote = git remote get-url origin
    Write-Host "✅ Remote configurado: $remote" -ForegroundColor Green
    Write-Host ""
} catch {
    Write-Host "❌ Error: No hay remote configurado" -ForegroundColor Red
    Write-Host "Ejecuta primero: git remote add origin https://github.com/diegogigi/chatbot-aerocamaras-cl.git" -ForegroundColor Yellow
    exit 1
}

# Verificar si el repositorio existe
Write-Host "🔍 Verificando si el repositorio existe..." -ForegroundColor Cyan
$checkRepo = git ls-remote --heads origin 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or $checkRepo -match "not found") {
    Write-Host ""
    Write-Host "⚠️  El repositorio no existe en GitHub aún" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "📝 Por favor:" -ForegroundColor Cyan
    Write-Host "   1. Ve a https://github.com/new" -ForegroundColor White
    Write-Host "   2. Nombre: chatbot-aerocamaras-cl" -ForegroundColor White
    Write-Host "   3. Público o Privado (tu elección)" -ForegroundColor White
    Write-Host "   4. NO marques 'Initialize with README'" -ForegroundColor White
    Write-Host "   5. Haz clic en 'Create repository'" -ForegroundColor White
    Write-Host ""
    Write-Host "   Luego ejecuta este script nuevamente" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Repositorio encontrado en GitHub" -ForegroundColor Green
Write-Host ""

# Verificar la rama actual
$currentBranch = git branch --show-current
Write-Host "📌 Rama actual: $currentBranch" -ForegroundColor Cyan
Write-Host ""

# Preguntar si quiere cambiar a 'main'
if ($currentBranch -eq "master") {
    $response = Read-Host "¿Deseas cambiar la rama a 'main'? (s/n) [Recomendado: s]"
    if ($response -eq "s" -or $response -eq "S" -or $response -eq "") {
        git branch -M main
        $currentBranch = "main"
        Write-Host "✅ Rama cambiada a 'main'" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "📤 Subiendo código a GitHub..." -ForegroundColor Cyan
Write-Host ""

# Hacer push
try {
    git push -u origin $currentBranch
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "✅ ¡Código subido exitosamente a GitHub!" -ForegroundColor Green
        Write-Host ""
        Write-Host "🔗 Repositorio: https://github.com/diegogigi/chatbot-aerocamaras-cl" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "📋 Próximo paso: Desplegar en Railway" -ForegroundColor Yellow
        Write-Host "   Lee el archivo DEPLOY.md para las instrucciones" -ForegroundColor White
    } else {
        Write-Host ""
        Write-Host "❌ Error al hacer push. Verifica:" -ForegroundColor Red
        Write-Host "   - Que el repositorio exista en GitHub" -ForegroundColor White
        Write-Host "   - Que tengas permisos para escribir" -ForegroundColor White
        Write-Host "   - Tu conexión a internet" -ForegroundColor White
    }
} catch {
    Write-Host ""
    Write-Host "❌ Error: $_" -ForegroundColor Red
}

