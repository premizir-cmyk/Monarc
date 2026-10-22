import os
import re
import json
import time
import zipfile
import telebot
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone
from telebot import types

# --- ОСНОВНЫЕ НАСТРОЙКИ КЛИЕНТА ---
TOKEN = '8898914668:AAEXJx5exYqF4fctUeGe3uSkHOwGHb9-Ar4'

# Канал для публикаций
CHANNELS = ['-1003934124856']
PRIMARY_CHANNEL = CHANNELS[0]

BOT_USERNAME = '@AsbergM_bot'
MY_USERNAME = '@br_vasrss'

# Владельцы бота (Твой ID + ID клиента)
OWNER_ID = [7605961809, 6218636923]
MAIN_ADMIN_ID = OWNER_ID[0]

bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=16)

MSK = timezone(timedelta(hours=3))

# --- ХРАНЕНИЕ ФАЙЛОВ ---
DATA_DIR = '/app/data' if os.path.exists('/app/data') else '.'
DB_FILE = os.path.join(DATA_DIR, 'users.json')
ADMIN_HISTORY_FILE = os.path.join(DATA_DIR, 'admin_history.json')
COOLDOWN_FILE = os.path.join(DATA_DIR, 'cooldowns.json')
POSTS_FILE = os.path.join(DATA_DIR, 'active_posts.json')
BAN_FILE = os.path.join(DATA_DIR, 'blacklist.json')

# КУЛДАУНЫ (в секундах)
USER_COOLDOWN_TIME = 1800      # 30 минут между своими постами
GLOBAL_COOLDOWN_TIME = 300     # 5 минут между чужими постами
PLATFORM_COOLDOWN_TIME = 1800  # 30 минут для одной платформы

file_lock = threading.Lock()
user_creation_data = {}
admin_action_data = {}

# --- РАБОТА С ДАННЫМИ ---

def load_data(filename):
    with file_lock:
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[LOG] Ошибка чтения {filename}: {e}", flush=True)
                return [] if filename.endswith(('blacklist.json', 'admin_history.json')) else {}
        return [] if filename.endswith(('blacklist.json', 'admin_history.json')) else {}

def save_data(filename, data):
    with file_lock:
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[LOG] Ошибка сохранения {filename}: {e}", flush=True)

def is_owner(user_id):
    return user_id in OWNER_ID

def is_banned(user_id):
    blacklist = load_data(BAN_FILE)
    return str(user_id) in blacklist or user_id in blacklist

def is_work_time():
    now = datetime.now(MSK)
    if 4 <= now.hour < 23:
        return True
    if now.hour == 23 and now.minute <= 45:
        return True
    return False

def get_user_display_name(user_id):
    """Пытается получить актуальный юзернейм или имя через Telegram API или из базы"""
    try:
        chat_member = bot.get_chat(user_id)
        if chat_member.username:
            return f"@{chat_member.username}"
        first = chat_member.first_name or ""
        last = chat_member.last_name or ""
        full_name = f"{first} {last}".strip()
        if full_name:
            return f"{full_name}"
    except Exception:
        pass
    return "Неизвестно"

def is_user_active(user_id):
    if is_owner(user_id):
        return True
    if is_banned(user_id):
        return False
    users = load_data(DB_FILE)
    str_id = str(user_id)
    if str_id in users:
        data = users[str_id]
        if isinstance(data, dict):
            exp_time = data.get("expire", 0)
            if exp_time > 0 and time.time() < exp_time:
                return True
            else:
                notify_expired(user_id)
    return False

def notify_expired(user_id):
    users = load_data(DB_FILE)
    str_id = str(user_id)
    if str_id in users:
        user_info = users[str_id]
        start_date = user_info.get("start_date", "Неизвестно")
        exp_date = datetime.fromtimestamp(user_info.get("expire", 0), MSK).strftime('%d.%m.%Y %H:%M')
        
        # Получаем актуальный юзернейм/имя перед удалением
        username_display = get_user_display_name(int(str_id))

        history = load_data(ADMIN_HISTORY_FILE)
        if not isinstance(history, list): history = []
        history.append({
            "user_id": str_id,
            "username": username_display,
            "start_date": start_date,
            "end_date": exp_date
        })
        save_data(ADMIN_HISTORY_FILE, history)
        
        del users[str_id]
        save_data(DB_FILE, users)
        
        for owner in OWNER_ID:
            try:
                bot.send_message(owner, f"⚠️ У пользователя `{str_id}` ({username_display}) закончились права админа!", parse_mode="Markdown")
            except:
                pass

def normalize_platform_name(platform_text):
    return platform_text.strip().capitalize()

