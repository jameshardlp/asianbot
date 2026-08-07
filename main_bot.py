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
SEND_DELAY = 3.0
users = []
history = []
schedule_data = {}

last_user_message_time = defaultdict(float)
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

users = load_users()
history = load_history()
schedule_data = load_schedule()

# ===== ФУНКЦИИ ОТПРАВКИ =====

async def send_post_with_retry(chat_id, photo_url=None, caption=None, media_type='photo', clip_url=None, max_retries=3):
    current_time = time.time()
    last_time = last_user_message_time.get(chat_id, 0)
    time_since_last = current_time - last_time
    
    if time_since_last < SEND_DELAY:
        wait_time = SEND_DELAY - time_since_last
        logger.info(f"⏳ Ожидание {wait_time:.1f} сек перед отправкой пользователю {chat_id}")
        await asyncio.sleep(wait_time)
    
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

async def send_post(chat_id, photo_url=None, caption=None, media_type='photo', clip_url=None):
    return await send_post_with_retry(chat_id, photo_url, caption, media_type, clip_url)

# ===== ИСПРАВЛЕННЫЙ ДЕКОРАТОР =====

def rate_limit(seconds: int = 3):
    def decorator(func):
        async def wrapper(message: Message, *args, **kwargs):
            user_id = message.from_user.id
            
            async with user_locks[user_id]:
                current_time = time.time()
                last_time = last_user_message_time.get(user_id, 0)
                
                if current_time - last_time < seconds:
                    logger.info(f"⏭️ Игнорируем частый запрос от {user_id} ({(current_time - last_time):.1f} сек)")
                    return
                
                last_user_message_time[user_id] = current_time
                # Передаем все аргументы, включая dispatcher
                return await func(message, *args, **kwargs)
        return wrapper
    return decorator

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

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
        
        await send_post_with_retry(chat_id, media_url, caption, media_type, clip_url)
        logger.info(f"✅ Пост отправлен в {chat_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания поста: {e}")
        return False

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
        
        # Отправляем в канал
        channel_id = CHANNEL_ID or await get_channel_id()
        if channel_id:
            try:
                logger.info(f"📢 Отправка в канал {channel_id}")
                await send_post_with_retry(channel_id, media_url, caption, media_type, clip_url)
                logger.info(f"✅ Пост отправлен в канал {channel_id}")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки в канал: {e}")
        else:
            logger.info("ℹ️ Канал не найден, отправка только пользователям")
        
        # Отправляем пользователям
        sent_count = 0
        failed_count = 0
        random.shuffle(users_list)
        
        for i, chat_id in enumerate(users_list):
            try:
                logger.info(f"📨 Отправка пользователю {i+1}/{len(users_list)}: {chat_id}")
                await send_post_with_retry(chat_id, media_url, caption, media_type, clip_url)
                sent_count += 1
                
                if i < len(users_list) - 1:
                    await asyncio.sleep(SEND_DELAY)
                    
            except Exception as e:
                logger.error(f"Ошибка отправки пользователю {chat_id}: {e}")
                failed_count += 1
        
        logger.info(f"✅ Пост отправлен: {sent_count} пользователям, {failed_count} ошибок")
    except Exception as e:
        logger.error(f"Ошибка в send_to_all_users: {e}")

# ===== КОМАНДЫ =====

@dp.message(Command("start"))
@rate_limit(seconds=3)
async def start(msg: Message):
    try:
        chat_id = msg.chat.id
        
        if chat_id not in users:
            users.append(chat_id)
            save_users(users)
            logger.info(f"👤 Добавлен пользователь: {chat_id}")
        
        current_schedule = load_schedule()
        times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
        stars_price = broadcast_prices.get("stars", 100)
        rub_price = broadcast_prices.get("rub", 100)
        
        channel_status = "❌ не найден"
        channel_id = CHANNEL_ID or await get_channel_id()
        if channel_id:
            channel_status = f"✅ {channel_id}"
        
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
@rate_limit(seconds=3)
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
        
        channel_id = CHANNEL_ID or await get_channel_id()
        if channel_id:
            await create_post_with_photo(str(channel_id), message.from_user.id, skip_moderation=True)
            await message.answer("✅ Пост создан для канала!")
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

