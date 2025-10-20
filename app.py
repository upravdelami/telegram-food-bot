import os
import telebot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, request, abort
import threading
import io
import json
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

# Файлы для хранения данных (теперь в persistent volume)
DATA_DIR = '/data'
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)  # Создаем директорию, если нет
USERS_DB_FILE = os.path.join(DATA_DIR, 'users_data.json')
ORDERS_DB_FILE = os.path.join(DATA_DIR, 'orders_history.json')

# Временные данные (в оперативной памяти)
current_orders = {}
registration_steps = {}

app = Flask(__name__)

def load_users_data():
    """Загрузка базы клиентов из файла"""
    try:
        if os.path.exists(USERS_DB_FILE):
            with open(USERS_DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Ошибка загрузки users_data: {e}")
    return {}

def save_users_data():
    """Сохранение базы клиентов в файл"""
    try:
        with open(USERS_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(users_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения users_data: {e}")

def load_orders_history():
    """Загрузка истории заказов из файла"""
    try:
        if os.path.exists(ORDERS_DB_FILE):
            with open(ORDERS_DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Ошибка загрузки orders_history: {e}")
    return {}

def save_orders_history():
    """Сохранение истории заказов в файл"""
    try:
        with open(ORDERS_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(orders_history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения orders_history: {e}")

def add_order_to_history(user_data, date_str):
    """Добавление заказа в историю"""
    try:
        if date_str not in orders_history:
            orders_history[date_str] = []
        
        order_entry = {
            'user_id': user_data.get('user_id'),
            'location_name': user_data['location_name'],
            'address': user_data['address'],
            'orders': user_data['orders'].copy(),
            'total_items': sum(user_data['orders'].values()),
            'timestamp': datetime.now().strftime('%H:%M')
        }
        
        orders_history[date_str].append(order_entry)
        save_orders_history()
    except Exception as e:
        print(f"Ошибка добавления в историю: {e}")

# Загрузка данных при запуске
users_data = load_users_data()
orders_history = load_orders_history()

print(f"Загружено пользователей: {len(users_data)}")
print(f"Загружено дней в истории: {len(orders_history)}")

@app.route(BOT_URL, methods=['POST'])
def webhook():
    print(f"ПОЛУЧЕН POST на {BOT_URL}")
    try:
        if request.headers.get('content-type') == 'application/json':
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            print(f"ОБНОВЛЕНИЕ: {update}")  # ← ВИДИМ, ЧТО ПРИШЛО
            bot.process_new_updates([update])
            return '', 200
        else:
            print("ОТКЛОНЁН: не JSON")
            abort(403)
    except Exception as e:
        print(f"ОШИБКА В WEBHOOK: {e}")
        return 'Error', 500

@app.route('/')
def index():
    return "Бот работает на Railway!"

def get_user_data(user_id):
    """Получить данные пользователя"""
    user_id_str = str(user_id)
    if user_id_str not in users_data:
        users_data[user_id_str] = {
            'user_id': user_id_str,
            'address': '',
            'location_name': '', 
            'orders': {},
            'registered': False,
            'registration_date': datetime.now().strftime('%d.%m.%Y %H:%M')
        }
        save_users_data()  # Сохраняем нового пользователя
    return users_data[user_id_str]

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
        "Добро пожаловать! Давайте зарегистрируем вас.\n\n"
        "**Как называется ваша точка/магазин?**\n"
        "Например: 'Магазин у дома', 'Офис на Ленина', 'Кафе Уют'"
    )

@bot.message_handler(commands=['admin'])
def admin_panel(message: Message):
    """Панель администратора"""
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "Доступ запрещен")
        return
    
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton('Excel Сводка', callback_data='admin_excel'),
        InlineKeyboardButton('Текстовая сводка', callback_data='admin_summary'),
        InlineKeyboardButton('База клиентов', callback_data='admin_clients'),
        InlineKeyboardButton('Удалить клиентов', callback_data='admin_delete_clients'),
        InlineKeyboardButton('История заказов', callback_data='admin_history'),
        InlineKeyboardButton('Обнулить заказы', callback_data='admin_clear'),
        InlineKeyboardButton('Экспорт данных', callback_data='admin_export'),
    ]
    markup.add(*buttons)
    
    stats_text = f"**Статистика:**\nКлиентов: {len(users_data)}\nДней в истории: {len(orders_history)}"
    
    bot.send_message(message.chat.id, f"**Панель администратора**\n\n{stats_text}", reply_markup=markup)

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
            "**Теперь укажите адрес доставки:**\n"
            "Например: 'ул. Ленина, 15', 'ТЦ Центральный, 2 этаж'"
        )
        
    elif step == 'waiting_address':
        user_data['address'] = message.text.strip()
        user_data['registered'] = True
        user_data['registration_date'] = datetime.now().strftime('%d.%m.%Y %H:%M')
        del registration_steps[user_id]
        
        save_users_data()  # Сохраняем данные после регистрации
        
        bot.send_message(
            message.chat.id,
            f"**Регистрация завершена!**\n\n"
            f"Точка: {user_data['location_name']}\n"
            f"Адрес: {user_data['address']}\n\n"
            f"Теперь вы можете делать заказы!"
        )
        
        show_main_menu(message.chat.id, user_data)

def show_main_menu(chat_id, user_data):
    """Показать главное меню"""
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton('Добавить заказ', callback_data='add_order'),
        InlineKeyboardButton('Мой заказ', callback_data='my_order'),
        InlineKeyboardButton('Изменить заказ', callback_data='edit_order'),
        InlineKeyboardButton('Мои данные', callback_data='my_data'),
    ]
    markup.add(*buttons)
    
    welcome_text = f"{user_data['location_name']}\n{user_data['address']}\n\nВыберите действие:"
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
        show_clients_database(call)
    elif call.data == 'admin_delete_clients':
        show_delete_clients_menu(call)
    elif call.data == 'admin_history':
        show_orders_history(call)
    elif call.data == 'admin_clear':
        clear_all_orders(call)
    elif call.data == 'admin_export':
        export_all_data(call)
    elif call.data in positions:
        current_orders[user_id] = {'position': call.data}
        bot.answer_callback_query(call.id, f"Выбрано: {call.data}")
        bot.send_message(chat_id, f"Сколько штук {call.data}?")
    elif call.data.startswith('edit_'):
        position = call.data[5:]
        current_orders[user_id] = {'position': position, 'editing': True}
        bot.answer_callback_query(call.id, f"Изменяем: {position}")
        bot.send_message(chat_id, f"Введите новое количество для {position}:")
    elif call.data == 'back_to_main':
        bot.answer_callback_query(call.id, "Возврат в меню")
        bot.delete_message(chat_id, call.message.message_id)
        show_main_menu(chat_id, user_data)
    elif call.data == 'clear_order':
        user_data['orders'] = {}
        save_users_data()
        bot.answer_callback_query(call.id, "Заказ очищен")
        bot.delete_message(chat_id, call.message.message_id)
        show_main_menu(chat_id, user_data)
    elif call.data.startswith('delete_user_'):
        delete_user(call)
    elif call.data == 'admin_stats':
        bot.answer_callback_query(call.id, "Детальная статистика")
        bot.send_message(chat_id, "Детальная статистика (в разработке): \n- Общее заказов: ...\n- Топ позиция: ...")
    elif call.data == 'back_to_admin':
        bot.answer_callback_query(call.id)
        bot.delete_message(chat_id, call.message.message_id)
        admin_panel(call.message)

def show_positions_menu(chat_id):
    markup = InlineKeyboardMarkup(row_width=2)
    for pos in positions.keys():
        markup.add(InlineKeyboardButton(pos, callback_data=pos))
    markup.add(InlineKeyboardButton('Назад', callback_data='back_to_main'))
    
    bot.send_message(chat_id, "Выберите позицию для заказа:", reply_markup=markup)

def show_user_order(call, user_data):
    user_orders = user_data['orders']
    
    if not user_orders:
        bot.answer_callback_query(call.id, "У вас нет заказов")
        bot.send_message(call.message.chat.id, "У вас еще нет заказов на сегодня.")
        return
    
    total_items = sum(user_orders.values())
    
    order_text = f"**{user_data['location_name']}**\n"
    order_text += f"{user_data['address']}\n\n"
    order_text += "**Ваш заказ на сегодня:**\n\n"
    
    for pos, qty in user_orders.items():
        order_text += f"• {pos}: {qty} шт.\n"
    
    order_text += f"\n**Итого:** {total_items} шт."
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, order_text)

