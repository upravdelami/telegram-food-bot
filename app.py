import os
import telebot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
import schedule
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, request, abort
import threading
import io
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

TOKEN = os.environ.get('BOT_TOKEN')
BOT_URL = '/webhook'
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID')

if not TOKEN or not ADMIN_CHAT_ID:
    raise ValueError("Не установлены BOT_TOKEN или ADMIN_CHAT_ID")

bot = telebot.TeleBot(TOKEN)

positions = {
    'Ватрушка': 200, 'Капуста': 130, 'Яблоко': 120, 'Картофель': 130,
    'Мак': 190, 'Плюшка': 150, 'Чечевица': 140, 'Повидло': 130,
    'Корица': 150, 'Сосиск в тесте': 150, 'Брусника': 130,
    'Вишня': 130, 'Черная смородина': 130, 'Творог с зеленью': 130
}

# Хранение данных: {user_id: {'address': '', 'location_name': '', 'orders': {}}}
users_data = {}
# Текущий заказ пользователя
current_orders = {}
# Регистрация пользователей: {user_id: 'waiting_address'/'waiting_location'}
registration_steps = {}

app = Flask(__name__)

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

def get_user_data(user_id):
    """Получить данные пользователя"""
    if user_id not in users_data:
        users_data[user_id] = {
            'address': '',
            'location_name': '', 
            'orders': {},
            'registered': False
        }
    return users_data[user_id]

@bot.message_handler(commands=['start'])
def start(message: Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    
    if not user_data['registered']:
        start_registration(message)
    else:
        show_main_menu(message.chat.id, user_data)

def start_registration(message):
    """Начать процесс регистрации"""
    user_id = message.from_user.id
    registration_steps[user_id] = 'waiting_location'
    
    bot.send_message(
        message.chat.id,
        "👋 Добро пожаловать! Давайте зарегистрируем вас.\n\n"
        "📝 **Как называется ваша точка/магазин?**\n"
        "Например: 'Магазин у дома', 'Офис на Ленина', 'Кафе Уют'"
    )

@bot.message_handler(commands=['admin'])
def admin_panel(message: Message):
    """Панель администратора"""
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ Доступ запрещен")
        return
    
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton('📊 Excel Сводка', callback_data='admin_excel'),
        InlineKeyboardButton('📋 Текстовая сводка', callback_data='admin_summary'),
        InlineKeyboardButton('👥 Список клиентов', callback_data='admin_clients'),
        InlineKeyboardButton('🔄 Обнулить заказы', callback_data='admin_clear'),
    ]
    markup.add(*buttons[:2])
    markup.add(*buttons[2:])
    
    bot.send_message(message.chat.id, "⚙️ **Панель администратора**", reply_markup=markup)