@dp.message(Command("check_channel"))
@rate_limit(seconds=3)
async def check_channel(message: Message):
    try:
        if message.from_user.id != OWNER_ID:
            await message.answer("⛔ Доступ запрещён")
            return
        try:
            chat_member = await bot.get_chat_member(STARS_CHANNEL_ID, bot.id)
            status_text = f"📊 Статус бота в канале {STARS_CHANNEL_ID}:\n"
            status_text += f"• Статус: {chat_member.status}\n"
            status_text += f"• Может отправлять: {chat_member.can_send_messages}\n"
            status_text += f"• Может управлять: {chat_member.can_manage_chat}\n"
            status_text += f"• Может публиковать: {chat_member.can_post_messages}\n"
            status_text += f"• Может управлять видеочатами: {chat_member.can_manage_video_chats}\n"
            await message.answer(status_text)
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}\n\nУбедитесь, что бот добавлен в канал {STARS_CHANNEL_ID} как администратор.")
    except Exception as e:
        logger.error(f"Ошибка проверки канала: {e}")
        await message.answer("❌ Произошла ошибка")

# ===== ПЛАНИРОВЩИК =====

async def scheduler():
    global is_sending, last_post_time
    await asyncio.sleep(10)
    logger.info("🔄 Планировщик запущен")
    logger.info(f"📅 Расписание: {schedule_data.get('times', ['12:00', '21:00'])}")
    logger.info(f"⏱️ Минимальный интервал: {MIN_POST_INTERVAL//3600} часов")
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

# ===== КОМАНДА /BROADCAST (СОКРАЩЕНА ДЛЯ ЭКОНОМИИ МЕСТА) =====