def show_user_data(call, user_data):
    user_orders = user_data['orders']
    total_items = sum(user_orders.values()) if user_orders else 0
    
    data_text = "**Ваши данные:**\n\n"
    data_text += f"**Точка:** {user_data['location_name']}\n"
    data_text += f"**Адрес:** {user_data['address']}\n"
    data_text += f"**Дата регистрации:** {user_data.get('registration_date', 'неизвестно')}\n"
    data_text += f"**Заказов сегодня:** {total_items} шт.\n\n"
    data_text += "_Чтобы изменить данные, перезапустите бота /start_"
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, data_text)

def show_edit_menu(call, user_data):
    user_orders = user_data['orders']
    
    if not user_orders:
        bot.answer_callback_query(call.id, "Нет заказов для редактирования")
        return
    
    markup = InlineKeyboardMarkup(row_width=2)
    
    for pos in user_orders.keys():
        markup.add(InlineKeyboardButton(f"{pos}", callback_data=f'edit_{pos}'))
    
    markup.add(InlineKeyboardButton('Добавить еще', callback_data='add_order'))
    markup.add(InlineKeyboardButton('Очистить все', callback_data='clear_order'))
    markup.add(InlineKeyboardButton('Назад', callback_data='back_to_main'))
    
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
            action_text = f"Удалено: {position}"
        else:
            user_data['orders'][position] = quantity
            action_text = f"{'Обновлено' if is_editing else 'Добавлено'} {quantity} шт. {position}"
        
        save_users_data()  # Сохраняем после изменения заказа
        
        bot.reply_to(message, f"{action_text} для {user_data['location_name']}!")
        del current_orders[user_id]
        
        show_main_menu(chat_id, user_data)
        
    except ValueError:
        bot.reply_to(message, "Введите целое число (0 для удаления позиции):")

