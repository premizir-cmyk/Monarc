import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
import threading
import time
import json
import os
import re
from datetime import datetime, date
import urllib.parse

# --- ОСНОВНЫЕ НАСТРОЙКИ ПОД ТВОЙ КАНАЛ И БОТА ---
TOKEN = '8841912645:AAHD0n4iKu5wE13zFkecawuDNK21SFCfSQ8'
CHANNEL_ID = '-1002345678901'  # Замени на ID твоего канала (или @username, если канал публичный)
CHANNEL_USERNAME = '@MonarchW0rk'
BOT_USERNAME = '@Monarchadm_bot'
MY_USERNAME = '@premizir'  # Твой юзернейм для связи

OWNER_ID = [7605961809]  # Твой ID владельца

bot = telebot.TeleBot(TOKEN)

# --- НАСТРОЙКА ХРАНЕНИЯ ФАЙЛОВ НА BOTHOST ---
DATA_DIR = '/app/data' if os.path.exists('/app/data') else '.'
DB_FILE = os.path.join(DATA_DIR, 'users.json')
COOLDOWN_FILE = os.path.join(DATA_DIR, 'cooldowns.json')
NOTIFIED_FILE = os.path.join(DATA_DIR, 'notified.json')
HISTORY_FILE = os.path.join(DATA_DIR, 'history.json')
POSTS_FILE = os.path.join(DATA_DIR, 'active_posts.json')
DAILY_LIMITS_FILE = os.path.join(DATA_DIR, 'daily_limits.json')

COOLDOWN_TIME = 7200    # Кулдаун 2 часа между постами (в секундах)

# --- ШАБЛОНЫ И ПРАВИЛА ---
TEMPLATE_TEXT = """Новое задание!

➤ Платформа: 
➤ Получите оплату: 
➤ Описание: """

RULES_TEXT = """⚠️ **ПРАВИЛА ПУБЛИКАЦИИ:**

1. **Строго по шаблону!** Бот проверяет структуру текста.
2. **Кулдаун:** Между постами 2 часа.
3. **Лимит:** У каждого тарифа свой суточный лимит постов.
4. **Закрытие постов:** Вы не сможете выложить новый пост, пока не закроете свой предыдущий пост командой `/close`.
5. **Запрещено:** Скамерство, спам, флуд.

🚨 *За нарушение правил доступ аннулируется без возврата средств!*"""

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def load_data(filename):
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Ошибка чтения {filename}: {e}")
            return {} if not filename.endswith('history.json') else []
    return {} if not filename.endswith('history.json') else []

def save_data(filename, data):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Ошибка сохранения {filename}: {e}")

def is_owner(user_id):
    return user_id in OWNER_ID

def is_user_active(user_id):
    if is_owner(user_id):
        return True
    users = load_data(DB_FILE)
    str_id = str(user_id)
    if str_id in users:
        expire_time = users[str_id].get("expire_time", 0) if isinstance(users[str_id], dict) else users[str_id]
        if time.time() < expire_time:
            return True
        else:
            del users[str_id]
            save_data(DB_FILE, users)
    return False

def get_user_daily_limit(user_id):
    if is_owner(user_id):
        return 999
    users = load_data(DB_FILE)
    str_id = str(user_id)
    if str_id in users and isinstance(users[str_id], dict):
        return users[str_id].get("daily_limit", 1)
    return 1

def can_user_post_today(user_id):
    if is_owner(user_id):
        return True
    
    daily_data = load_data(DAILY_LIMITS_FILE)
    str_id = str(user_id)
    today = str(date.today())

    if str_id not in daily_data or daily_data[str_id].get("date") != today:
        daily_data[str_id] = {"date": today, "count": 0}
        save_data(DAILY_LIMITS_FILE, daily_data)

    max_limit = get_user_daily_limit(user_id)
    return daily_data[str_id]["count"] < max_limit

def increment_daily_post_count(user_id):
    if is_owner(user_id):
        return
    daily_data = load_data(DAILY_LIMITS_FILE)
    str_id = str(user_id)
    today = str(date.today())

    if str_id not in daily_data or daily_data[str_id].get("date") != today:
        daily_data[str_id] = {"date": today, "count": 1}
    else:
        daily_data[str_id]["count"] += 1

    save_data(DAILY_LIMITS_FILE, daily_data)

def has_active_unclosed_post(user_id):
    if is_owner(user_id):
        return False
    posts = load_data(POSTS_FILE)
    for p_id, p_info in posts.items():
        if p_info.get("user_id") == user_id:
            return True
    return False