def contains_contacts(text):
    """Проверка текста на наличие юзернеймов, ссылок и Telegram контактов."""
    if '@' in text:
        return True
    if re.search(r'(https?://|t\.me/|telegram\.me/)', text, re.IGNORECASE):
        return True
    return False

# --- ПРОВЕРКА КУЛДАУНОВ ---

def get_cooldown_status(user_id, platform_name):
    if is_owner(user_id):
        return True, ""
    
    cooldowns = load_data(COOLDOWN_FILE)
    now = time.time()
    str_id = str(user_id)
    norm_platform = normalize_platform_name(platform_name)

    if str_id in cooldowns and isinstance(cooldowns[str_id], dict):
        last_user_post = cooldowns[str_id].get("user_last", 0)
        elapsed = now - last_user_post
        if elapsed < USER_COOLDOWN_TIME:
            left_min = int((USER_COOLDOWN_TIME - elapsed) // 60) + 1
            return False, f"⏳ Кулдаун между своими постами! Подождите ещё {left_min} мин."

    global_last = cooldowns.get("global_last", 0)
    global_last_user = cooldowns.get("global_last_user", 0)
    if global_last_user != user_id and (now - global_last < GLOBAL_COOLDOWN_TIME):
        left_sec = int(GLOBAL_COOLDOWN_TIME - (now - global_last))
        return False, f"⏳ Кулдаун между постами разных юзеров! Подождите ещё {left_sec} сек."

    platform_last = cooldowns.get("platforms", {}).get(norm_platform, 0)
    if now - platform_last < PLATFORM_COOLDOWN_TIME:
        left_min = int((PLATFORM_COOLDOWN_TIME - (now - platform_last)) // 60) + 1
        return False, f"⏳ Платформа «{norm_platform}» на кулдауне! Выберите другую или подождите {left_min} мин."

    return True, ""

def update_cooldowns(user_id, platform_name):
    if is_owner(user_id):
        return
    cooldowns = load_data(COOLDOWN_FILE)
    if not isinstance(cooldowns, dict): cooldowns = {}
    
    now = time.time()
    str_id = str(user_id)
    norm_platform = normalize_platform_name(platform_name)

    if str_id not in cooldowns or not isinstance(cooldowns[str_id], dict):
        cooldowns[str_id] = {}

    cooldowns[str_id]["user_last"] = now
    cooldowns["global_last"] = now
    cooldowns["global_last_user"] = user_id

    if "platforms" not in cooldowns:
        cooldowns["platforms"] = {}
    cooldowns["platforms"][norm_platform] = now

    save_data(COOLDOWN_FILE, cooldowns)

# --- ЗАКРЫТИЕ ПОСТОВ ---

def close_posts_in_channels(message_ids_dict):
    CLOSED_CARD = (
        "❌ **Задание закончилось, ожидайте следующего.**\n\n"
        "Не успеваете взять задания? Включите уведомления и берите их первыми! 🔔"
    )
    for ch_id, msg_id in message_ids_dict.items():
        try:
            bot.edit_message_text(
                text=CLOSED_CARD,
                chat_id=int(ch_id),
                message_id=int(msg_id),
                parse_mode="Markdown",
                reply_markup=None
            )
        except Exception as e:
            print(f"[LOG] Ошибка закрытия поста {msg_id}: {e}", flush=True)

# --- КЛАВИАТУРЫ ---

def get_persistent_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📱 Главное меню"))
    return markup

def get_main_menu_keyboard(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(text="📝 Выставить пост", callback_data="start_create_post"),
        types.InlineKeyboardButton(text="🔒 Закрыть мой пост", callback_data="my_active_posts")
    )
    if is_owner(user_id):
        markup.add(types.InlineKeyboardButton(text="🛠 Админ-панель", callback_data="open_admin_panel"))
    return markup

def get_admin_panel_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(text="🟢 Выдать админку (по дням)", callback_data="admin_grant_days"),
        types.InlineKeyboardButton(text="📋 Активные админы", callback_data="admin_list_active"),
        types.InlineKeyboardButton(text="📜 История всех админов", callback_data="admin_list_history"),
        types.InlineKeyboardButton(text="🔴 Забрать права", callback_data="admin_revoke"),
        types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="main_menu")
    )
    return markup