def generate_excel_file():
    """Генерация Excel файла со сводкой"""
    active_users = [data for data in users_data.values() if data.get('orders') and data.get('registered')]
    
    if not active_users:
        return None
    
    # Сортируем по названию точки
    active_users.sort(key=lambda x: x['location_name'])
    
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
    num_positions = len(positions)
    header_end_col = get_column_letter(3 + num_positions + 1)  # №, Точка, Адрес, positions, ИТОГО
    ws.merge_cells(f'A1:{header_end_col}1')
    ws['A1'] = f"Сводка заказов от {datetime.now().strftime('%d.%m.%Y')}"
    ws['A1'].font = header_font
    ws['A1'].alignment = center_align
    
    # Пустая строка
    ws.append([])
    
    # Заголовки таблицы
    headers = ['№', 'Точка', 'Адрес'] + list(positions.keys()) + ['ИТОГО']
    ws.append(headers)
    
    # Применяем стили к заголовкам
    header_row = 3
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=header_row, column=col)
        cell.font = title_font
        cell.alignment = center_align
        cell.border = border
    
    # Данные по клиентам
    row_num = 4
    for i, user_data in enumerate(active_users, 1):
        row = [i, user_data['location_name'], user_data['address']]
        total = 0
        
        for pos in positions.keys():
            qty = user_data['orders'].get(pos, 0)
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
        row_num += 1
    
    # Итоговая строка
    ws.append([])
    row_num += 1
    total_row = ['ВСЕГО', '', '']
    
    for pos_idx in range(len(positions)):
        col_idx = 4 + pos_idx
        pos_total = sum(ws.cell(row=r, column=col_idx).value or 0 for r in range(4, row_num))
        total_row.append(pos_total)
    
    grand_total = sum(total_row[3:])
    total_row.append(grand_total)
    ws.append(total_row)
    
    # Стили для итоговой строки
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=row_num + 1, column=col)
        cell.font = bold_font
        cell.border = border
        if col >= 4:
            cell.alignment = center_align
    
    # Настраиваем ширину колонок
    column_widths = {
        'A': 5,    # №
        'B': 25,   # Точка
        'C': 30,   # Адрес
    }
    
    for i, pos in enumerate(positions.keys(), 4):
        col_letter = get_column_letter(i)
        column_widths[col_letter] = 8
    
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
    try:
        excel_buffer = generate_excel_file()
        
        if not excel_buffer:
            if call:
                bot.answer_callback_query(call.id, "Нет заказов")
                bot.send_message(call.message.chat.id, "Нет заказов за сегодня.")
            else:
                bot.send_message(ADMIN_CHAT_ID, "Нет заказов за сегодня.")
            return
        
        filename = f"заказы_{datetime.now().strftime('%d.%m.%Y')}.xlsx"
        excel_buffer.name = filename  # Устанавливаем атрибут name для InputFile
        
        input_file = telebot.types.InputFile(excel_buffer)
        
        if call:
            bot.answer_callback_query(call.id)
            bot.send_document(
                call.message.chat.id,
                document=input_file,
                caption=f"Сводка заказов от {datetime.now().strftime('%d.%m.%Y')}\n\nФайл готов для открытия в Excel"
            )
        else:
            current_date = datetime.now().strftime('%Y-%m-%d')
            for user_data in users_data.values():
                if user_data.get('orders') and user_data.get('registered'):
                    add_order_to_history(user_data, current_date)
            
            bot.send_document(
                ADMIN_CHAT_ID,
                document=input_file,
                caption=f"Автоматическая сводка заказов от {datetime.now().strftime('%d.%m.%Y')}"
            )
            
    except Exception as e:
        print(f"Ошибка при отправке сводки: {e}")
        if call:
            bot.send_message(call.message.chat.id, f"Ошибка при генерации Excel: {e}")
        else:
            bot.send_message(ADMIN_CHAT_ID, f"Ошибка при отправке сводки: {e}")

def send_text_summary(call):
    """Текстовая сводка"""
    active_users = [data for data in users_data.values() if data.get('orders') and data.get('registered')]
    
    if not active_users:
        bot.answer_callback_query(call.id, "Нет заказов")
        bot.send_message(call.message.chat.id, "Нет заказов за сегодня.")
        return
    
    active_users.sort(key=lambda x: x['location_name'])
    
    summary_text = f"**Сводка заказов от {datetime.now().strftime('%d.%m.%Y')}**\n"
    summary_text += f"Клиентов: {len(active_users)}\n\n"
    
    for user_data in active_users:
        total_items = sum(user_data['orders'].values())
        order_details = [f"{pos}:{qty}" for pos, qty in user_data['orders'].items() if qty > 0]
        
        details_str = ", ".join(order_details)
        summary_text += f"• **{user_data['location_name']}** - {total_items} шт.\n"
        summary_text += f"  {details_str}\n"
        summary_text += f"  {user_data['address']}\n\n"
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, summary_text)

def show_clients_database(call):
    """Показать базу клиентов"""
    registered_users = [data for data in users_data.values() if data['registered']]
    
    if not registered_users:
        bot.answer_callback_query(call.id, "База клиентов пуста")
        bot.send_message(call.message.chat.id, "База клиентов пуста.")
        return
    
    clients_text = f"**БАЗА КЛИЕНТОВ**\nВсего: {len(registered_users)}\n\n"
    
    for i, user_data in enumerate(registered_users, 1):
        order_count = sum(user_data['orders'].values())
        last_order = "Сегодня" if order_count > 0 else "Нет заказов"
        clients_text += f"{i}. **{user_data['location_name']}**\n"
        clients_text += f"   {user_data['address']}\n"
        clients_text += f"   Регистрация: {user_data.get('registration_date', 'неизвестно')}\n"
        clients_text += f"   {last_order} ({order_count} шт.)\n\n"
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, clients_text)

def show_delete_clients_menu(call):
    if str(call.message.chat.id) != ADMIN_CHAT_ID:
        bot.answer_callback_query(call.id, "Доступ запрещен")
        return
    
    registered_users = [data for data in users_data.values() if data['registered']]
    
    if not registered_users:
        bot.answer_callback_query(call.id, "Нет клиентов для удаления")
        bot.send_message(call.message.chat.id, "Нет клиентов для удаления.")
        return
    
    markup = InlineKeyboardMarkup(row_width=1)
    for user_data in registered_users:
        button_text = f"Удалить {user_data['location_name']} (ID: {user_data['user_id']})"
        markup.add(InlineKeyboardButton(button_text, callback_data=f"delete_user_{user_data['user_id']}"))
    
    markup.add(InlineKeyboardButton('Назад в админ', callback_data='back_to_admin'))
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Выберите клиента для удаления:", reply_markup=markup)

def delete_user(call):
    if str(call.message.chat.id) != ADMIN_CHAT_ID:
        bot.answer_callback_query(call.id, "Доступ запрещен")
        return
    
    user_id_str = call.data.split('_')[-1]
    if user_id_str in users_data:
        location_name = users_data[user_id_str]['location_name']
        del users_data[user_id_str]
        save_users_data()
        bot.answer_callback_query(call.id, f"Клиент {location_name} удален")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, f"Клиент {location_name} удален из базы (заказы обнулены).")
    else:
        bot.answer_callback_query(call.id, "Клиент не найден")