@bot.message_handler(func=lambda message: True)
def handle_messages(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Обработка регистрации
    if user_id in registration_steps:
        handle_registration(message)
        return
    
    # Обработка количества для заказов
    if user_id in current_orders:
        handle_quantity(message)
        return
    
    bot.reply_to(message, "Используйте меню для навигации")

def handle_registration(message: Message):
    """Обработка шагов регистрации"""
    user_id = message.from_user.id
    step = registration_steps.get(user_id)
    user_data = get_user_data(user_id)
    
    if step == 'waiting_location':
        user_data['location_name'] = message.text.strip()
        registration_steps[user_id] = 'waiting_address'
        
        bot.send_message(
            message.chat.id,
            "📍 **Теперь укажите адрес доставки:**\n"
            "Например: 'ул. Ленина, 15', 'ТЦ Центральный, 2 этаж'"
        )
        
    elif step == 'waiting_address':
        user_data['address'] = message.text.strip()
        user_data['registered'] = True
        del registration_steps[user_id]
        
        bot.send_message(
            message.chat.id,
            f"✅ **Регистрация завершена!**\n\n"
            f"🏪 Точка: {user_data['location_name']}\n"
            f"📍 Адрес: {user_data['address']}\n\n"
            f"Теперь вы можете делать заказы!",
            parse_mode='Markdown'
        )
        
        show_main_menu(message.chat.id, user_data)

def show_main_menu(chat_id, user_data):
    """Показать главное меню"""
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton('➕ Добавить заказ', callback_data='add_order'),
        InlineKeyboardButton('📋 Мой заказ', callback_data='my_order'),
        InlineKeyboardButton('✏️ Изменить заказ', callback_data='edit_order'),
        InlineKeyboardButton('🏪 Мои данные', callback_data='my_data'),
    ]
    markup.add(*buttons[:2])
    markup.add(*buttons[2:])
    
    welcome_text = f"🏪 {user_data['location_name']}\n📍 {user_data['address']}\n\nВыберите действие:"
    bot.send_message(chat_id, welcome_text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    user_data = get_user_data(user_id)
    
    if call.data == 'add_order':
        show_positions_menu(chat_id)
    elif call.data == 'my_order':
        show_user_order(call, user_data)
    elif call.data == 'edit_order':
        show_edit_menu(call, user_data)
    elif call.data == 'my_data':
        show_user_data(call, user_data)
    elif call.data == 'admin_excel':
        send_excel_summary(call)
    elif call.data == 'admin_summary':
        send_text_summary(call)
    elif call.data == 'admin_clients':
        show_clients_list(call)
    elif call.data == 'admin_clear':
        clear_all_orders(call)
    elif call.data in positions:
        current_orders[user_id] = {'position': call.data}
        bot.answer_callback_query(call.id, f"Выбрано: {call.data}")
        bot.send_message(chat_id, f"Сколько штук {call.data}?")
    elif call.data.startswith('edit_'):
        position = call.data[5:]
        current_orders[user_id] = {'position': position, 'editing': True}
        bot.answer_callback_query(call.id, f"Изменяем: {position}")
        bot.send_message(chat_id, f"Введите новое количество для {position}:")

def show_positions_menu(chat_id):
    markup = InlineKeyboardMarkup(row_width=2)
    for pos in positions.keys():
        markup.add(InlineKeyboardButton(pos, callback_data=pos))
    markup.add(InlineKeyboardButton('↩️ Назад', callback_data='back_to_main'))
    
    bot.send_message(chat_id, "Выберите позицию для заказа:", reply_markup=markup)

def show_user_order(call, user_data):
    user_orders = user_data['orders']
    
    if not user_orders:
        bot.answer_callback_query(call.id, "У вас нет заказов")
        bot.send_message(call.message.chat.id, "📭 У вас еще нет заказов на сегодня.")
        return
    
    total_items = sum(user_orders.values())
    
    order_text = f"🏪 **{user_data['location_name']}**\n"
    order_text += f"📍 {user_data['address']}\n\n"
    order_text += "📋 **Ваш заказ на сегодня:**\n\n"
    
    for pos, qty in user_orders.items():
        order_text += f"• {pos}: {qty} шт.\n"
    
    order_text += f"\n📊 **Итого:** {total_items} шт."
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, order_text, parse_mode='Markdown')

def show_user_data(call, user_data):
    user_orders = user_data['orders']
    total_items = sum(user_orders.values()) if user_orders else 0
    
    data_text = "👤 **Ваши данные:**\n\n"
    data_text += f"🏪 **Точка:** {user_data['location_name']}\n"
    data_text += f"📍 **Адрес:** {user_data['address']}\n"
    data_text += f"📦 **Заказов сегодня:** {total_items} шт.\n\n"
    data_text += "_Чтобы изменить данные, перезапустите бота /start_"
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, data_text, parse_mode='Markdown')

def show_edit_menu(call, user_data):
    user_orders = user_data['orders']
    
    if not user_orders:
        bot.answer_callback_query(call.id, "Нет заказов для редактирования")
        return
    
    markup = InlineKeyboardMarkup(row_width=2)
    
    for pos in user_orders.keys():
        markup.add(InlineKeyboardButton(f"✏️ {pos}", callback_data=f'edit_{pos}'))
    
    markup.add(InlineKeyboardButton('➕ Добавить еще', callback_data='add_order'))
    markup.add(InlineKeyboardButton('🗑️ Очистить все', callback_data='clear_order'))
    markup.add(InlineKeyboardButton('↩️ Назад', callback_data='back_to_main'))
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Выберите позицию для изменения:", reply_markup=markup)