def get_cooldown_left(user_id):
    if is_owner(user_id):
        return 0
    cooldowns = load_data(COOLDOWN_FILE)
    str_id = str(user_id)
    if str_id in cooldowns:
        last_post_time = cooldowns[str_id]
        elapsed = time.time() - last_post_time
        if elapsed < COOLDOWN_TIME:
            return int(COOLDOWN_TIME - elapsed)
    return 0

def set_cooldown(user_id):
    if is_owner(user_id):
        return
    cooldowns = load_data(COOLDOWN_FILE)
    cooldowns[str(user_id)] = time.time()
    save_data(COOLDOWN_FILE, cooldowns)

def reset_cooldown(user_id):
    cooldowns = load_data(COOLDOWN_FILE)
    str_id = str(user_id)
    if str_id in cooldowns:
        del cooldowns[str_id]
        save_data(COOLDOWN_FILE, cooldowns)

def save_to_history(user_id, username, text):
    history = load_data(HISTORY_FILE)
    if not isinstance(history, list):
        history = []
    
    post_entry = {
        "timestamp": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "user_id": user_id,
        "username": username or "Без username",
        "text": text[:300]
    }
    
    history.append(post_entry)
    if len(history) > 50:
        history = history[-50:]
        
    save_data(HISTORY_FILE, history)

def format_time(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours} ч. {minutes} мин."
    else:
        return f"{minutes} мин."

def parse_post_data(text):
    platform = "Не указана"
    payment = "Не указана"
    
    m_plat = re.search(r"➤\s*Платформа:\s*(.+)", text, re.IGNORECASE)
    if m_plat:
        platform = m_plat.group(1).strip()
        
    m_pay = re.search(r"➤\s*Получите оплату:\s*(.+)", text, re.IGNORECASE)
    if m_pay:
        payment = m_pay.group(1).strip()
        
    return platform, payment

# --- ЛОГИКА ЗАКРЫТИЯ ПОСТА В КАНАЛЕ ---

def close_post_in_channel(message_id):
    CLOSED_CARD = (
        "🔒 **[ЗАДАНИЕ ЗАКРЫТО]**\n\n"
        "━━━━━⬍━━━━━\n"
        "⛔ *Набор на это задание завершён.*\n"
        "🔔 Включите уведомления в канале, чтобы не пропустить новые предложения!\n\n"
        f"🤖 *Хотите такого же бота в свой канал? Пишите:* {MY_USERNAME}"
    )

    try:
        bot.edit_message_text(
            text=CLOSED_CARD,
            chat_id=CHANNEL_ID,
            message_id=message_id,
            parse_mode="Markdown",
            reply_markup=None
        )
        return True
    except Exception:
        try:
            bot.delete_message(chat_id=CHANNEL_ID, message_id=message_id)
            bot.send_message(
                chat_id=CHANNEL_ID,
                text=CLOSED_CARD,
                parse_mode="Markdown"
            )
            return True
        except Exception:
            try:
                bot.edit_message_caption(
                    caption=CLOSED_CARD,
                    chat_id=CHANNEL_ID,
                    message_id=message_id,
                    parse_mode="Markdown",
                    reply_markup=None
                )
                return True
            except:
                return False

# --- ФОНОВЫЙ ПОТОК (ПРОВЕРКА ПОДПИСОК) ---

def check_expiring_subscriptions():
    while True:
        try:
            users = load_data(DB_FILE)
            notified = load_data(NOTIFIED_FILE)
            now = time.time()
            
            for u_id, u_info in list(users.items()):
                exp_time = u_info.get("expire_time", 0) if isinstance(u_info, dict) else u_info
                time_left = exp_time - now
                if 0 < time_left <= 86400 and u_id not in notified:
                    try:
                        bot.send_message(
                            int(u_id), 
                            "⚠️ **Внимание!** Ваша подписка закончится через 24 часа."
                        )
                        notified[u_id] = True
                        save_data(NOTIFIED_FILE, notified)
                    except ApiTelegramException as e:
                        if e.error_code in [403, 400]:
                            notified[u_id] = True
                            save_data(NOTIFIED_FILE, notified)
                    except Exception as e:
                        print(f"Ошибка предупреждения {u_id}: {e}")
        except Exception as e:
            print(f"Ошибка проверки подписок: {e}")
            
        time.sleep(3600)

# --- КЛАВИАТУРЫ И МЕНЮ ---