def show_orders_history(call):
    """Показать историю заказов"""
    if not orders_history:
        bot.answer_callback_query(call.id, "История заказов пуста")
        bot.send_message(call.message.chat.id, "История заказов пуста.")
        return
    
    history_text = f"**ИСТОРИЯ ЗАКАЗОВ**\nДней в истории: {len(orders_history)}\n\n"
    
    sorted_dates = sorted(orders_history.keys(), reverse=True)[:7]
    
    for date_str in sorted_dates:
        date_orders = orders_history[date_str]
        total_orders = len(date_orders)
        total_items = sum(order['total_items'] for order in date_orders)
        
        history_text += f"**{datetime.strptime(date_str, '%Y-%m-%d').strftime('%d.%m.%Y')}**\n"
        history_text += f"   Клиентов: {total_orders}\n"
        history_text += f"   Товаров: {total_items} шт.\n\n"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton('Детальная статистика', callback_data='admin_stats'))
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, history_text, reply_markup=markup)

def clear_all_orders(call):
    """Очистить все заказы"""
    cleared_count = 0
    for user_data in users_data.values():
        if user_data['orders']:
            user_data['orders'] = {}
            cleared_count += 1
    
    save_users_data()
    
    bot.answer_callback_query(call.id, f"Очищено {cleared_count} заказов")
    bot.send_message(call.message.chat.id, f"Очищены заказы у {cleared_count} клиентов!")

def clear_all_orders_auto():
    cleared_count = 0
    for user_data in users_data.values():
        if user_data['orders']:
            user_data['orders'] = {}
            cleared_count += 1
    
    if cleared_count > 0:
        save_users_data()
    
    print(f"Автоматически очищены заказы у {cleared_count} пользователей")
    return cleared_count

def export_all_data(call):
    """Экспорт всех данных в JSON"""
    try:
        export_data = {
            'users': users_data,
            'orders_history': orders_history,
            'export_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        export_json = json.dumps(export_data, ensure_ascii=False, indent=2).encode('utf-8')
        json_buffer = io.BytesIO(export_json)
        filename = f"backup_data_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        json_buffer.name = filename  # Устанавливаем name для InputFile
        
        input_file = telebot.types.InputFile(json_buffer)
        
        bot.answer_callback_query(call.id)
        bot.send_document(
            call.message.chat.id,
            document=input_file,
            caption="Полный бэкап данных системы"
        )
    except Exception as e:
        bot.answer_callback_query(call.id, "Ошибка экспорта")
        bot.send_message(call.message.chat.id, f"Ошибка при экспорте данных: {e}")

# глобальные параметры
target_send_minute = None
target_clear_minute = None
last_triggered_minute = None

STATE_FILE = "scheduler_state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"target_send_minute": None, "target_clear_minute": None, "last_triggered_minute": None}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)

def check_scheduled_tasks():
    state = load_state()
    msk_tz = timezone(timedelta(hours=3))
    now = datetime.now(msk_tz)
    current_time = now.strftime('%H:%M:%S')

    print(f"--- ПРОВЕРКА: {current_time} ---")

    # первый запуск
    if state["target_send_minute"] is None and state["target_clear_minute"] is None:
        state["target_send_minute"] = (now.minute + 1) % 60
        state["target_clear_minute"] = (now.minute + 2) % 60
        save_state(state)
        print(f"🎯 Первичная установка: сводка в {state['target_send_minute']}, очистка в {state['target_clear_minute']}")

    print(f"Ожидаем: сводка в {state['target_send_minute']:02d}, очистка в {state['target_clear_minute']:02d}")

    # не повторяем в ту же минуту
    if state["last_triggered_minute"] == now.minute:
        print("⏸ Уже выполнялось в эту минуту, ждём следующую...")
        return

    # === ОТПРАВКА СВОДКИ ===
    if now.minute == state["target_send_minute"]:
        print("*** ТРИГГЕР: ОТПРАВКА СВОДКИ ***")
        try:
            send_excel_summary()
            print("✅ Сводка отправлена!")
        except Exception as e:
            print(f"❌ Ошибка сводки: {e}")
        finally:
            state["last_triggered_minute"] = now.minute
            state["target_send_minute"] = (state["target_send_minute"] + 60) % 60
            save_state(state)

    # === ОЧИСТКА ЗАКАЗОВ ===
    elif now.minute == state["target_clear_minute"]:
        print("*** ТРИГГЕР: ОЧИСТКА ЗАКАЗОВ ***")
        try:
            cleared_count = clear_all_orders_auto()
            bot.send_message(ADMIN_CHAT_ID, f"✅ Заказы обнулены. Очищено: {cleared_count}")
            print(f"Очищено: {cleared_count}")
        except Exception as e:
            print(f"❌ Ошибка очистки: {e}")
        finally:
            state["last_triggered_minute"] = now.minute
            state["target_clear_minute"] = (state["target_clear_minute"] + 60) % 60
            save_state(state)
    else:
        print(f"Ждём... сейчас {now.minute}, нужно {state['target_send_minute']} или {state['target_clear_minute']}")



def scheduler():
    print("🚀 ПЛАННИРОВЩИК ЗАПУЩЕН! Проверяем каждую секунду...")
    
    while True:
        try:
            check_scheduled_tasks()
            time.sleep(10)  # ← Уменьшил до 10 сек для быстрой отладки
        except Exception as e:
            print(f"❌ КРИТИЧЕСКАЯ ОШИБКА ПЛАННИРОВЩИКА: {e}")
            time.sleep(10)

def setup_webhook():
    print("Удаляю старый webhook...")
    bot.remove_webhook()
    time.sleep(2)

    # Полный URL
    webhook_url = "https://web-production-d7a9d.up.railway.app/webhook"
    print(f"Устанавливаю webhook: {webhook_url}")

    result = bot.set_webhook(url=webhook_url)
    if result:
        print("WEBHOOK УСПЕШНО УСТАНОВЛЕН!")
    else:
        print("ОШИБКА: Webhook НЕ установлен!")
        print("Проверь: токен, URL, доступность /webhook")
     

import os
import telebot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, request, abort
import threading
import io
import json
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

# Файлы для хранения данных (теперь в persistent volume)
DATA_DIR = '/data'
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)  # Создаем директорию, если нет
USERS_DB_FILE = os.path.join(DATA_DIR, 'users_data.json')
ORDERS_DB_FILE = os.path.join(DATA_DIR, 'orders_history.json')