def handle_quantity(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_data = get_user_data(user_id)
    
    position_data = current_orders[user_id]
    position = position_data['position']
    is_editing = position_data.get('editing', False)
    
    try:
        quantity = int(message.text.strip())
        if quantity < 0:
            raise ValueError
        
        if quantity == 0:
            if position in user_data['orders']:
                del user_data['orders'][position]
            action_text = f"❌ Удалено: {position}"
        else:
            user_data['orders'][position] = quantity
            action_text = f"{'✏️ Обновлено' if is_editing else '✅ Добавлено'} {quantity} шт. {position}"
        
        bot.reply_to(message, f"{action_text} для {user_data['location_name']}!")
        del current_orders[user_id]
        
        show_main_menu(chat_id, user_data)
        
    except ValueError:
        bot.reply_to(message, "Введите целое число (0 для удаления позиции):")

def generate_excel_file():
    """Генерация Excel файла со сводкой"""
    active_users = {uid: data for uid, data in users_data.items() if data.get('orders')}
    
    if not active_users:
        return None
    
    # Собираем данные клиентов
    clients_data = []
    for user_id, user_data in active_users.items():
        if user_data.get('orders'):
            clients_data.append({
                'name': user_data['location_name'],
                'address': user_data['address'],
                'orders': user_data['orders']
            })
    
    # Сортируем по названию точки
    clients_data.sort(key=lambda x: x['name'])
    
    # Создаем Excel книгу
    wb = Workbook()
    ws = wb.active
    ws.title = "Сводка заказов"
    
    # Стили
    header_font = Font(bold=True, size=14)
    title_font = Font(bold=True, size=12)
    bold_font = Font(bold=True)
    center_align = Alignment(horizontal='center', vertical='center')
    border = Border(left=Side(style='thin'), right=Side(style='thin'), 
                   top=Side(style='thin'), bottom=Side(style='thin'))
    
    # Заголовок
    ws.merge_cells('A1:H1')
    ws['A1'] = f"Сводка заказов от {datetime.now().strftime('%d.%m.%Y')}"
    ws['A1'].font = header_font
    ws['A1'].alignment = center_align
    
    # Пустая строка
    ws.append([])
    
    # Заголовки таблицы
    headers = ['№', 'Точка', 'Адрес'] + list(positions.keys()) + ['ИТОГО']
    ws.append(headers)
    
    # Применяем стили к заголовкам
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=3, column=col)
        cell.font = title_font
        cell.alignment = center_align
        cell.border = border
    
    # Данные по клиентам
    row_num = 4
    for i, client in enumerate(clients_data, 1):
        row = [i, client['name'], client['address']]
        total = 0
        
        for pos in positions.keys():
            qty = client['orders'].get(pos, 0)
            row.append(qty)
            total += qty
        
        row.append(total)
        ws.append(row)
        
        # Применяем стили к строке
        for col in range(1, len(headers) + 1):
            cell = ws.cell(row=row_num, column=col)
            cell.border = border
            if col in [1, len(headers)]:  # № и ИТОГО - жирный
                cell.font = bold_font
    
    # Итоговая строка
    ws.append([])
    total_row = ['ВСЕГО', '', '']
    
    for pos in positions.keys():
        pos_total = sum(client['orders'].get(pos, 0) for client in clients_data)
        total_row.append(pos_total)
    
    total_row.append(sum(total_row[3:]))
    ws.append(total_row)
    
    # Стили для итоговой строки
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=row_num + 2, column=col)
        cell.font = bold_font
        cell.border = border
        if col >= 4:  # Числовые колонки
            cell.alignment = center_align
    
    # Настраиваем ширину колонок
    column_widths = {
        'A': 5,    # №
        'B': 25,   # Точка
        'C': 30,   # Адрес
    }
    
    # Ширина для позиций
    for i, pos in enumerate(positions.keys(), 4):
        col_letter = get_column_letter(i)
        column_widths[col_letter] = 8
    
    # Ширина для ИТОГО
    column_widths[get_column_letter(len(headers))] = 10
    
    for col, width in column_widths.items():
        ws.column_dimensions[col].width = width
    
    # Сохраняем в память
    excel_buffer = io.BytesIO()
    wb.save(excel_buffer)
    excel_buffer.seek(0)
    
    return excel_buffer