def get_main_menu_keyboard(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(text="📋 Шаблон поста", callback_data="get_template"),
        types.InlineKeyboardButton(text="📖 Правила", callback_data="show_rules"),
        types.InlineKeyboardButton(text="⏳ Мой профиль / КД", callback_data="my_profile")
    )
    markup.add(types.InlineKeyboardButton(text="🤖 Хочу такого же бота себе", url=f"https://t.me/{MY_USERNAME.replace('@', '')}"))
    
    if is_owner(user_id):
        markup.add(types.InlineKeyboardButton(text="🛠 Админ-панель", callback_data="open_admin_help"))
    return markup

def get_back_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="main_menu"))
    return markup

def get_admin_help_text():
    return (
        "🛠 **ПАНЕЛЬ УПРАВЛЕНИЯ ВЛАДЕЛЬЦА:**\n\n"
        "🟢 `/ad ID ДНИ ЛИМИТ_ПОСТОВ` — Выдать доступ\n"
        "🔴 `/del ID` — Забрать доступ\n"
        "📋 `/list` — Список активных подписок\n"
        "⚡ `/uncd ID` — Сбросить кулдаун юзеру\n"
        "📜 `/history` — Посмотреть последние посты\n"
    )

# --- АДМИН-КОМАНДЫ ---

@bot.message_handler(commands=['adminhelp'])
def admin_help_cmd(message):
    if not is_owner(message.from_user.id):
        return
    bot.reply_to(message, get_admin_help_text(), parse_mode="Markdown")

@bot.message_handler(commands=['ad', 'add'])
def add_user(message):
    if not is_owner(message.from_user.id):
        return
    try:
        args = message.text.split()
        target_id = str(args[1])
        days = int(args[2])
        limit = int(args[3]) if len(args) > 3 else 1

        users = load_data(DB_FILE)
        users[target_id] = {
            "expire_time": time.time() + (days * 86400),
            "daily_limit": limit
        }
        save_data(DB_FILE, users)
        
        notified = load_data(NOTIFIED_FILE)
        if target_id in notified:
            del notified[target_id]
            save_data(NOTIFIED_FILE, notified)

        bot.reply_to(message, f"✅ Доступ для ID `{target_id}` выдан на {days} дн. с лимитом {limit} постов/день!", parse_mode="Markdown")
        try:
            bot.send_message(int(target_id), f"🎉 **Вам выдан доступ на {days} дн.!**\nЛимит: {limit} постов в день.\nНажмите /start, чтобы начать.")
        except:
            pass
    except Exception:
        bot.reply_to(message, "❌ Формат: `/ad ID ДНИ ЛИМИТ_ПОСТОВ`", parse_mode="Markdown")

@bot.message_handler(commands=['del'])
def del_user(message):
    if not is_owner(message.from_user.id):
        return
    try:
        target_id = str(message.text.split()[1])
        users = load_data(DB_FILE)
        if target_id in users:
            del users[target_id]
            save_data(DB_FILE, users)
            bot.reply_to(message, f"⛔ Доступ для ID {target_id} аннулирован.")
        else:
            bot.reply_to(message, "Юзер не найден в базе.")
    except:
        bot.reply_to(message, "Формат: /del ID")

@bot.message_handler(commands=['list'])
def list_users(message):
    if not is_owner(message.from_user.id):
        return
    users = load_data(DB_FILE)
    if not users:
        bot.reply_to(message, "Список платных подписок пуст.")
        return
    text = "📋 **Активные подписки:**\n\n"
    now = time.time()
    for u_id, u_info in list(users.items()):
        exp_time = u_info.get("expire_time", 0) if isinstance(u_info, dict) else u_info
        limit = u_info.get("daily_limit", 1) if isinstance(u_info, dict) else 1
        left_days = round((exp_time - now) / 86400, 1)
        if left_days > 0:
            text += f"• ID: `{u_id}` — осталось {left_days} дн. | Лимит: {limit} пост/день\n"
        else:
            del users[u_id]
            save_data(DB_FILE, users)
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['uncd', 'uncooldown'])
def reset_cooldown_command(message):
    if not is_owner(message.from_user.id):
        return
    try:
        target_id = str(message.text.split()[1])
        reset_cooldown(target_id)
        bot.reply_to(message, f"⚡ Кулдаун для ID `{target_id}` успешно сброшен!", parse_mode="Markdown")
    except Exception:
        bot.reply_to(message, "❌ Формат: /uncd ID", parse_mode="Markdown")

@bot.message_handler(commands=['history'])
def show_history(message):
    if not is_owner(message.from_user.id):
        return
    history = load_data(HISTORY_FILE)
    if not history:
        bot.reply_to(message, "История постов пуста.")
        return
    text = "📜 **История последних публикаций:**\n\n"
    for item in history[-10:]:
        user_str = f"@{item['username']}" if item['username'] != "Без username" else f"ID {item['user_id']}"
        text += f"🕒 [{item['timestamp']}] {user_str}\n💬 {item['text'][:80]}...\n---\n"
    bot.reply_to(message, text)