# Временные данные (в оперативной памяти)
current_orders = {}
registration_steps = {}

app = Flask(__name__)

def load_users_data():
    """Загрузка базы клиентов из файла"""
    try:
        if os.path.exists(USERS_DB_FILE):
            with open(USERS_DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Ошибка загрузки users_data: {e}")
    return {}

def save_users_data():
    """Сохранение базы клиентов в файл"""
    try:
        with open(USERS_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(users_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения users_data: {e}")

def load_orders_history():
    """Загрузка истории заказов из файла"""
    try:
        if os.path.exists(ORDERS_DB_FILE):
            with open(ORDERS_DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Ошибка загрузки orders_history: {e}")
    return {}

def save_orders_history():
    """Сохранение истории заказов в файл"""
    try:
        with open(ORDERS_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(orders_history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения orders_history: {e}")

def add_order_to_history(user_data, date_str):
    """Добавление заказа в историю"""
    try:
        if date_str not in orders_history:
            orders_history[date_str] = []
        
        order_entry = {
            'user_id': user_data.get('user_id'),
            'location_name': user_data['location_name'],
            'address': user_data['address'],
            'orders': user_data['orders'].copy(),
            'total_items': sum(user_data['orders'].values()),
            'timestamp': datetime.now().strftime('%H:%M')
        }
        
        orders_history[date_str].append(order_entry)
        save_orders_history()
    except Exception as e:
        print(f"Ошибка добавления в историю: {e}")

# Загрузка данных при запуске
users_data = load_users_data()
orders_history = load_orders_history()

print(f"Загружено пользователей: {len(users_data)}")
print(f"Загружено дней в истории: {len(orders_history)}")

@app.route(BOT_URL, methods=['POST'])
def webhook():
    print(f"ПОЛУЧЕН POST на {BOT_URL}")
    try:
        if request.headers.get('content-type') == 'application/json':
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            print(f"ОБНОВЛЕНИЕ: {update}")  # ← ВИДИМ, ЧТО ПРИШЛО
            bot.process_new_updates([update])
            return '', 200
        else:
            print("ОТКЛОНЁН: не JSON")
            abort(403)
    except Exception as e:
        print(f"ОШИБКА В WEBHOOK: {e}")
        return 'Error', 500

@app.route('/')
def index():
    return "Бот работает на Railway!"

def get_user_data(user_id):
    """Получить данные пользователя"""
    user_id_str = str(user_id)
    if user_id_str not in users_data:
        users_data[user_id_str] = {
            'user_id': user_id_str,
            'address': '',
            'location_name': '', 
            'orders': {},
            'registered': False,
            'registration_date': datetime.now().strftime('%d.%m.%Y %H:%M')
        }
        save_users_data()  # Сохраняем нового пользователя
    return users_data[user_id_str]

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
        "Добро пожаловать! Давайте зарегистрируем вас.\n\n"
        "**Как называется ваша точка/магазин?**\n"
        "Например: 'Магазин у дома', 'Офис на Ленина', 'Кафе Уют'"
    )

@bot.message_handler(commands=['admin'])
def admin_panel(message: Message):
    """Панель администратора"""
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "Доступ запрещен")
        return
    
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton('Excel Сводка', callback_data='admin_excel'),
        InlineKeyboardButton('Текстовая сводка', callback_data='admin_summary'),
        InlineKeyboardButton('База клиентов', callback_data='admin_clients'),
        InlineKeyboardButton('Удалить клиентов', callback_data='admin_delete_clients'),
        InlineKeyboardButton('История заказов', callback_data='admin_history'),
        InlineKeyboardButton('Обнулить заказы', callback_data='admin_clear'),
        InlineKeyboardButton('Экспорт данных', callback_data='admin_export'),
    ]
    markup.add(*buttons)
    
    stats_text = f"**Статистика:**\nКлиентов: {len(users_data)}\nДней в истории: {len(orders_history)}"
    
    bot.send_message(message.chat.id, f"**Панель администратора**\n\n{stats_text}", reply_markup=markup)

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
            "**Теперь укажите адрес доставки:**\n"
            "Например: 'ул. Ленина, 15', 'ТЦ Центральный, 2 этаж'"
        )
        
    elif step == 'waiting_address':
        user_data['address'] = message.text.strip()
        user_data['registered'] = True
        user_data['registration_date'] = datetime.now().strftime('%d.%m.%Y %H:%M')
        del registration_steps[user_id]
        
        save_users_data()  # Сохраняем данные после регистрации
        
        bot.send_message(
            message.chat.id,
            f"**Регистрация завершена!**\n\n"
            f"Точка: {user_data['location_name']}\n"
            f"Адрес: {user_data['address']}\n\n"
            f"Теперь вы можете делать заказы!"
        )
        
        show_main_menu(message.chat.id, user_data)

def show_main_menu(chat_id, user_data):
    """Показать главное меню"""
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton('Добавить заказ', callback_data='add_order'),
        InlineKeyboardButton('Мой заказ', callback_data='my_order'),
        InlineKeyboardButton('Изменить заказ', callback_data='edit_order'),
        InlineKeyboardButton('Мои данные', callback_data='my_data'),
    ]
    markup.add(*buttons)
    
    welcome_text = f"{user_data['location_name']}\n{user_data['address']}\n\nВыберите действие:"
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
        show_clients_database(call)
    elif call.data == 'admin_delete_clients':
        show_delete_clients_menu(call)
    elif call.data == 'admin_history':
        show_orders_history(call)
    elif call.data == 'admin_clear':
        clear_all_orders(call)
    elif call.data == 'admin_export':
        export_all_data(call)
    elif call.data in positions:
        current_orders[user_id] = {'position': call.data}
        bot.answer_callback_query(call.id, f"Выбрано: {call.data}")
        bot.send_message(chat_id, f"Сколько штук {call.data}?")
    elif call.data.startswith('edit_'):
        position = call.data[5:]
        current_orders[user_id] = {'position': position, 'editing': True}
        bot.answer_callback_query(call.id, f"Изменяем: {position}")
        bot.send_message(chat_id, f"Введите новое количество для {position}:")
    elif call.data == 'back_to_main':
        bot.answer_callback_query(call.id, "Возврат в меню")
        bot.delete_message(chat_id, call.message.message_id)
        show_main_menu(chat_id, user_data)
    elif call.data == 'clear_order':
        user_data['orders'] = {}
        save_users_data()
        bot.answer_callback_query(call.id, "Заказ очищен")
        bot.delete_message(chat_id, call.message.message_id)
        show_main_menu(chat_id, user_data)
    elif call.data.startswith('delete_user_'):
        delete_user(call)
    elif call.data == 'admin_stats':
        bot.answer_callback_query(call.id, "Детальная статистика")
        bot.send_message(chat_id, "Детальная статистика (в разработке): \n- Общее заказов: ...\n- Топ позиция: ...")
    elif call.data == 'back_to_admin':
        bot.answer_callback_query(call.id)
        bot.delete_message(chat_id, call.message.message_id)
        admin_panel(call.message)

def show_positions_menu(chat_id):
    markup = InlineKeyboardMarkup(row_width=2)
    for pos in positions.keys():
        markup.add(InlineKeyboardButton(pos, callback_data=pos))
    markup.add(InlineKeyboardButton('Назад', callback_data='back_to_main'))
    
    bot.send_message(chat_id, "Выберите позицию для заказа:", reply_markup=markup)

def show_user_order(call, user_data):
    user_orders = user_data['orders']
    
    if not user_orders:
        bot.answer_callback_query(call.id, "У вас нет заказов")
        bot.send_message(call.message.chat.id, "У вас еще нет заказов на сегодня.")
        return
    
    total_items = sum(user_orders.values())
    
    order_text = f"**{user_data['location_name']}**\n"
    order_text += f"{user_data['address']}\n\n"
    order_text += "**Ваш заказ на сегодня:**\n\n"
    
    for pos, qty in user_orders.items():
        order_text += f"• {pos}: {qty} шт.\n"
    
    order_text += f"\n**Итого:** {total_items} шт."
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, order_text)

