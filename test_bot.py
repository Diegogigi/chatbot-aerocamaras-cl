"""
Script de prueba para el chatbot con IA
Ejecuta este script para probar el bot localmente sin necesidad de Telegram o WhatsApp
"""

import requests
import json

BASE_URL = "http://localhost:8000"

def test_conversation():
    """Simula una conversación completa con el bot"""
    
    user_id = "test_user_123"
    
    # Conversación de ejemplo
    messages = [
        "Hola",
        "Necesito una aerocámara para mi hijo",
        "¿Cuál es la diferencia entre la de bolso y la de mascarilla?",
        "Quiero la de mascarilla",
        "Juan Pérez",
        "Las Condes",
        "juan@email.com",
    ]
    
    print("=" * 60)
    print("🤖 PRUEBA DEL CHATBOT CON IA")
    print("=" * 60)
    print()
    
    for i, message in enumerate(messages, 1):
        print(f"👤 Usuario: {message}")
        
        try:
            response = requests.post(
                f"{BASE_URL}/webchat/send",
                json={"user_id": user_id, "text": message},
                timeout=30
            )
            
            if response.status_code == 200:
                bot_reply = response.json().get("reply", "")
                print(f"🤖 Bot: {bot_reply}")
            else:
                print(f"❌ Error: {response.status_code}")
                print(f"   {response.text}")
        
        except requests.exceptions.ConnectionError:
            print("❌ Error: No se pudo conectar al servidor")
            print("   Asegúrate de que el bot esté corriendo en http://localhost:8000")
            print("   Ejecuta: uvicorn app:app --reload")
            return
        
        except Exception as e:
            print(f"❌ Error inesperado: {e}")
            return
        
        print()
        print("-" * 60)
        print()

if __name__ == "__main__":
    print("\n⚠️  Asegúrate de que el bot esté corriendo:")
    print("   uvicorn app:app --reload\n")
    
    input("Presiona ENTER para iniciar la prueba...")
    print()
    
    test_conversation()
    
    print("=" * 60)
    print("✅ Prueba completada")
    print("=" * 60)