# --- РУЧНОЕ ЗАКРЫТИЕ ПОСТА ---

@bot.message_handler(commands=['close', 'clouse'])
def close_user_post(message):
    user_id = message.from_user.id
    posts_data = load_data(POSTS_FILE)
    
    target_post_id = None
    
    if message.reply_to_message:
        for p_id, p_info in posts_data.items():
            if p_info.get("confirm_msg_id") == message.reply_to_message.message_id:
                target_post_id = p_id
                break
                
    if not target_post_id:
        args = message.text.split()
        if len(args) > 1 and args[1].isdigit():
            target_post_id = args[1]

    if not target_post_id:
        user_posts = [p_id for p_id, info in posts_data.items() if info.get("user_id") == user_id]
        if user_posts:
            target_post_id = user_posts[-1]

    if not target_post_id:
        bot.reply_to(message, "❌ Активный пост не найден.\nДля закрытия поста ответьте командой `/close` на сообщение подтверждения или укажите ID: `/close ID`", parse_mode="Markdown")
        return

    if target_post_id in posts_data:
        post_info = posts_data[target_post_id]
        if post_info["user_id"] != user_id and not is_owner(user_id):
            bot.reply_to(message, "⛔ Вы не можете закрыть чужой пост.")
            return

        close_post_in_channel(int(target_post_id))

        del posts_data[target_post_id]
        save_data(POSTS_FILE, posts_data)

        bot.reply_to(message, "✅ **Задание успешно закрыто!**\nТеперь вы можете выкладывать следующее задание (при соблюдении КД).", parse_mode="Markdown")
            
    else:
        if is_owner(user_id):
            res = close_post_in_channel(int(target_post_id))
            if res:
                bot.reply_to(message, f"✅ Старый пост `{target_post_id}` успешно закрыт в канале!", parse_mode="Markdown")
            else:
                bot.reply_to(message, f"❌ Не удалось закрыть пост `{target_post_id}`. Проверь ID.", parse_mode="Markdown")
        else:
            bot.reply_to(message, "❌ Пост не найден в списке активных.")

# --- ОБРАБОТКА CALLBACK-КНОПОК ---

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    
    if call.data == "main_menu":
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="👋 Привет! Добро пожаловать в бот автопубликаций.\nВыберите нужный раздел ниже:",
            reply_markup=get_main_menu_keyboard(user_id)
        )

    elif call.data == "get_template":
        bot.answer_callback_query(call.id, "Шаблон готов к копированию!")
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"📋 **Нажми на текст ниже, чтобы скопировать его:**\n\n<code>{TEMPLATE_TEXT}</code>",
            parse_mode="HTML",
            reply_markup=get_back_keyboard()
        )

    elif call.data == "show_rules":
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=RULES_TEXT,
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )

    elif call.data == "my_profile":
        bot.answer_callback_query(call.id)
        if is_owner(user_id):
            prof_text = "👑 У вас статус **Владельца** (без КД, без лимитов и ограничений)."
        elif is_user_active(user_id):
            users = load_data(DB_FILE)
            u_data = users[str(user_id)]
            exp_time = u_data.get("expire_time", 0) if isinstance(u_data, dict) else u_data
            limit = u_data.get("daily_limit", 1) if isinstance(u_data, dict) else 1
            left = round((exp_time - time.time()) / 86400, 1)
            cd = get_cooldown_left(user_id)
            cd_str = format_time(cd) if cd > 0 else "Отсутствует"
            has_post = "Да (нужно закрыть через /close)" if has_active_unclosed_post(user_id) else "Нет"
            
            prof_text = (
                f"👤 **Ваш профиль:**\n\n"
                f"• Подписка активна ещё: ~**{left} дн.**\n"
                f"• Дневной лимит постов: **{limit}**\n"
                f"• Текущий кулдаун: **{cd_str}**\n"
                f"• Активное открытое задание: **{has_post}**"
            )
        else:
            prof_text = "⛔ У вас нет активной подписки."

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=prof_text,
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )

    elif call.data == "open_admin_help":
        if is_owner(user_id):
            bot.answer_callback_query(call.id)
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=get_admin_help_text(),
                parse_mode="Markdown",
                reply_markup=get_back_keyboard()
            )

