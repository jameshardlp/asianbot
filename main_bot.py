# ===== main_bot.py =====
"""
Основной скрипт бота
"""
import asyncio
import os
import sys
import json
import time
import random
import hashlib
import logging
import base64
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any, List
from collections import defaultdict

import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, PreCheckoutQuery, LabeledPrice, WebAppInfo
from aiogram.exceptions import TelegramAPIError
from aiohttp import web

# Импорты из модулей
from deepseek_parser import (
    generate_caption_with_validation, 
    get_streamer_media, 
    get_streamer_photo,
    get_streamer_for_post, 
    validate_caption, 
    clean_text, 
    truncate_by_sentences,
    STREAMER_INFO, 
    ASIAN_QUERIES, 
    is_photo_valid, 
    search_bing, 
    search_google_direct,
    search_yandex, 
    search_pexels, 
    search_youtube_clip, 
    add_to_last_posts, 
    is_similar, 
    clear_prompt_cache, 
    check_date_in_content,
    get_random_photo,
    analyze_photo_for_comment
)
from payment_system import (
    broadcast_prices, 
    save_broadcast_price, 
    load_broadcast_price,
    create_freekassa_payment_link, 
    check_freekassa_payment_status,
    create_aurapay_payment, 
    check_aurapay_payment_status,
    aurapay_webhook, 
    freekassa_webhook,
    broadcast_data, 
    pending_broadcasts, 
    AURAPAY_MINIAPP_URL
)

# ===== НАСТРОЙКА ЛОГИРОВАНИЯ =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===== КОНФИГУРАЦИЯ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_ID = int(os.getenv("OWNER_ID", 0))
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
STARS_CHANNEL_ID = -1003893727881
FREEKASSA_SHOP_ID = os.getenv("FREEKASSA_SHOP_ID", "")
FREEKASSA_SECRET1 = os.getenv("FREEKASSA_SECRET1", "")

USERS_FILE = "users.json"
HISTORY_FILE = "history.json"
SCHEDULE_FILE = "schedule.json"
USAGE_FILE = "usage.json"

# ===== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ =====
is_sending = False
last_post_time = time.time()
MIN_POST_INTERVAL = 2 * 60 * 60
SEND_DELAY = 3.0  # Задержка 3 секунды между сообщениями
users = []
history = []
schedule_data = {}

# Хранилище для отслеживания последнего времени отправки пользователю
last_user_message_time = defaultdict(float)
# Блокировка для каждого пользователя, чтобы предотвратить одновременные запросы
user_locks = defaultdict(asyncio.Lock)

# ===== ИНИЦИАЛИЗАЦИЯ БОТА =====
if not BOT_TOKEN:
    logger.error("BOT_TOKEN не задан")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===== РАБОТА С ПОЛЬЗОВАТЕЛЯМИ =====

def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_users(users_list):
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(users_list, f)
    except Exception as e:
        logger.error(f"Ошибка сохранения пользователей: {e}")

def load_history():
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_history(history_list):
    try:
        if len(history_list) > 100:
            history_list = history_list[-100:]
        with open(HISTORY_FILE, "w") as f:
            json.dump(history_list, f)
    except Exception as e:
        logger.error(f"Ошибка сохранения истории: {e}")

def load_schedule():
    try:
        with open(SCHEDULE_FILE, "r") as f:
            data = json.load(f)
            if not data or not data.get("times"):
                return {"times": ["12:00", "21:00"]}
            return data
    except:
        return {"times": ["12:00", "21:00"]}

def save_schedule(schedule_data):
    try:
        with open(SCHEDULE_FILE, "w") as f:
            json.dump(schedule_data, f)
        return True
    except:
        return False

def load_usage() -> dict:
    try:
        with open(USAGE_FILE, "r") as f:
            data = json.load(f)
            current_date = datetime.now().strftime("%Y-%m-%d")
            for user_id in list(data.keys()):
                if data[user_id].get("date") != current_date:
                    del data[user_id]
            return data
    except:
        return {}

def save_usage(usage_data: dict):
    try:
        with open(USAGE_FILE, "w") as f:
            json.dump(usage_data, f)
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения статистики: {e}")
        return False

# ===== ИНИЦИАЛИЗАЦИЯ ДАННЫХ =====
users = load_users()
history = load_history()
schedule_data = load_schedule()

# ===== ФУНКЦИИ ОТПРАВКИ С ЗАДЕРЖКОЙ =====

