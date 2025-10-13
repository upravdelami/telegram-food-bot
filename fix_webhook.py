import requests

BOT_TOKEN = "8198242578:AAGLHoHR1l1lpCj6DzG3reJrlVar4r6A2nA"
RAILWAY_URL = "https://web-production-d7a9d.up.railway.app"

print("Устанавливаю вебхук...")

response = requests.post(
    f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
    json={
        "url": f"{RAILWAY_URL}/webhook",
        "drop_pending_updates": True
    }
)

print("Статус:", response.status_code)
print("Ответ:", response.json())

# Проверим статус
print("\nПроверяем статус вебхука...")
response = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo")
print("Статус вебхука:", response.json())