# --- ОБРАБОТКА СТАРТА ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id

    if is_user_active(user_id):
        bot.reply_to(
            message, 
            "👋 Привет! Добро пожаловать в бот автопубликаций.\nВыберите нужный раздел ниже:", 
            reply_markup=get_main_menu_keyboard(user_id)
        )
    else:
        bot.reply_to(
            message, 
            f"⛔ У вас нет доступа к публикации.\nВаш Telegram ID: `{user_id}`\n\nДля покупки доступа напишите администратору.", 
            parse_mode="Markdown"
        )

# --- ПУБЛИКАЦИЯ ПОСТОВ ---

@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'animation'])
def handle_post(message):
    if message.text and message.text.startswith('/'):
        return

    user_id = message.from_user.id
    
    if not is_user_active(user_id):
        bot.reply_to(message, f"⛔ Публикация отклонена. Подписка истекла или не куплена.\nВаш ID: `{user_id}`", parse_mode="Markdown")
        return

    # Проверка на неоконченное задание
    if has_active_unclosed_post(user_id):
        bot.reply_to(
            message, 
            "⚠️ **У вас уже есть открытое задание!**\n\n"
            "Вы не можете опубликовать новое задание, пока не закроете старое.\n"
            "Чтобы закрыть предыдущее задание, отправьте команду `/close`.", 
            parse_mode="Markdown"
        )
        return

    # Проверка дневного лимита
    if not can_user_post_today(user_id):
        bot.reply_to(message, "🚫 **Вы исчерпали свой суточный лимит постов!**\nПопробуйте снова завтра.")
        return

    # Проверка кулдауна
    cooldown_left = get_cooldown_left(user_id)
    if cooldown_left > 0:
        time_str = format_time(cooldown_left)
        bot.reply_to(message, f"⏳ **Кулдаун!**\nВы сможете опубликовать следующий пост через **{time_str}**.")
        return

    post_text = message.text or message.caption or ""
    
    has_required = ("Новое задание!" in post_text) and ("➤ Платформа:" in post_text) and ("➤ Получите оплату:" in post_text) and ("➤ Описание:" in post_text)

    if not has_required:
        bot.reply_to(
            message, 
            "❌ **Неправильный шаблон!**\n\n"
            "👇 **Скопируйте актуальный шаблон ниже:**\n\n" + f"<code>{TEMPLATE_TEXT}</code>", 
            parse_mode="HTML"
        )
        return

    try:
        user = message.from_user
        username = user.username
        platform, payment = parse_post_data(post_text)

        # Формирование готового текста сообщения автору
        start_msg = f"Привет, я с канала {CHANNEL_USERNAME} за заданием на {platform} за {payment}"
        encoded_msg = urllib.parse.quote(start_msg)

        if username:
            author_link = f"https://t.me/{username}?text={encoded_msg}"
        else:
            author_link = f"tg://user?id={user_id}"

        published_msg = bot.copy_message(
            chat_id=CHANNEL_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="Взять задание 💬", url=author_link))
        
        bot.edit_message_reply_markup(
            chat_id=CHANNEL_ID,
            message_id=published_msg.message_id,
            reply_markup=markup
        )

        set_cooldown(user_id)
        increment_daily_post_count(user_id)
        save_to_history(user_id, username, post_text)
        
        confirm_msg = bot.reply_to(
            message, 
            "🚀 **Задание успешно выложено в канал!**\n\n"
            "📌 **Важно:** Пост будет активен, пока вы его не закроете.\n"
            "Чтобы закрыть задание и дать возможность выкладывать новые посты, ответьте командой `/close` на это сообщение.",
            parse_mode="Markdown"
        )

        posts_data = load_data(POSTS_FILE)
        posts_data[str(published_msg.message_id)] = {
            "user_id": user_id,
            "created_at": time.time(),
            "confirm_msg_id": confirm_msg.message_id,
            "original_text": post_text
        }
        save_data(POSTS_FILE, posts_data)

        if not is_owner(user_id):
            user_tag = f"@{username}" if username else f"ID {user_id}"
            admin_log = f"📩 **Новый пост в канале!**\n👤 Автор: {user_tag}\n📝 Текст:\n{post_text}"
            for admin_id in OWNER_ID:
                try:
                    bot.send_message(admin_id, admin_log, parse_mode="Markdown")
                except:
                    pass

    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка публикации: {e}")

# --- ЗАПУСК ПОТОКОВ И ПОЛЛИНГА ---

threading.Thread(target=check_expiring_subscriptions, daemon=True).start()

if __name__ == '__main__':
    while True:
        try:
            print("Бот запущен и готов к работе...")
            bot.polling(none_stop=True, timeout=20, long_polling_timeout=20, skip_pending=True)
        except Exception as e:
            print(f"Ошибка сети: {e}. Переподключение...")
            time.sleep(3)