def show_user_data(call, user_data):
    user_orders = user_data['orders']
    total_items = sum(user_orders.values()) if user_orders else 0
    
    data_text = "**Ваши данные:**\n\n"
    data_text += f"**Точка:** {user_data['location_name']}\n"
    data_text += f"**Адрес:** {user_data['address']}\n"
    data_text += f"**Дата регистрации:** {user_data.get('registration_date', 'неизвестно')}\n"
    data_text += f"**Заказов сегодня:** {total_items} шт.\n\n"
    data_text += "_Чтобы изменить данные, перезапустите бота /start_"
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, data_text)

def show_edit_menu(call, user_data):
    user_orders = user_data['orders']
    
    if not user_orders:
        bot.answer_callback_query(call.id, "Нет заказов для редактирования")
        return
    
    markup = InlineKeyboardMarkup(row_width=2)
    
    for pos in user_orders.keys():
        markup.add(InlineKeyboardButton(f"{pos}", callback_data=f'edit_{pos}'))
    
    markup.add(InlineKeyboardButton('Добавить еще', callback_data='add_order'))
    markup.add(InlineKeyboardButton('Очистить все', callback_data='clear_order'))
    markup.add(InlineKeyboardButton('Назад', callback_data='back_to_main'))
    
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
            action_text = f"Удалено: {position}"
        else:
            user_data['orders'][position] = quantity
            action_text = f"{'Обновлено' if is_editing else 'Добавлено'} {quantity} шт. {position}"
        
        save_users_data()  # Сохраняем после изменения заказа
        
        bot.reply_to(message, f"{action_text} для {user_data['location_name']}!")
        del current_orders[user_id]
        
        show_main_menu(chat_id, user_data)
        
    except ValueError:
        bot.reply_to(message, "Введите целое число (0 для удаления позиции):")

