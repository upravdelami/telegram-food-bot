import os
import telebot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
import schedule
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, request, abort
import threading

# Твой токен от BotFather - ИЗМЕНЕНО для Railway
TOKEN = os.environ.get('BOT_TOKEN')
BOT_URL = '/webhook'

# ID чата для сводки
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID')

if not TOKEN or not ADMIN_CHAT_ID:
    raise ValueError("Не установлены BOT_TOKEN или ADMIN_CHAT_ID в переменных окружения")

bot = telebot.TeleBot(TOKEN)

# Доступные позиции с весами (в граммах)
positions = {
    'Ватрушка': 200,
    'Капуста': 130,
    'Яблоко': 120,
    'Картофель': 130,
    'Мак': 190,
    'Плюшка': 150,
    'Чечевица': 140,
    'Повидло': 130,
    'Корица': 150,
    'Сосиск в тесте': 150,
    'Брусника': 130,
    'Вишня': 130,
    'Черная смородина': 130,
    'Творог с зеленью': 130
}

# Хранение заказов: {username: {'позиция': количество}}
orders = {}

# Текущий заказ пользователя (для multi-step: выбор позиции -> количество)
current_orders = {}  # {user_id: {'position': str}}

app = Flask(__name__)


# Webhook эндпоинт
@app.route(BOT_URL, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        abort(403)


@app.route('/')
def index():
    return "Бот работает на Railway! 🚂"


@bot.message_handler(commands=['start'])
def start(message: Message):
    markup = InlineKeyboardMarkup(row_width=2)
    for pos in positions.keys():
        markup.add(InlineKeyboardButton(pos, callback_data=pos))

    bot.reply_to(message, "Привет! Выбери позицию для заказа:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    position = call.data

    if position in positions:
        current_orders[user_id] = {'position': position}
        bot.answer_callback_query(call.id, f"Выбрано: {position}")
        bot.send_message(call.message.chat.id, f"Сколько штук {position} (вес: {positions[position]} гр.)?")
    else:
        bot.answer_callback_query(call.id, "Неверная позиция")


@bot.message_handler(func=lambda message: True)
def handle_quantity(message: Message):
    user_id = message.from_user.id
    if user_id not in current_orders:
        bot.reply_to(message, "Сначала выбери позицию через /start")
        return

    position = current_orders[user_id]['position']
    try:
        quantity = int(message.text.strip())
        if quantity <= 0:
            raise ValueError

        username = message.from_user.username or f"User_{user_id}"
        if username not in orders:
            orders[username] = {}

        if position in orders[username]:
            orders[username][position] += quantity
        else:
            orders[username][position] = quantity

        bot.reply_to(message, f"Добавлено {quantity} шт. {position} для {username}!")
        del current_orders[user_id]  # Сброс после заказа

        # Показать меню снова
        start(message)
    except ValueError:
        bot.reply_to(message, "Введи положительное число!")


# Функция сводки
def send_summary():
    if not orders:
        bot.send_message(ADMIN_CHAT_ID, "Нет заказов за день.")
        return

    all_positions = sorted(positions.keys())
    clients = sorted(orders.keys())

    # Таблица в Markdown
    table = "| Позиция | Вес (гр.) | " + " | ".join(clients) + " |\n"
    table += "| --- | --- | " + " | ".join(["---"] * len(clients)) + " |\n"

    for pos in all_positions:
        row = f"| {pos} | {positions[pos]} |"
        for client in clients:
            qty = orders.get(client, {}).get(pos, 0)
            row += f" {qty} |"
        table += row + "\n"

    bot.send_message(ADMIN_CHAT_ID, "Сводка заказов за день:\n" + table, parse_mode='Markdown')
    orders.clear()


# Планировщик
def scheduler():
    msk_tz = timezone(timedelta(hours=3))
    while True:
        now = datetime.now(msk_tz)
        if now.hour == 20 and now.minute == 0:
            send_summary()
        time.sleep(60)


def setup_webhook():
    """Настройка webhook для Railway"""
    bot.remove_webhook()
    time.sleep(1)

    # ИЗМЕНЕНО: Получаем URL автоматически от Railway
    railway_url = os.environ.get('RAILWAY_STATIC_URL')
    if not railway_url:
        # Если переменной нет, используем стандартный Railway домен
        app_name = os.environ.get('RAILWAY_PROJECT_NAME', 'your-app-name')
        railway_url = f"https://{app_name}.up.railway.app"

    webhook_url = f"{railway_url}{BOT_URL}"
    print(f"Setting webhook to: {webhook_url}")
    bot.set_webhook(webhook_url)


if __name__ == '__main__':
    # Настраиваем webhook при запуске
    setup_webhook()

    # Запускаем планировщик в отдельном потоке
    threading.Thread(target=scheduler, daemon=True).start()

    # Запускаем Flask приложение
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