@dp.message(Command("broadcast"))
@rate_limit(seconds=3)
async def broadcast_command(message: Message):
    try:
        if message.chat.type != "private":
            await message.answer("ℹ️ Эта команда работает только в личных сообщениях с ботом.")
            return
        
        user_id = message.from_user.id
        chat_id = message.chat.id
        
        text = ""
        has_media = False
        media_type = None
        media_file_id = None
        
        if message.text:
            text = message.text.replace("/broadcast", "").strip()
        elif message.caption:
            text = message.caption.replace("/broadcast", "").strip()
        
        if message.photo:
            has_media = True
            media_type = "photo"
            media_file_id = message.photo[-1].file_id
            text = message.caption or ""
        elif message.video:
            has_media = True
            media_type = "video"
            media_file_id = message.video.file_id
            text = message.caption or ""
        elif message.document:
            has_media = True
            media_type = "document"
            media_file_id = message.document.file_id
            text = message.caption or ""
        elif message.animation:
            has_media = True
            media_type = "animation"
            media_file_id = message.animation.file_id
            text = message.caption or ""
        elif message.audio:
            has_media = True
            media_type = "audio"
            media_file_id = message.audio.file_id
            text = message.caption or ""
        elif message.voice:
            has_media = True
            media_type = "voice"
            media_file_id = message.voice.file_id
            text = message.caption or ""
        elif message.video_note:
            has_media = True
            media_type = "video_note"
            media_file_id = message.video_note.file_id
            text = message.caption or ""
        elif message.sticker:
            has_media = True
            media_type = "sticker"
            media_file_id = message.sticker.file_id
            text = message.caption or ""
        
        if not text and not has_media:
            stars_price = broadcast_prices.get("stars", 100)
            rub_price = broadcast_prices.get("rub", 100)
            await message.answer(
                f"📢 **Платная рассылка**\n\n"
                f"Отправьте сообщение с текстом или медиафайлом.\n\n"
                f"💰 Цена: {stars_price} ⭐ или {rub_price} RUB\n"
                f"💳 После оплаты сообщение уйдёт на модерацию.\n\n"
                f"📌 Поддерживаются: фото, видео, GIF, аудио, документы, голосовые, стикеры.",
                parse_mode="Markdown"
            )
            return
        
        stars_price = broadcast_prices.get("stars", 100)
        rub_price = broadcast_prices.get("rub", 100)
        order_id = f"broadcast_{user_id}_{int(time.time())}"
        
        broadcast_data[user_id] = {
            'text': text,
            'has_media': has_media,
            'media_type': media_type,
            'media_file_id': media_file_id,
            'timestamp': time.time(),
            'chat_id': chat_id,
            'user_id': user_id,
            'order_id': order_id
        }
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"⭐ Оплатить {stars_price} звёзд", callback_data=f"pay_stars_{order_id}")],
            [InlineKeyboardButton(text=f"💳 Оплатить {rub_price} RUB", callback_data=f"pay_rub_{order_id}")],
            [InlineKeyboardButton(text=f"🔗 Оплатить через AuraPay", callback_data=f"pay_aurapay_{order_id}")]
        ])
        
        preview_text = f"📢 **Ваше сообщение для рассылки**\n\n"
        if text:
            preview_text += f"📝 {text[:200]}{'...' if len(text) > 200 else ''}\n\n"
        else:
            preview_text += f"📝 (без текста)\n\n"
        
        if has_media:
            media_names = {
                "photo": "📸 Фото",
                "video": "🎬 Видео",
                "document": "📄 Документ",
                "animation": "🎥 GIF",
                "audio": "🎵 Аудио",
                "voice": "🎤 Голосовое",
                "video_note": "🔄 Видео-кружок",
                "sticker": "🎯 Стикер"
            }
            preview_text += f"📎 {media_names.get(media_type, 'Медиафайл')} (будет отправлено)\n\n"
        
        preview_text += f"💰 Цена: {stars_price} ⭐ или {rub_price} RUB\n"
        preview_text += f"⏳ После оплаты сообщение уйдёт на модерацию."
        
        if has_media and media_file_id:
            if media_type == "photo":
                await message.answer_photo(
                    photo=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            elif media_type == "video":
                await message.answer_video(
                    video=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            elif media_type == "animation":
                await message.answer_animation(
                    animation=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            elif media_type == "audio":
                await message.answer_audio(
                    audio=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            elif media_type == "document":
                await message.answer_document(
                    document=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            elif media_type == "voice":
                await message.answer_voice(
                    voice=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            elif media_type == "video_note":
                await message.answer_video_note(
                    video_note=media_file_id,
                    reply_markup=keyboard
                )
                await message.answer(
                    preview_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            elif media_type == "sticker":
                await message.answer_sticker(
                    sticker=media_file_id,
                    reply_markup=keyboard
                )
                await message.answer(
                    preview_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
        else:
            await message.answer(
                preview_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        
        logger.info(f"📢 Рассылка создана для {user_id}, заказ {order_id}")
        
    except Exception as e:
        logger.error(f"Ошибка в команде broadcast: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")

# ===== ОБРАБОТЧИКИ ОПЛАТЫ =====

@dp.callback_query(lambda c: c.data and c.data.startswith('pay_stars_'))
async def pay_with_stars(callback: CallbackQuery):
    try:
        order_id = callback.data.replace('pay_stars_', '')
        user_id = callback.from_user.id
        
        if user_id not in broadcast_data:
            await callback.answer("❌ Данные не найдены", show_alert=True)
            return
        
        broadcast_info = broadcast_data[user_id]
        if broadcast_info.get('order_id') != order_id:
            await callback.answer("❌ Неверный заказ", show_alert=True)
            return
        
        text = broadcast_info.get('text', '')
        has_media = broadcast_info.get('has_media', False)
        stars_price = broadcast_prices.get("stars", 100)
        
        description = f"Отправка сообщения всем подписчикам бота"
        if text:
            description += f"\n\nТекст: {text[:100]}{'...' if len(text) > 100 else ''}"
        if has_media:
            description += "\n📎 С медиафайлом"
        
        prices = [LabeledPrice(label="⭐ Рассылка", amount=stars_price)]
        
        await bot.send_invoice(
            chat_id=user_id,
            title="📢 Рассылка сообщения",
            description=description,
            payload=f"broadcast_stars_{order_id}",
            provider_token="",
            currency="XTR",
            prices=prices,
            start_parameter="broadcast",
            chat_id_for_payment=STARS_CHANNEL_ID,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"⭐ Оплатить {stars_price} звёзд", pay=True)]
            ])
        )
        
        await callback.answer("🔄 Отправлен счёт на оплату звёздами")
    except Exception as e:
        logger.error(f"Ошибка оплаты звёздами: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data and c.data.startswith('pay_rub_'))
async def pay_with_rub(callback: CallbackQuery):
    try:
        order_id = callback.data.replace('pay_rub_', '')
        user_id = callback.from_user.id
        
        if user_id not in broadcast_data:
            await callback.answer("❌ Данные не найдены", show_alert=True)
            return
        
        broadcast_info = broadcast_data[user_id]
        if broadcast_info.get('order_id') != order_id:
            await callback.answer("❌ Неверный заказ", show_alert=True)
            return
        
        text = broadcast_info.get('text', '')
        has_media = broadcast_info.get('has_media', False)
        rub_price = broadcast_prices.get("rub", 100)
        
        description = f"Рассылка в Telegram"
        if text:
            description += f": {text[:50]}"
        
        payment_url = create_freekassa_payment_link(
            rub_price,
            f"{order_id}_rub",
            description
        )
        
        if not payment_url:
            await callback.answer("❌ FreeKassa не настроен", show_alert=True)
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 Оплатить {rub_price} RUB", url=payment_url)],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_rub_payment_{order_id}")]
        ])
        
        preview_text = f"💳 **Оплата в рублях**\n\n"
        if text:
            preview_text += f"📝 Текст: {text[:100]}{'...' if len(text) > 100 else ''}\n"
        else:
            preview_text += f"📝 (без текста)\n"
        if has_media:
            preview_text += f"📎 С медиафайлом\n"
        preview_text += f"💰 Сумма: {rub_price} RUB\n\n"
        preview_text += f"🔗 Нажмите кнопку ниже для оплаты через FreeKassa.\n"
        preview_text += f"После оплаты нажмите 'Проверить оплату'."
        
        await callback.message.edit_text(
            preview_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await callback.answer("🔄 Ссылка на оплату создана")
    except Exception as e:
        logger.error(f"Ошибка оплаты рублями: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data and c.data.startswith('pay_aurapay_'))
async def pay_with_aurapay(callback: CallbackQuery):
    try:
        order_id = callback.data.replace('pay_aurapay_', '')
        user_id = callback.from_user.id
        
        if user_id not in broadcast_data:
            await callback.answer("❌ Данные не найдены", show_alert=True)
            return
        
        broadcast_info = broadcast_data[user_id]
        if broadcast_info.get('order_id') != order_id:
            await callback.answer("❌ Неверный заказ", show_alert=True)
            return
        
        rub_price = broadcast_prices.get("rub", 100)
        
        miniapp_url = f"{AURAPAY_MINIAPP_URL}?order_id={order_id}&user_id={user_id}&amount={rub_price}&currency=RUB"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Оплатить через AuraPay", web_app=WebAppInfo(url=miniapp_url))],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_aurapay_payment_{order_id}")]
        ])
        
        text = broadcast_info.get('text', '')
        has_media = broadcast_info.get('has_media', False)
        
        preview_text = f"🔗 **Оплата через AuraPay**\n\n"
        if text:
            preview_text += f"📝 Текст: {text[:100]}{'...' if len(text) > 100 else ''}\n"
        if has_media:
            preview_text += f"📎 С медиафайлом\n"
        preview_text += f"💰 Сумма: {rub_price} RUB\n\n"
        preview_text += f"🔐 Нажмите кнопку ниже для оплаты через AuraPay.\n"
        preview_text += f"После оплаты нажмите 'Проверить оплату'."
        
        await callback.message.edit_text(
            preview_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await callback.answer("🔄 Ссылка на AuraPay создана")
        
    except Exception as e:
        logger.error(f"Ошибка оплаты через AuraPay: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data and c.data.startswith('check_rub_payment_'))
async def check_rub_payment(callback: CallbackQuery):
    try:
        order_id = callback.data.replace('check_rub_payment_', '')
        user_id = callback.from_user.id
        
        if user_id not in broadcast_data:
            await callback.answer("❌ Данные не найдены", show_alert=True)
            return
        
        broadcast_info = broadcast_data[user_id]
        if broadcast_info.get('order_id') != order_id:
            await callback.answer("❌ Неверный заказ", show_alert=True)
            return
        
        await callback.answer("⏳ Проверяю статус платежа...")
        
        payment_status = await check_freekassa_payment_status(f"{order_id}_rub")
        
        if payment_status and payment_status.get('status') == 'paid':
            await process_successful_payment_broadcast(user_id, broadcast_info, "rub")
        else:
            await callback.message.answer(
                "❌ Платёж ещё не оплачен.\n"
                "Оплатите счёт и нажмите 'Проверить оплату' снова."
            )
    except Exception as e:
        logger.error(f"Ошибка проверки оплаты: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data and c.data.startswith('check_aurapay_payment_'))
async def check_aurapay_payment(callback: CallbackQuery):
    try:
        order_id = callback.data.replace('check_aurapay_payment_', '')
        user_id = callback.from_user.id
        
        if user_id not in broadcast_data:
            await callback.answer("❌ Данные не найдены", show_alert=True)
            return
        
        broadcast_info = broadcast_data[user_id]
        if broadcast_info.get('order_id') != order_id:
            await callback.answer("❌ Неверный заказ", show_alert=True)
            return
        
        await callback.answer("⏳ Проверяю статус платежа...")
        
        full_order_id = f"{order_id}_aurapay"
        payment_status = await check_aurapay_payment_status(full_order_id)
        
        if payment_status and payment_status.get('status') in ['paid', 'success', 'completed']:
            await process_successful_payment_broadcast(user_id, broadcast_info, "aurapay")
            
            if user_id in broadcast_data:
                del broadcast_data[user_id]
            
            await callback.message.edit_text(
                "✅ Оплата через AuraPay подтверждена!\n\n"
                "Ваше сообщение отправлено на модерацию.\n"
                "Ожидайте подтверждения от администратора."
            )
        else:
            await callback.message.answer(
                "❌ Платёж ещё не оплачен.\n"
                "Оплатите счёт и нажмите 'Проверить оплату' снова."
            )
            
    except Exception as e:
        logger.error(f"Ошибка проверки оплаты AuraPay: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    try:
        if pre_checkout_query.invoice_payload.startswith("broadcast_stars_"):
            await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
        else:
            await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Неизвестный платёж")
    except Exception as e:
        logger.error(f"Ошибка в pre_checkout: {e}")
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Ошибка")

@dp.message(lambda message: message.successful_payment is not None)
async def process_successful_payment(message: Message):
    try:
        user_id = message.from_user.id
        payload = message.successful_payment.invoice_payload
        if not payload.startswith("broadcast_stars_"):
            return
        
        order_id = payload.replace("broadcast_stars_", "")
        
        broadcast_info = broadcast_data.get(user_id)
        if not broadcast_info:
            await message.answer("❌ Данные о сообщении не найдены. Попробуйте снова.")
            return
        
        await process_successful_payment_broadcast(user_id, broadcast_info, "stars")
    except Exception as e:
        logger.error(f"Ошибка в successful_payment: {e}")
        await message.answer(f"❌ Ошибка при обработке платежа: {str(e)}")

async def process_successful_payment_broadcast(user_id: int, broadcast_info: dict, payment_type: str):
    try:
        text = broadcast_info.get('text', '')
        has_media = broadcast_info.get('has_media', False)
        media_type = broadcast_info.get('media_type')
        media_file_id = broadcast_info.get('media_file_id')
        
        if not text and not has_media:
            return
        
        broadcast_id = f"broadcast_{int(time.time())}_{hashlib.md5(str(broadcast_info).encode()).hexdigest()[:8]}"
        
        pending_broadcasts[broadcast_id] = {
            'text': text,
            'has_media': has_media,
            'media_type': media_type,
            'media_file_id': media_file_id,
            'user_id': user_id,
            'timestamp': time.time(),
            'chat_id': broadcast_info.get('chat_id'),
            'payment_type': payment_type
        }
        
        if user_id in broadcast_data:
            del broadcast_data[user_id]
        
        await send_broadcast_for_moderation(broadcast_id, pending_broadcasts[broadcast_id])
        
        payment_methods = {
            'stars': '⭐ Звёзды',
            'rub': '💳 FreeKassa',
            'aurapay': '🔗 AuraPay'
        }
        payment_method = payment_methods.get(payment_type, '🔗 AuraPay')
        
        await bot.send_message(
            chat_id=user_id,
            text=f"✅ Оплата получена! Сообщение отправлено на модерацию.\n"
                 f"📝 {text[:100]}{'...' if len(text) > 100 else ''}\n"
                 f"{'📎 С медиафайлом' if has_media else ''}\n"
                 f"💳 Способ оплаты: {payment_method}\n\n"
                 f"⏳ Ожидайте подтверждения от администратора."
        )
    except Exception as e:
        logger.error(f"Ошибка обработки оплаты: {e}")

async def send_broadcast_for_moderation(broadcast_id: str, broadcast_info: dict):
    if not OWNER_ID:
        return
    try:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"broad_approve_{broadcast_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"broad_reject_{broadcast_id}")
            ]
        ])
        
        text = broadcast_info.get('text', '')
        has_media = broadcast_info.get('has_media', False)
        media_type = broadcast_info.get('media_type')
        media_file_id = broadcast_info.get('media_file_id')
        user_id = broadcast_info.get('user_id')
        payment_type = broadcast_info.get('payment_type', 'stars')
        
        payment_methods = {
            'stars': '⭐ Звёзды',
            'rub': '💳 FreeKassa',
            'aurapay': '🔗 AuraPay'
        }
        payment_method = payment_methods.get(payment_type, '🔗 AuraPay')
        
        preview_text = f"📋 **Новая рассылка на модерацию** #{broadcast_id}\n\n"
        preview_text += f"👤 Заказчик ID: {user_id}\n"
        preview_text += f"💰 Оплачено: {payment_method}\n"
        
        if text:
            preview_text += f"\n📝 Текст:\n{text[:500]}{'...' if len(text) > 500 else ''}\n"
        else:
            preview_text += f"\n📝 Текст: (без текста)\n"
        
        if has_media:
            media_names = {
                "photo": "📸 Фото",
                "video": "🎬 Видео",
                "document": "📄 Документ",
                "animation": "🎥 GIF",
                "audio": "🎵 Аудио",
                "voice": "🎤 Голосовое",
                "video_note": "🔄 Видео-кружок",
                "sticker": "🎯 Стикер"
            }
            preview_text += f"\n📎 {media_names.get(media_type, 'Медиафайл')} (будет отправлено)\n"
        
        preview_text += f"\n⏳ После подтверждения будет задержка 5 минут перед публикацией."
        
        if has_media and media_file_id:
            if media_type == "photo":
                await bot.send_photo(
                    chat_id=OWNER_ID,
                    photo=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            elif media_type == "video":
                await bot.send_video(
                    chat_id=OWNER_ID,
                    video=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            elif media_type == "animation":
                await bot.send_animation(
                    chat_id=OWNER_ID,
                    animation=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            elif media_type == "audio":
                await bot.send_audio(
                    chat_id=OWNER_ID,
                    audio=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            elif media_type == "document":
                await bot.send_document(
                    chat_id=OWNER_ID,
                    document=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            elif media_type == "voice":
                await bot.send_voice(
                    chat_id=OWNER_ID,
                    voice=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            else:
                await bot.send_message(
                    chat_id=OWNER_ID,
                    text=preview_text + "\n\n📎 Медиафайл прикреплён",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
        else:
            await bot.send_message(
                chat_id=OWNER_ID,
                text=preview_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        
        logger.info(f"📨 Рассылка {broadcast_id} на модерации")
    except Exception as e:
        logger.error(f"Ошибка модерации: {e}")

@dp.callback_query(lambda c: c.data and c.data.startswith('broad_'))
async def handle_broadcast_moderation(callback: CallbackQuery):
    try:
        if callback.from_user.id != OWNER_ID:
            await callback.answer("⛔ Доступ запрещен", show_alert=True)
            return
        parts = callback.data.split('_')
        action = parts[1]
        broadcast_id = '_'.join(parts[2:])
        approved = action == 'approve'
        if broadcast_id not in pending_broadcasts:
            await callback.answer("❌ Сообщение не найдено", show_alert=True)
            return
        broadcast_info = pending_broadcasts[broadcast_id]
        if approved:
            await callback.answer("✅ Сообщение одобрено. Будет опубликовано через 5 минут.", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n✅ ОДОБРЕНО",
                reply_markup=None
            )
            await asyncio.sleep(300)
            if broadcast_id in pending_broadcasts:
                text = broadcast_info.get('text', '')
                has_media = broadcast_info.get('has_media', False)
                media_type = broadcast_info.get('media_type')
                media_file_id = broadcast_info.get('media_file_id')
                
                users_list = load_users()
                sent_count = 0
                failed_count = 0
                
                for i, chat_id in enumerate(users_list):
                    try:
                        if has_media and media_file_id:
                            if media_type == "photo":
                                await bot.send_photo(
                                    chat_id=chat_id,
                                    photo=media_file_id,
                                    caption=text if text else None
                                )
                            elif media_type == "video":
                                await bot.send_video(
                                    chat_id=chat_id,
                                    video=media_file_id,
                                    caption=text if text else None
                                )
                            elif media_type == "animation":
                                await bot.send_animation(
                                    chat_id=chat_id,
                                    animation=media_file_id,
                                    caption=text if text else None
                                )
                            elif media_type == "audio":
                                await bot.send_audio(
                                    chat_id=chat_id,
                                    audio=media_file_id,
                                    caption=text if text else None
                                )
                            elif media_type == "document":
                                await bot.send_document(
                                    chat_id=chat_id,
                                    document=media_file_id,
                                    caption=text if text else None
                                )
                            elif media_type == "voice":
                                await bot.send_voice(
                                    chat_id=chat_id,
                                    voice=media_file_id,
                                    caption=text if text else None
                                )
                            else:
                                await bot.send_message(chat_id=chat_id, text=text)
                        else:
                            if text:
                                await bot.send_message(chat_id=chat_id, text=text)
                        
                        sent_count += 1
                        
                        if i < len(users_list) - 1:
                            await asyncio.sleep(3.0)
                            
                    except Exception as e:
                        logger.error(f"Ошибка отправки в {chat_id}: {e}")
                        failed_count += 1
                        if "forbidden" in str(e).lower() or "chat not found" in str(e).lower():
                            if chat_id in users_list:
                                users_list.remove(chat_id)
                                save_users(users_list)
                
                try:
                    if CHANNEL_ID and CHANNEL_ID.strip():
                        if has_media and media_file_id:
                            if media_type == "photo":
                                await bot.send_photo(
                                    chat_id=CHANNEL_ID,
                                    photo=media_file_id,
                                    caption=text if text else None
                                )
                            elif media_type == "video":
                                await bot.send_video(
                                    chat_id=CHANNEL_ID,
                                    video=media_file_id,
                                    caption=text if text else None
                                )
                            elif media_type == "animation":
                                await bot.send_animation(
                                    chat_id=CHANNEL_ID,
                                    animation=media_file_id,
                                    caption=text if text else None
                                )
                            elif media_type == "audio":
                                await bot.send_audio(
                                    chat_id=CHANNEL_ID,
                                    audio=media_file_id,
                                    caption=text if text else None
                                )
                            elif media_type == "document":
                                await bot.send_document(
                                    chat_id=CHANNEL_ID,
                                    document=media_file_id,
                                    caption=text if text else None
                                )
                            else:
                                await bot.send_message(chat_id=CHANNEL_ID, text=text)
                        else:
                            if text:
                                await bot.send_message(chat_id=CHANNEL_ID, text=text)
                        logger.info(f"📢 Отправлено в канал {CHANNEL_ID}")
                except Exception as e:
                    logger.error(f"Ошибка отправки в канал: {e}")
                
                del pending_broadcasts[broadcast_id]
                
                try:
                    await bot.send_message(
                        chat_id=OWNER_ID,
                        text=f"📊 Рассылка #{broadcast_id} завершена!\n"
                             f"✅ Отправлено: {sent_count}\n"
                             f"❌ Ошибок: {failed_count}\n"
                             f"📝 {text[:200]}{'...' if len(text) > 200 else ''}\n"
                             f"{'📎 С медиафайлом' if has_media else ''}"
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки отчета: {e}")
                
                try:
                    user_id = broadcast_info.get('user_id')
                    if user_id:
                        await bot.send_message(
                            chat_id=user_id,
                            text=f"✅ Ваше сообщение опубликовано!\n"
                                 f"📨 Отправлено: {sent_count} пользователям\n"
                                 f"📝 {text[:100]}{'...' if len(text) > 100 else ''}\n"
                                 f"{'📎 С медиафайлом' if has_media else ''}"
                        )
                except Exception as e:
                    logger.error(f"Ошибка уведомления заказчика: {e}")
        else:
            await callback.answer("❌ Сообщение отклонено", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n❌ ОТКЛОНЕНО",
                reply_markup=None
            )
            try:
                user_id = broadcast_info.get('user_id')
                if user_id:
                    await bot.send_message(
                        chat_id=user_id,
                        text="❌ Ваше сообщение отклонено модератором."
                    )
            except Exception as e:
                logger.error(f"Ошибка уведомления заказчика: {e}")
            if broadcast_id in pending_broadcasts:
                del pending_broadcasts[broadcast_id]
    except Exception as e:
        logger.error(f"Ошибка в broadcast модерации: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

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