# --- ОБРАБОТКА CALLBACK ---

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id

    if call.data == "complain_action":
        bot.answer_callback_query(
            call.id,
            f"🚨 По вопросам нарушений и жалоб пишите администратору: {MY_USERNAME}",
            show_alert=True
        )
        return

    bot.answer_callback_query(call.id)

    if not is_user_active(user_id):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="💬 Продлить админку", url=f"https://t.me/{MY_USERNAME.replace('@','')}") )
        bot.send_message(
            call.message.chat.id,
            f"⛔ **У вас нет прав.**\nДля приобретения или продления админки пишите: {MY_USERNAME}",
            parse_mode="Markdown",
            reply_markup=markup
        )
        return

    if call.data == "start_create_post":
        if not is_work_time():
            bot.send_message(call.message.chat.id, "🌙 Публикация постов доступна только с 04:00 до 23:45 по МСК!")
            return

        posts_data = load_data(POSTS_FILE)
        if str(user_id) in posts_data:
            bot.send_message(
                call.message.chat.id,
                "⚠️ **У вас уже есть активный пост!**\n\nСначала закройте прошлый пост через кнопку «🔒 Закрыть мой пост», чтобы выложить новый.",
                parse_mode="Markdown",
                reply_markup=get_main_menu_keyboard(user_id)
            )
            return

        user_creation_data[user_id] = {'step': 1}
        bot.send_message(
            call.message.chat.id,
            "📌 **Шаг 1 из 3:**\nВведите название площадки (например: *Яндекс Карты*, *Авито*):",
            parse_mode="Markdown"
        )

    elif call.data == "confirm_publish_now":
        if user_id not in user_creation_data:
            bot.send_message(call.message.chat.id, "❌ Ошибка. Начните заново.")
            return

        c_data = user_creation_data[user_id]
        platform = c_data['platform']
        payment = c_data['payment']
        desc = c_data['desc']

        can_post, reason = get_cooldown_status(user_id, platform)
        if not can_post:
            bot.send_message(call.message.chat.id, reason)
            return

        formatted_post = (
            f"💬 ЕСТЬ ЗАДАНИЕ\n\n"
            f"📑 Площадка: {platform}\n"
            f"💸 Оплата: {payment}\n"
            f"✨ Описание: {desc}"
        )

        try:
            auto_msg = f"Здравствуйте! Я из канала MONARCH я хочу взять у вас задание ({platform}) за ({payment})руб!"
            encoded_text = urllib.parse.quote(auto_msg)
            direct_url = f"https://t.me/{call.from_user.username}?text={encoded_text}" if call.from_user.username else f"tg://user?id={user_id}"
            clean_bot_username = BOT_USERNAME.replace('@', '')

            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(text="Перейти к выполнению 💬", url=direct_url),
                types.InlineKeyboardButton(text="🚫 У меня спам-блок", url=f"https://t.me/{clean_bot_username}?start=spamblock_{user_id}"),
                types.InlineKeyboardButton(text="🚨 Пожаловаться", callback_data="complain_action")
            )

            published_msg = bot.send_message(PRIMARY_CHANNEL, formatted_post, reply_markup=markup)

            posts_data = load_data(POSTS_FILE)
            if not isinstance(posts_data, dict): posts_data = {}
            posts_data[str(user_id)] = {
                "user_id": user_id,
                "message_ids": {str(PRIMARY_CHANNEL): published_msg.message_id},
                "platform": platform
            }
            save_data(POSTS_FILE, posts_data)

            update_cooldowns(user_id, platform)

            bot.send_message(
                call.message.chat.id,
                "🚀 **Ваш пост успешно опубликован в канале!**\nНе забудьте закрыть его, когда задание будет выполнено.",
                parse_mode="Markdown",
                reply_markup=get_main_menu_keyboard(user_id)
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Ошибка отправки поста: {e}")

        if user_id in user_creation_data:
            del user_creation_data[user_id]

    elif call.data == "my_active_posts":
        posts_data = load_data(POSTS_FILE)
        str_id = str(user_id)
        if str_id not in posts_data:
            bot.send_message(call.message.chat.id, "❌ У вас нет активных открытых постов.", reply_markup=get_main_menu_keyboard(user_id))
            return

        p_info = posts_data[str_id]
        msg_dict = p_info.get("message_ids", {})
        close_posts_in_channels(msg_dict)
        
        del posts_data[str_id]
        save_data(POSTS_FILE, posts_data)

        bot.send_message(call.message.chat.id, "✅ Ваш пост успешно закрыт! Теперь вы можете выложить новый.", reply_markup=get_main_menu_keyboard(user_id))

    elif call.data == "open_admin_panel":
        if not is_owner(user_id): return
        bot.send_message(call.message.chat.id, "🛠 **Панель владельца:**", parse_mode="Markdown", reply_markup=get_admin_panel_keyboard())

    elif call.data == "admin_grant_days":
        if not is_owner(user_id): return
        admin_action_data[user_id] = {'action': 'grant_step1'}
        bot.send_message(call.message.chat.id, "🟢 Введите Telegram ID пользователя:")

    elif call.data == "admin_list_active":
        if not is_owner(user_id): return
        users = load_data(DB_FILE)
        if not users:
            bot.send_message(call.message.chat.id, "📋 Список активных админов пуст.")
            return
        
        text = "📋 **Активные админы:**\n\n"
        for uid, uinfo in users.items():
            exp_str = datetime.fromtimestamp(uinfo.get("expire", 0), MSK).strftime('%d.%m.%Y %H:%M')
            start_str = uinfo.get("start_date", "Неизвестно")
            uname = get_user_display_name(int(uid))
            text += f"• `{uid}` ({uname}) | С: `{start_str}` | До: `{exp_str}`\n"
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown")

    elif call.data == "admin_list_history":
        if not is_owner(user_id): return
        history = load_data(ADMIN_HISTORY_FILE)
        if not history:
            bot.send_message(call.message.chat.id, "📜 История выдачи админок пуста.")
            return

        text = "📜 **История всех прошлых админов:**\n\n"
        for item in history[-15:]:
            u_id = item.get('user_id', 'Неизвестно')
            u_name = item.get('username', get_user_display_name(int(u_id)) if str(u_id).isdigit() else 'Неизвестно')
            start_str = item.get('start_date', 'Неизвестно')
            end_str = item.get('end_date', 'Неизвестно')
            text += f"• `{u_id}` ({u_name}) | С: `{start_str}` | До: `{end_str}`\n"
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown")

    elif call.data == "admin_revoke":
        if not is_owner(user_id): return
        admin_action_data[user_id] = {'action': 'revoke_step1'}
        bot.send_message(call.message.chat.id, "🔴 Введите ID пользователя, у которого нужно забрать админку:")

    elif call.data == "main_menu":
        bot.send_message(call.message.chat.id, "👋 Главное меню:", reply_markup=get_main_menu_keyboard(user_id))

# --- ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ---

@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id

    command_args = message.text.split()
    if len(command_args) > 1 and command_args[1].startswith("spamblock_"):
        author_id_str = command_args[1].replace("spamblock_", "")
        try:
            author_id = int(author_id_str)
            user_mention = f"@{message.from_user.username}" if message.from_user.username else f"ID: `{user_id}`"
            
            spam_notification = (
                f"⚠️ **У пользователя спам-блок!**\n\n"
                f"• Пользователь: {user_mention} (ID: `{user_id}`)\n"
                f"Хочет взять ваше задание, но у него не отправляется ЛС из-за спам-блока. Напишите ему первыми!"
            )
            bot.send_message(author_id, spam_notification, parse_mode="Markdown")
            bot.reply_to(message, "✅ Уведомление отправлено автору задания! Скоро он напишет вам сам.", reply_markup=get_persistent_keyboard())
        except Exception as e:
            bot.reply_to(message, "❌ Не удалось отправить уведомление автору.", reply_markup=get_persistent_keyboard())
        return

    if not is_user_active(user_id):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="💬 Написать разработчику", url=f"https://t.me/{MY_USERNAME.replace('@','')}") )
        bot.reply_to(
            message,
            f"⛔ **У вас нет прав.**\n\nДля покупки админки обратитесь к: {MY_USERNAME}",
            parse_mode="Markdown",
            reply_markup=markup
        )
        return

    bot.reply_to(message, "👋 Добро пожаловать!", reply_markup=get_main_menu_keyboard(user_id))
    bot.send_message(message.chat.id, "Клавиатура меню закреплена ниже.", reply_markup=get_persistent_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "📱 Главное меню")