async def send_post_with_retry(chat_id, photo_url=None, caption=None, media_type='photo', clip_url=None, max_retries=3):
    """Отправляет пост с повторными попытками при ошибках и задержкой между сообщениями"""
    
    # Проверяем, не слишком ли часто отправляем этому пользователю
    current_time = time.time()
    last_time = last_user_message_time.get(chat_id, 0)
    time_since_last = current_time - last_time
    
    if time_since_last < SEND_DELAY:
        wait_time = SEND_DELAY - time_since_last
        logger.info(f"⏳ Ожидание {wait_time:.1f} сек перед отправкой пользователю {chat_id}")
        await asyncio.sleep(wait_time)
    
    # Обновляем время последней отправки
    last_user_message_time[chat_id] = time.time()
    
    for attempt in range(max_retries):
        try:
            if not photo_url and not caption:
                return False
            
            if not photo_url:
                if caption:
                    await bot.send_message(chat_id=chat_id, text=caption)
                return True
            
            if not caption:
                caption, _ = generate_caption_with_validation()
                caption = clean_text(caption)
                caption = truncate_by_sentences(caption, max_length=1023)
            
            if media_type == 'clip':
                text = f"{caption}\n\n{photo_url}"
                await bot.send_message(chat_id=chat_id, text=text)
            else:
                if len(caption) > 1024:
                    caption = truncate_by_sentences(caption, max_length=1023)
                await bot.send_photo(chat_id=chat_id, photo=photo_url, caption=caption)
            
            return True
            
        except TelegramAPIError as e:
            error_str = str(e).lower()
            
            # Обработка ошибки "Too Many Requests"
            if "too many requests" in error_str or "retry after" in error_str:
                import re
                match = re.search(r"retry after (\d+)", str(e))
                if match:
                    wait_time = int(match.group(1)) + 1
                else:
                    wait_time = 5 * (attempt + 1)
                
                logger.warning(f"⚠️ Лимит превышен для {chat_id}. Ожидание {wait_time} сек. Попытка {attempt+1}/{max_retries}")
                await asyncio.sleep(wait_time)
                continue
                
            elif "forbidden" in error_str or "chat not found" in error_str:
                users_list = load_users()
                if chat_id in users_list:
                    users_list.remove(chat_id)
                    save_users(users_list)
                    logger.info(f"👤 Пользователь {chat_id} удалён")
                return False
            else:
                logger.error(f"❌ Ошибка Telegram при отправке в {chat_id}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в {chat_id}: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
                continue
            return False
    
    return False

# ===== ОБНОВЛЕННАЯ ФУНКЦИЯ ОТПРАВКИ ПОСТА =====

async def send_post(chat_id, photo_url=None, caption=None, media_type='photo', clip_url=None):
    """Отправляет пост с задержкой 3 секунды между сообщениями"""
    return await send_post_with_retry(chat_id, photo_url, caption, media_type, clip_url)

# ===== ДЕКОРАТОР ДЛЯ ОГРАНИЧЕНИЯ ЧАСТОТЫ КОМАНД =====

def rate_limit(seconds: int = 3):
    """Декоратор для ограничения частоты вызова команд"""
    def decorator(func):
        async def wrapper(message: Message, *args, **kwargs):
            user_id = message.from_user.id
            
            # Используем блокировку для пользователя
            async with user_locks[user_id]:
                current_time = time.time()
                last_time = last_user_message_time.get(user_id, 0)
                
                if current_time - last_time < seconds:
                    # Не отвечаем, просто игнорируем
                    logger.info(f"⏭️ Игнорируем частый запрос от {user_id} ({(current_time - last_time):.1f} сек)")
                    return
                
                last_user_message_time[user_id] = current_time
                return await func(message, *args, **kwargs)
        return wrapper
    return decorator

# ===== ОБНОВЛЕННЫЕ КОМАНДЫ С rate_limit =====

@dp.message(Command("start"))
async def start(msg: Message):
    try:
        chat_id = msg.chat.id
        user_id = msg.from_user.id
        
        if chat_id not in users:
            users.append(chat_id)
            save_users(users)
            logger.info(f"👤 Добавлен пользователь: {chat_id}")
        
        current_schedule = load_schedule()
        times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
        stars_price = broadcast_prices.get("stars", 100)
        rub_price = broadcast_prices.get("rub", 100)
        
        channel_status = "❌ не найден"
        channel_id = CHANNEL_ID
        if channel_id and channel_id.strip():
            channel_status = f"✅ {channel_id}"
        else:
            found_channel = await get_channel_id()
            if found_channel:
                channel_status = f"✅ {found_channel} (авто-найден)"
        
        await msg.answer(
            f"✅ Бот активирован!\n\n"
            f"📸 Посты про стримеров и Азию\n"
            f"⏰ Расписание: {times}\n"
            f"📢 Канал: {channel_status}\n\n"
            f"🔄 /photo - получить пост сейчас (до 10 раз в день)\n"
            f"⏰ /schedule - изменить расписание (только для владельца)\n"
            f"📢 /broadcast - отправить сообщение всем (⭐ {stars_price} звёзд или 💳 {rub_price} RUB)\n"
            f"🛑 /stop - отписаться\n"
            f"📊 /status - статус бота"
        )
        
    except Exception as e:
        logger.error(f"Ошибка в команде start: {e}")

@dp.message(Command("photo"))
@rate_limit(seconds=3)  # Ограничение 3 секунды между вызовами
async def photo_command(message: Message):
    try:
        user_id = message.from_user.id
        chat_id = message.chat.id
        
        if chat_id not in users:
            await message.answer("⚠️ Бот не активирован. Напишите /start")
            return
        
        can_use, used_count, limit = can_use_photo(user_id)
        
        if not can_use:
            await message.answer(
                f"⛔ Вы исчерпали лимит на сегодня ({limit} запросов).\n"
                f"🔄 Лимит обновится завтра."
            )
            return
        
        await create_post_with_photo(str(chat_id), user_id, skip_moderation=True)
        
        new_count, limit = increment_photo_usage(user_id)
        remaining = limit - new_count
        
        await message.answer(
            f"✅ Пост отправлен!\n"
            f"📊 Осталось запросов на сегодня: {remaining} из {limit}"
        )
    except Exception as e:
        logger.error(f"Ошибка в команде photo: {e}")

@dp.message(Command("post"))
@rate_limit(seconds=3)
async def post_command(message: Message):
    try:
        if message.from_user.id != OWNER_ID:
            await message.answer("⛔ Доступ запрещён")
            return
        
        channel_id = CHANNEL_ID
        if channel_id and channel_id.strip():
            await create_post_with_photo(str(channel_id), message.from_user.id, skip_moderation=True)
            await message.answer("✅ Пост создан для канала!")
        else:
            channel_id = await get_channel_id()
            if channel_id:
                await create_post_with_photo(str(channel_id), message.from_user.id, skip_moderation=True)
                await message.answer(f"✅ Пост создан для канала {channel_id}!")
            else:
                await message.answer("⚠️ Канал не найден. Укажите CHANNEL_ID в переменных окружения.")
        
        await create_post_with_photo(str(message.chat.id), message.from_user.id, skip_moderation=True)
        await message.answer("✅ Пост создан в ЛС!")
    except Exception as e:
        logger.error(f"Ошибка в команде post: {e}")

@dp.message(Command("stop"))
@rate_limit(seconds=3)
async def stop(msg: Message):
    try:
        chat_id = msg.chat.id
        if chat_id in users:
            users.remove(chat_id)
            save_users(users)
            await msg.answer("🛑 Вы отписаны от рассылки")
        else:
            await msg.answer("ℹ️ Вы и так не подписаны")
    except Exception as e:
        logger.error(f"Ошибка в команде stop: {e}")

@dp.message(Command("schedule"))
@rate_limit(seconds=3)
async def schedule(msg: Message):
    try:
        if msg.from_user.id != OWNER_ID:
            await msg.answer("⛔ Доступ запрещён")
            return
        
        args = msg.text.replace("/schedule", "").strip()
        if not args:
            current_schedule = load_schedule()
            times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
            await msg.answer(f"📅 Текущее расписание: {times}")
            return
        
        new_times = []
        for time_str in args.split(','):
            time_str = time_str.strip()
            try:
                hour, minute = map(int, time_str.split(':'))
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    new_times.append(f"{hour:02d}:{minute:02d}")
            except:
                continue
        
        if new_times:
            schedule_data["times"] = new_times
            save_schedule(schedule_data)
            await msg.answer(f"✅ Расписание обновлено: {', '.join(new_times)}")
        else:
            await msg.answer("❌ Неверный формат")
    except Exception as e:
        logger.error(f"Ошибка в команде schedule: {e}")

@dp.message(Command("price"))
@rate_limit(seconds=3)
async def set_price(message: Message):
    try:
        if message.from_user.id != OWNER_ID:
            await message.answer("⛔ Доступ запрещён")
            return
        
        args = message.text.replace("/price", "").strip()
        if not args:
            stars_price = broadcast_prices.get("stars", 100)
            rub_price = broadcast_prices.get("rub", 100)
            await message.answer(
                f"💰 Текущие цены:\n"
                f"⭐ Звёзды: {stars_price}\n"
                f"💳 Рубли: {rub_price} RUB"
            )
            return
        
        parts = args.split()
        if len(parts) != 2:
            await message.answer("❌ Использование: /price stars 10 или /price rub 100")
            return
        
        currency, value = parts[0].lower(), parts[1]
        try:
            price = int(value)
            if price < 1:
                await message.answer("❌ Цена должна быть > 0")
                return
            
            if currency == "stars":
                broadcast_prices["stars"] = price
                save_broadcast_price(broadcast_prices)
                await message.answer(f"✅ Цена в звёздах: {price} ⭐")
            elif currency == "rub":
                broadcast_prices["rub"] = price
                save_broadcast_price(broadcast_prices)
                await message.answer(f"✅ Цена в рублях: {price} RUB")
            else:
                await message.answer("❌ Укажите stars или rub")
        except ValueError:
            await message.answer("❌ Введите число")
    except Exception as e:
        logger.error(f"Ошибка в команде price: {e}")

@dp.message(Command("status"))
@rate_limit(seconds=3)
async def status(msg: Message):
    try:
        users_list = load_users()
        current_schedule = load_schedule()
        times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
        channel_id = CHANNEL_ID or await get_channel_id()
        
        await msg.answer(
            f"📊 Статус бота:\n"
            f"• Подписчиков: {len(users_list)}\n"
            f"• Фото в истории: {len(history)}\n"
            f"• Расписание: {times}\n"
            f"• Канал: {'✅ ' + channel_id if channel_id else '❌ не найден'}"
        )
    except Exception as e:
        logger.error(f"Ошибка в команде status: {e}")

# ===== ОБНОВЛЕННАЯ ФУНКЦИЯ ОТПРАВКИ ВСЕМ ПОЛЬЗОВАТЕЛЯМ =====

async def send_to_all_users():
    try:
        users_list = load_users()
        if not users_list:
            logger.warning("Нет пользователей для отправки")
            return
        
        logger.info(f"Отправка поста {len(users_list)} пользователям...")
        
        caption, streamer_key = generate_caption_with_validation()
        if not caption:
            return
        
        # Получаем медиа
        media_url = None
        media_type = 'photo'
        clip_url = None
        
        if streamer_key:
            streamer_names = {
                'voodoosh': 'Вудуш', 'praden': 'Праден', 'bratishkinoff': 'Братишкин',
                'sasavot': 'Сасавот', 'alina_rin': 'Алина Рин', 'lasqa': 'Ласка',
                'arrowwoods': 'Аравудус', 'evelone': 'Эвелон', 'buster': 'Бустер',
            }
            streamer_display = streamer_names.get(streamer_key, streamer_key)
            media_url, media_type = get_streamer_media(streamer_key, streamer_display)
            if media_type == 'clip':
                clip_url = media_url
        
        if not media_url:
            photo_url = await get_random_photo("streamer", None)
            if photo_url:
                media_url = photo_url
        
        if not media_url:
            photo_url = await get_random_photo("asia", None)
            if photo_url:
                media_url = photo_url
        
        if not media_url:
            logger.error("Не удалось найти медиа")
            return
        
        # Отправляем в канал (если он есть)
        channel_id = None
        if CHANNEL_ID and CHANNEL_ID.strip():
            channel_id = CHANNEL_ID
        else:
            channel_id = await get_channel_id()
        
        if channel_id:
            try:
                logger.info(f"📢 Отправка в канал {channel_id}")
                await send_post_with_retry(channel_id, media_url, caption, media_type, clip_url)
                logger.info(f"✅ Пост отправлен в канал {channel_id}")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки в канал: {e}")
        else:
            logger.info("ℹ️ Канал не найден, отправка только пользователям")
        
        # Отправляем всем пользователям с задержкой 3 секунды
        sent_count = 0
        failed_count = 0
        
        # Сортируем пользователей для равномерной отправки
        random.shuffle(users_list)
        
        for i, chat_id in enumerate(users_list):
            try:
                logger.info(f"📨 Отправка пользователю {i+1}/{len(users_list)}: {chat_id}")
                await send_post_with_retry(chat_id, media_url, caption, media_type, clip_url)
                sent_count += 1
                
                # Задержка 3 секунды между отправками (кроме последней)
                if i < len(users_list) - 1:
                    await asyncio.sleep(SEND_DELAY)
                    
            except Exception as e:
                logger.error(f"Ошибка отправки пользователю {chat_id}: {e}")
                failed_count += 1
        
        logger.info(f"✅ Пост отправлен: {sent_count} пользователям, {failed_count} ошибок")
    except Exception as e:
        logger.error(f"Ошибка в send_to_all_users: {e}")

# ===== ОСТАЛЬНЫЕ ФУНКЦИИ (без изменений) =====

async def get_channel_id() -> Optional[str]:
    if CHANNEL_ID and CHANNEL_ID.strip():
        return CHANNEL_ID.strip()
    try:
        me = await bot.get_me()
        logger.info(f"Бот: @{me.username}")
        try:
            updates = await asyncio.wait_for(
                bot.get_updates(offset=-1, limit=10),
                timeout=10
            )
            for update in updates:
                if update.channel_post:
                    chat_id = update.channel_post.chat.id
                    try:
                        chat_member = await bot.get_chat_member(chat_id, bot.id)
                        if chat_member.status in ["administrator", "creator"]:
                            logger.info(f"Найден канал: {chat_id}")
                            return str(chat_id)
                    except:
                        pass
        except asyncio.TimeoutError:
            logger.warning("Таймаут получения обновлений")
        except Exception as e:
            logger.error(f"Ошибка получения обновлений: {e}")
    except Exception as e:
        logger.error(f"Ошибка поиска канала: {e}")
    return None

async def check_user_can_use_command(message: Message) -> bool:
    try:
        chat_type = message.chat.type
        if chat_type == "private":
            return True
        if chat_type in ["group", "supergroup"]:
            return await is_user_admin(message.chat.id, message.from_user.id)
        return False
    except Exception as e:
        logger.error(f"Ошибка проверки прав: {e}")
        return False

async def is_user_admin(chat_id: int, user_id: int) -> bool:
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ["administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка проверки админа: {e}")
        return False

def encode_image_to_base64_url(image_url: str) -> str:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(image_url, headers=headers, timeout=10)
        if response.status_code == 200:
            return base64.b64encode(response.content).decode('utf-8')
        return None
    except Exception as e:
        logger.error(f"Ошибка загрузки картинки: {e}")
        return None

def can_use_photo(user_id: int) -> Tuple[bool, int, int]:
    if user_id == OWNER_ID:
        return True, 0, float('inf')
    
    usage_data = load_usage()
    current_date = datetime.now().strftime("%Y-%m-%d")
    user_key = str(user_id)
    limit = 10
    
    if user_key not in usage_data:
        return True, 0, limit
    
    user_usage = usage_data.get(user_key, {})
    last_date = user_usage.get("date")
    count = user_usage.get("count", 0)
    
    if last_date != current_date:
        return True, 0, limit
    
    if count >= limit:
        return False, count, limit
    
    return True, count, limit

def increment_photo_usage(user_id: int) -> Tuple[int, int]:
    if user_id == OWNER_ID:
        return 0, float('inf')
    
    usage_data = load_usage()
    current_date = datetime.now().strftime("%Y-%m-%d")
    user_key = str(user_id)
    limit = 10
    
    if user_key not in usage_data:
        usage_data[user_key] = {"date": current_date, "count": 0}
    
    user_usage = usage_data[user_key]
    
    if user_usage.get("date") != current_date:
        user_usage["date"] = current_date
        user_usage["count"] = 0
    
    user_usage["count"] += 1
    
    save_usage(usage_data)
    
    return user_usage["count"], limit

async def create_post_with_photo(chat_id, user_id=0, skip_moderation=False, style="streamer"):
    try:
        caption, streamer_key = generate_caption_with_validation()
        if not caption:
            return False
        
        media_url = None
        media_type = 'photo'
        clip_url = None
        
        if streamer_key:
            streamer_names = {
                'voodoosh': 'Вудуш', 'praden': 'Праден', 'bratishkinoff': 'Братишкин',
                'sasavot': 'Сасавот', 'alina_rin': 'Алина Рин', 'lasqa': 'Ласка',
                'arrowwoods': 'Аравудус', 'evelone': 'Эвелон', 'buster': 'Бустер',
            }
            streamer_display = streamer_names.get(streamer_key, streamer_key)
            media_url, media_type = get_streamer_media(streamer_key, streamer_display)
            if media_type == 'clip':
                clip_url = media_url
        
        if not media_url:
            photo_url = await get_random_photo("streamer", None)
            if photo_url:
                media_url = photo_url
        
        if not media_url:
            photo_url = await get_random_photo("asia", None)
            if photo_url:
                media_url = photo_url
        
        if not media_url:
            logger.error("❌ Не удалось найти медиа")
            await send_post_with_retry(chat_id, None, caption)
            return True
        
        if media_type == 'photo' and random.random() < 0.1 and DEEPSEEK_API_KEY:
            photo_comment = await analyze_photo_for_comment(media_url)
            if photo_comment:
                caption = caption.rstrip() + "\n\n" + photo_comment
        
        if media_type == 'photo' and media_url not in history:
            history.append(media_url)
            save_history(history)
        
        # Отправляем пост с задержкой
        await send_post_with_retry(chat_id, media_url, caption, media_type, clip_url)
        logger.info(f"✅ Пост отправлен в {chat_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания поста: {e}")
        return False

# ===== ПЛАНИРОВЩИК =====

async def scheduler():
    global is_sending, last_post_time
    await asyncio.sleep(10)
    logger.info("🔄 Планировщик запущен")
    logger.info(f"📅 Расписание: {schedule_data.get('times', ['12:00', '21:00'])}")
    logger.info(f"⏱️ Минимальный интервал между постами: {MIN_POST_INTERVAL//3600} часов")
    logger.info(f"⏱️ Задержка между сообщениями: {SEND_DELAY} секунд")
    
    while True:
        try:
            current_time = time.time()
            
            if current_time - last_post_time < MIN_POST_INTERVAL:
                wait_time = random.randint(1800, 3600)
                logger.info(f"⏳ Следующая проверка через {wait_time//60} минут")
                await asyncio.sleep(wait_time)
                continue
            
            now = datetime.now()
            current_time_str = now.strftime("%H:%M")
            
            schedule_times = schedule_data.get("times", ["12:00", "21:00"])
            
            if current_time_str in schedule_times:
                if not is_sending:
                    is_sending = True
                    try:
                        random_delay = random.randint(0, 2700)
                        logger.info(f"🎲 Случайная задержка {random_delay//60} минут")
                        await asyncio.sleep(random_delay)
                        
                        if time.time() - last_post_time >= MIN_POST_INTERVAL:
                            if random.random() < 0.05:
                                logger.info("🎲 Случайный пропуск отправки (5%)")
                                last_post_time = time.time()
                            else:
                                logger.info(f"📢 Отправка по расписанию {current_time_str}")
                                await send_to_all_users()
                                last_post_time = time.time()
                                logger.info(f"✅ Пост отправлен в {datetime.now().strftime('%H:%M')}")
                        else:
                            logger.info("⏭️ Пост уже был отправлен, пропускаем")
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки: {e}")
                    finally:
                        is_sending = False
                else:
                    logger.warning("⚠️ Отправка уже идёт, пропускаем")
            
            await asyncio.sleep(60)
            
        except Exception as e:
            logger.error(f"❌ Ошибка в планировщике: {e}")
            await asyncio.sleep(60)

# ===== ОСТАЛЬНЫЕ КОМАНДЫ (BROADCAST, ОПЛАТА) =====
# ... (код broadcast_command, pay_with_stars, pay_with_rub, pay_with_aurapay,
# check_rub_payment, check_aurapay_payment, process_pre_checkout_query,
# process_successful_payment, process_successful_payment_broadcast,
# send_broadcast_for_moderation, handle_broadcast_moderation)

# ===== ЗАПУСК =====

async def main():
    try:
        logger.info("=" * 60)
        logger.info("🤖 БОТ ЗАПУЩЕН")
        logger.info("📸 85% постов про стримеров, 15% про Азию")
        logger.info(f"⏱️ Задержка между сообщениями: {SEND_DELAY} секунд")
        logger.info("=" * 60)
        
        if FREEKASSA_SHOP_ID and FREEKASSA_SECRET1:
            port = int(os.getenv("PORT", 8080))
            app = web.Application()
            app.router.add_post('/freekassa/webhook', freekassa_webhook)
            app.router.add_post('/aurapay/webhook', aurapay_webhook)
            
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            logger.info(f"🌐 Webhook сервер на порту {port}")
        
        asyncio.create_task(scheduler())
        
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "pre_checkout_query"],
            skip_updates=True
        )
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен")
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}")
        sys.exit(1)