def send_excel_summary(call=None):
    """Отправка Excel сводки"""
    excel_buffer = generate_excel_file()
    
    if not excel_buffer:
        if call:
            bot.answer_callback_query(call.id, "Нет заказов")
            bot.send_message(call.message.chat.id, "📭 Нет заказов за сегодня.")
        else:
            bot.send_message(ADMIN_CHAT_ID, "📭 Нет заказов за сегодня.")
        return
    
    # Отправляем Excel файл
    filename = f"заказы_{datetime.now().strftime('%d.%m.%Y')}.xlsx"
    
    if call:
        bot.answer_callback_query(call.id)
        bot.send_document(
            call.message.chat.id,
            document=excel_buffer,
            visible_file_name=filename,
            caption=f"📊 Сводка заказов от {datetime.now().strftime('%d.%m.%Y')}\n\nФайл готов для открытия в Excel"
        )
    else:
        bot.send_document(
            ADMIN_CHAT_ID,
            document=excel_buffer,
            visible_file_name=filename,
            caption=f"📊 Автоматическая сводка заказов от {datetime.now().strftime('%d.%m.%Y')}"
        )
        
        # Автоматически очищаем заказы после отправки сводки
        for user_data in users_data.values():
            user_data['orders'] = {}

def send_text_summary(call):
    """Текстовая сводка (для быстрого просмотра)"""
    active_users = {uid: data for uid, data in users_data.items() if data.get('orders')}
    
    if not active_users:
        bot.answer_callback_query(call.id, "Нет заказов")
        bot.send_message(call.message.chat.id, "📭 Нет заказов за сегодня.")
        return
    
    clients_data = []
    for user_id, user_data in active_users.items():
        if user_data.get('orders'):
            clients_data.append({
                'name': user_data['location_name'],
                'address': user_data['address'],
                'orders': user_data['orders']
            })
    
    clients_data.sort(key=lambda x: x['name'])
    
    summary_text = f"📊 **Сводка заказов от {datetime.now().strftime('%d.%m.%Y')}**\n"
    summary_text += f"👥 Клиентов: {len(clients_data)}\n\n"
    
    for client in clients_data:
        total_items = sum(client['orders'].values())
        order_details = []
        
        for pos, qty in client['orders'].items():
            if qty > 0:
                order_details.append(f"{pos}:{qty}")
        
        details_str = ", ".join(order_details)
        summary_text += f"• **{client['name']}** - {total_items} шт.\n"
        summary_text += f"  {details_str}\n"
        summary_text += f"  📍 {client['address']}\n\n"
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, summary_text, parse_mode='Markdown')

def show_clients_list(call):
    """Показать список всех клиентов"""
    registered_users = [data for data in users_data.values() if data['registered']]
    
    if not registered_users:
        bot.answer_callback_query(call.id, "Нет зарегистрированных клиентов")
        bot.send_message(call.message.chat.id, "👥 Нет зарегистрированных клиентов.")
        return
    
    clients_text = "👥 **ЗАРЕГИСТРИРОВАННЫЕ КЛИЕНТЫ**\n\n"
    
    for i, user_data in enumerate(registered_users, 1):
        order_count = sum(user_data['orders'].values())
        status = "✅ Есть заказы" if order_count > 0 else "⏳ Нет заказов"
        clients_text += f"{i}. **{user_data['location_name']}**\n"
        clients_text += f"   📍 {user_data['address']}\n"
        clients_text += f"   📦 {status} ({order_count} шт.)\n\n"
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, clients_text, parse_mode='Markdown')

def clear_all_orders(call):
    """Очистить все заказы"""
    for user_data in users_data.values():
        user_data['orders'] = {}
    
    bot.answer_callback_query(call.id, "Все заказы очищены")
    bot.send_message(call.message.chat.id, "🗑️ Все заказы очищены!")

# Планировщик для автоматической сводки
def scheduler():
    msk_tz = timezone(timedelta(hours=3))
    while True:
        now = datetime.now(msk_tz)
        if now.hour == 20 and now.minute == 0:
            send_excel_summary()
        time.sleep(60)

def setup_webhook():
    bot.remove_webhook()
    time.sleep(1)
    railway_url = os.environ.get('RAILWAY_STATIC_URL')
    if not railway_url:
        app_name = os.environ.get('RAILWAY_PROJECT_NAME', 'your-app-name')
        railway_url = f"https://{app_name}.up.railway.app"
    webhook_url = f"{railway_url}{BOT_URL}"
    bot.set_webhook(webhook_url)

if __name__ == '__main__':
    setup_webhook()
    threading.Thread(target=scheduler, daemon=True).start()
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