def handle_menu_btn(message):
    user_id = message.from_user.id
    if not is_user_active(user_id):
        bot.reply_to(message, f"⛔ У вас нет прав. Пишите {MY_USERNAME}")
        return
    bot.send_message(message.chat.id, "👋 Главное меню:", reply_markup=get_main_menu_keyboard(user_id))

@bot.message_handler(content_types=['text'])
def text_handler(message):
    user_id = message.from_user.id

    # Действия Владельцев
    if is_owner(user_id) and user_id in admin_action_data:
        act = admin_action_data[user_id].get('action')
        
        if act == 'grant_step1':
            target_id = message.text.strip()
            if not target_id.isdigit():
                bot.reply_to(message, "❌ Некорректный ID. Введите цифры:")
                return
            admin_action_data[user_id]['target_id'] = target_id
            admin_action_data[user_id]['action'] = 'grant_step2'
            bot.reply_to(message, "Введите кол-во дней подписки (число):")
            return

        elif act == 'grant_step2':
            days_str = message.text.strip()
            if not days_str.isdigit():
                bot.reply_to(message, "❌ Введите только число дней:")
                return
            days = int(days_str)
            target_id = admin_action_data[user_id]['target_id']

            users = load_data(DB_FILE)
            now_dt = datetime.now(MSK)
            exp_time = time.time() + (days * 86400)
            
            users[target_id] = {
                "start_date": now_dt.strftime('%d.%m.%Y %H:%M'),
                "expire": exp_time
            }
            save_data(DB_FILE, users)

            target_uname = get_user_display_name(int(target_id))
            bot.reply_to(message, f"🎉 **Права админа для `{target_id}` ({target_uname}) успешно выданы на {days} дн.!**", parse_mode="Markdown")
            try:
                bot.send_message(int(target_id), f"🎉 **Вам выданы права админа (на {days} дн.)!**\nНажмите /start для работы.", reply_markup=get_persistent_keyboard())
            except:
                pass
            del admin_action_data[user_id]
            return

        elif act == 'revoke_step1':
            target_id = message.text.strip()
            users = load_data(DB_FILE)
            if target_id in users:
                # Сохраняем в историю перед удалением вручную
                user_info = users[target_id]
                start_date = user_info.get("start_date", "Неизвестно")
                exp_date = datetime.fromtimestamp(user_info.get("expire", 0), MSK).strftime('%d.%m.%Y %H:%M')
                uname = get_user_display_name(int(target_id))

                history = load_data(ADMIN_HISTORY_FILE)
                if not isinstance(history, list): history = []
                history.append({
                    "user_id": target_id,
                    "username": uname,
                    "start_date": start_date,
                    "end_date": exp_date
                })
                save_data(ADMIN_HISTORY_FILE, history)

                del users[target_id]
                save_data(DB_FILE, users)

                bot.reply_to(message, f"✅ Права у `{target_id}` ({uname}) забраны и внесены в историю.", parse_mode="Markdown")
            else:
                bot.reply_to(message, "⚠️ Этот ID не найден в активных админах.")
            del admin_action_data[user_id]
            return

    if not is_user_active(user_id):
        bot.reply_to(message, f"⛔ У вас нет прав. Пишите {MY_USERNAME}")
        return

    if user_id in user_creation_data:
        step = user_creation_data[user_id].get('step', 1)
        text = message.text.strip()

        # ПРОВЕРКА НА ЮЗЕРНЕЙМЫ И ССЫЛКИ
        if contains_contacts(text):
            bot.reply_to(
                message,
                "❌ **Указывать юзернеймы (@username) и ссылки в посте запрещено!**\n\nИсполнители смогут связаться с вами строго по кнопке под постом. Пожалуйста, введите текст без контактов:",
                parse_mode="Markdown"
            )
            return

        if step == 1:
            can_post, reason = get_cooldown_status(user_id, text)
            if not can_post:
                bot.reply_to(message, reason)
                del user_creation_data[user_id]
                return

            user_creation_data[user_id]['platform'] = text
            user_creation_data[user_id]['step'] = 2
            bot.reply_to(message, "💸 **Шаг 2 из 3:**\nВведите сумму оплаты в рублях (например: *150*):", parse_mode="Markdown")

        elif step == 2:
            user_creation_data[user_id]['payment'] = text
            user_creation_data[user_id]['step'] = 3
            bot.reply_to(message, "✨ **Шаг 3 из 3:**\nВведите краткое описание задания (без контактов):", parse_mode="Markdown")

        elif step == 3:
            user_creation_data[user_id]['desc'] = text
            
            c_data = user_creation_data[user_id]
            platform = c_data['platform']
            payment = c_data['payment']
            desc = c_data['desc']

            preview_text = (
                f"💬 ЕСТЬ ЗАДАНИЕ\n\n"
                f"📑 Площадка: {platform}\n"
                f"💸 Оплата: {payment}\n"
                f"✨ Описание: {desc}"
            )

            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(text="🚀 Опубликовать сейчас", callback_data="confirm_publish_now"),
                types.InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu")
            )

            bot.reply_to(message, f"👁 **ПРЕДПРОСМОТР ПОСТА:**\n\n{preview_text}\n\nВсё верно?", reply_markup=markup)

if __name__ == '__main__':
    print("🚀 Бот полностью готов и запущен!", flush=True)
    while True:
        try:
            bot.polling(none_stop=True, timeout=30, long_polling_timeout=30, skip_pending=True)
        except Exception as e:
            print(f"❌ Ошибка polling: {e}", flush=True)
            time.sleep(5)