def generate_excel_file():
    """Генерация Excel файла со сводкой"""
    active_users = [data for data in users_data.values() if data.get('orders') and data.get('registered')]
    
    if not active_users:
        return None
    
    # Сортируем по названию точки
    active_users.sort(key=lambda x: x['location_name'])
    
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
    num_positions = len(positions)
    header_end_col = get_column_letter(3 + num_positions + 1)  # №, Точка, Адрес, positions, ИТОГО
    ws.merge_cells(f'A1:{header_end_col}1')
    ws['A1'] = f"Сводка заказов от {datetime.now().strftime('%d.%m.%Y')}"
    ws['A1'].font = header_font
    ws['A1'].alignment = center_align
    
    # Пустая строка
    ws.append([])
    
    # Заголовки таблицы
    headers = ['№', 'Точка', 'Адрес'] + list(positions.keys()) + ['ИТОГО']
    ws.append(headers)
    
    # Применяем стили к заголовкам
    header_row = 3
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=header_row, column=col)
        cell.font = title_font
        cell.alignment = center_align
        cell.border = border
    
    # Данные по клиентам
    row_num = 4
    for i, user_data in enumerate(active_users, 1):
        row = [i, user_data['location_name'], user_data['address']]
        total = 0
        
        for pos in positions.keys():
            qty = user_data['orders'].get(pos, 0)
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
        row_num += 1
    
    # Итоговая строка
    ws.append([])
    row_num += 1
    total_row = ['ВСЕГО', '', '']
    
    for pos_idx in range(len(positions)):
        col_idx = 4 + pos_idx
        pos_total = sum(ws.cell(row=r, column=col_idx).value or 0 for r in range(4, row_num))
        total_row.append(pos_total)
    
    grand_total = sum(total_row[3:])
    total_row.append(grand_total)
    ws.append(total_row)
    
    # Стили для итоговой строки
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=row_num + 1, column=col)
        cell.font = bold_font
        cell.border = border
        if col >= 4:
            cell.alignment = center_align
    
    # Настраиваем ширину колонок
    column_widths = {
        'A': 5,    # №
        'B': 25,   # Точка
        'C': 30,   # Адрес
    }
    
    for i, pos in enumerate(positions.keys(), 4):
        col_letter = get_column_letter(i)
        column_widths[col_letter] = 8
    
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
    try:
        excel_buffer = generate_excel_file()
        
        if not excel_buffer:
            if call:
                bot.answer_callback_query(call.id, "Нет заказов")
                bot.send_message(call.message.chat.id, "Нет заказов за сегодня.")
            else:
                bot.send_message(ADMIN_CHAT_ID, "Нет заказов за сегодня.")
            return
        
        filename = f"заказы_{datetime.now().strftime('%d.%m.%Y')}.xlsx"
        excel_buffer.name = filename  # Устанавливаем атрибут name для InputFile
        
        input_file = telebot.types.InputFile(excel_buffer)
        
        if call:
            bot.answer_callback_query(call.id)
            bot.send_document(
                call.message.chat.id,
                document=input_file,
                caption=f"Сводка заказов от {datetime.now().strftime('%d.%m.%Y')}\n\nФайл готов для открытия в Excel"
            )
        else:
            current_date = datetime.now().strftime('%Y-%m-%d')
            for user_data in users_data.values():
                if user_data.get('orders') and user_data.get('registered'):
                    add_order_to_history(user_data, current_date)
            
            bot.send_document(
                ADMIN_CHAT_ID,
                document=input_file,
                caption=f"Автоматическая сводка заказов от {datetime.now().strftime('%d.%m.%Y')}"
            )
            
    except Exception as e:
        print(f"Ошибка при отправке сводки: {e}")
        if call:
            bot.send_message(call.message.chat.id, f"Ошибка при генерации Excel: {e}")
        else:
            bot.send_message(ADMIN_CHAT_ID, f"Ошибка при отправке сводки: {e}")

def send_text_summary(call):
    """Текстовая сводка"""
    active_users = [data for data in users_data.values() if data.get('orders') and data.get('registered')]
    
    if not active_users:
        bot.answer_callback_query(call.id, "Нет заказов")
        bot.send_message(call.message.chat.id, "Нет заказов за сегодня.")
        return
    
    active_users.sort(key=lambda x: x['location_name'])
    
    summary_text = f"**Сводка заказов от {datetime.now().strftime('%d.%m.%Y')}**\n"
    summary_text += f"Клиентов: {len(active_users)}\n\n"
    
    for user_data in active_users:
        total_items = sum(user_data['orders'].values())
        order_details = [f"{pos}:{qty}" for pos, qty in user_data['orders'].items() if qty > 0]
        
        details_str = ", ".join(order_details)
        summary_text += f"• **{user_data['location_name']}** - {total_items} шт.\n"
        summary_text += f"  {details_str}\n"
        summary_text += f"  {user_data['address']}\n\n"
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, summary_text)

def show_clients_database(call):
    """Показать базу клиентов"""
    registered_users = [data for data in users_data.values() if data['registered']]
    
    if not registered_users:
        bot.answer_callback_query(call.id, "База клиентов пуста")
        bot.send_message(call.message.chat.id, "База клиентов пуста.")
        return
    
    clients_text = f"**БАЗА КЛИЕНТОВ**\nВсего: {len(registered_users)}\n\n"
    
    for i, user_data in enumerate(registered_users, 1):
        order_count = sum(user_data['orders'].values())
        last_order = "Сегодня" if order_count > 0 else "Нет заказов"
        clients_text += f"{i}. **{user_data['location_name']}**\n"
        clients_text += f"   {user_data['address']}\n"
        clients_text += f"   Регистрация: {user_data.get('registration_date', 'неизвестно')}\n"
        clients_text += f"   {last_order} ({order_count} шт.)\n\n"
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, clients_text)

def show_delete_clients_menu(call):
    if str(call.message.chat.id) != ADMIN_CHAT_ID:
        bot.answer_callback_query(call.id, "Доступ запрещен")
        return
    
    registered_users = [data for data in users_data.values() if data['registered']]
    
    if not registered_users:
        bot.answer_callback_query(call.id, "Нет клиентов для удаления")
        bot.send_message(call.message.chat.id, "Нет клиентов для удаления.")
        return
    
    markup = InlineKeyboardMarkup(row_width=1)
    for user_data in registered_users:
        button_text = f"Удалить {user_data['location_name']} (ID: {user_data['user_id']})"
        markup.add(InlineKeyboardButton(button_text, callback_data=f"delete_user_{user_data['user_id']}"))
    
    markup.add(InlineKeyboardButton('Назад в админ', callback_data='back_to_admin'))
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Выберите клиента для удаления:", reply_markup=markup)

def delete_user(call):
    if str(call.message.chat.id) != ADMIN_CHAT_ID:
        bot.answer_callback_query(call.id, "Доступ запрещен")
        return
    
    user_id_str = call.data.split('_')[-1]
    if user_id_str in users_data:
        location_name = users_data[user_id_str]['location_name']
        del users_data[user_id_str]
        save_users_data()
        bot.answer_callback_query(call.id, f"Клиент {location_name} удален")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, f"Клиент {location_name} удален из базы (заказы обнулены).")
    else:
        bot.answer_callback_query(call.id, "Клиент не найден")

def show_orders_history(call):
    """Показать историю заказов"""
    if not orders_history:
        bot.answer_callback_query(call.id, "История заказов пуста")
        bot.send_message(call.message.chat.id, "История заказов пуста.")
        return
    
    history_text = f"**ИСТОРИЯ ЗАКАЗОВ**\nДней в истории: {len(orders_history)}\n\n"
    
    sorted_dates = sorted(orders_history.keys(), reverse=True)[:7]
    
    for date_str in sorted_dates:
        date_orders = orders_history[date_str]
        total_orders = len(date_orders)
        total_items = sum(order['total_items'] for order in date_orders)
        
        history_text += f"**{datetime.strptime(date_str, '%Y-%m-%d').strftime('%d.%m.%Y')}**\n"
        history_text += f"   Клиентов: {total_orders}\n"
        history_text += f"   Товаров: {total_items} шт.\n\n"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton('Детальная статистика', callback_data='admin_stats'))
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, history_text, reply_markup=markup)

def clear_all_orders(call):
    """Очистить все заказы"""
    cleared_count = 0
    for user_data in users_data.values():
        if user_data['orders']:
            user_data['orders'] = {}
            cleared_count += 1
    
    save_users_data()
    
    bot.answer_callback_query(call.id, f"Очищено {cleared_count} заказов")
    bot.send_message(call.message.chat.id, f"Очищены заказы у {cleared_count} клиентов!")

def clear_all_orders_auto():
    cleared_count = 0
    for user_data in users_data.values():
        if user_data['orders']:
            user_data['orders'] = {}
            cleared_count += 1
    
    if cleared_count > 0:
        save_users_data()
    
    print(f"Автоматически очищены заказы у {cleared_count} пользователей")
    return cleared_count

def export_all_data(call):
    """Экспорт всех данных в JSON"""
    try:
        export_data = {
            'users': users_data,
            'orders_history': orders_history,
            'export_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        export_json = json.dumps(export_data, ensure_ascii=False, indent=2).encode('utf-8')
        json_buffer = io.BytesIO(export_json)
        filename = f"backup_data_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        json_buffer.name = filename  # Устанавливаем name для InputFile
        
        input_file = telebot.types.InputFile(json_buffer)
        
        bot.answer_callback_query(call.id)
        bot.send_document(
            call.message.chat.id,
            document=input_file,
            caption="Полный бэкап данных системы"
        )
    except Exception as e:
        bot.answer_callback_query(call.id, "Ошибка экспорта")
        bot.send_message(call.message.chat.id, f"Ошибка при экспорте данных: {e}")

def check_scheduled_tasks():
    msk_tz = timezone(timedelta(hours=3))
    now = datetime.now(msk_tz)
    current_time = now.strftime('%H:%M:%S')
    
    print(f"--- ПРОВЕРКА: {current_time} ---")
    
    # Тест: сводка через 1 минуту, очистка через 2
    test_send_minute = (now.minute + 1) % 60
    test_clear_minute = (now.minute + 2) % 60
    
    print(f"Ожидаем: сводка в {test_send_minute:02d}, очистка в {test_clear_minute:02d}")

    # ТЕСТ: сводка — в течение всей минуты
    if now.minute == test_send_minute:
        print("*** ТРИГГЕР: ОТПРАВКА СВОДКИ ***")
        try:
            send_excel_summary()
            print("СВОДКА ОТПРАВЛЕНА!")
        except Exception as e:
            print(f"ОШИБКА СВОДКИ: {e}")
        time.sleep(70)  # Чтобы не повторять

    # ТЕСТ: очистка — в течение следующей минуты
    elif now.minute == test_clear_minute:
        print("*** ТРИГГЕР: ОЧИСТКА ЗАКАЗОВ ***")
        try:
            cleared_count = clear_all_orders_auto()
            bot.send_message(ADMIN_CHAT_ID, f"ТЕСТ: Заказы обнулены. Очищено: {cleared_count}")
            print(f"ОЧИЩЕНО: {cleared_count}")
        except Exception as e:
            print(f"ОШИБКА ОЧИСТКИ: {e}")
        time.sleep(70)

    else:
        print(f"Ждём... сейчас {now.minute}, нужно {test_send_minute} или {test_clear_minute}")

def scheduler():
    print("🚀 ПЛАННИРОВЩИК ЗАПУЩЕН! Проверяем каждую секунду...")
    
    while True:
        try:
            check_scheduled_tasks()
            time.sleep(10)  # ← Уменьшил до 10 сек для быстрой отладки
        except Exception as e:
            print(f"❌ КРИТИЧЕСКАЯ ОШИБКА ПЛАННИРОВЩИКА: {e}")
            time.sleep(10)

def setup_webhook():
    print("Удаляю старый webhook...")
    bot.remove_webhook()
    time.sleep(2)

    # Полный URL
    webhook_url = "https://web-production-d7a9d.up.railway.app/webhook"
    print(f"Устанавливаю webhook: {webhook_url}")

    result = bot.set_webhook(url=webhook_url)
    if result:
        print("WEBHOOK УСПЕШНО УСТАНОВЛЕН!")
    else:
        print("ОШИБКА: Webhook НЕ установлен!")
        print("Проверь: токен, URL, доступность /webhook")
     

# === ЗАПУСК ПЛАНИРОВЩИКА И WEBHOOK ПРИ ИМПОРТЕ ===
def _start_bot():
    print("=== ИНИЦИАЛИЗАЦИЯ БОТА ===")
    
    # Установка webhook
    print("Удаляю старый webhook...")
    bot.remove_webhook()
    time.sleep(2)
    
    webhook_url = "https://web-production-d7a9d.up.railway.app/webhook"
    print(f"Устанавливаю webhook: {webhook_url}")
    result = bot.set_webhook(url=webhook_url)
    if result:
        print("WEBHOOK УСПЕШНО УСТАНОВЛЕН!")
    else:
        print("ОШИБКА: Webhook НЕ установлен!")
    
    # Запуск планировщика в отдельном потоке
    def run_scheduler():
        print("ПЛАННИРОВЩИК ЗАПУЩЕН!")
        while True:
            try:
                check_scheduled_tasks()
                time.sleep(10)
            except Exception as e:
                print(f"ОШИБКА ПЛАНИРОВЩИКА: {e}")
                time.sleep(10)
    
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    print("ПЛАНИРОВЩИК ЗАПУЩЕН!")

# Вызываем при импорте — безопасно для Gunicorn
_start_bot()
