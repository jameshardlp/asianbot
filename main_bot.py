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
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, PreCheckoutQuery, LabeledPrice, WebAppInfo
from aiogram.exceptions import TelegramAPIError
from aiohttp import web

# Импорты из модулей
from deepseek_parser import (
    generate_caption_with_validation, get_streamer_media, get_streamer_photo,
    get_streamer_for_post, validate_caption, clean_text, truncate_by_sentences,
    STREAMER_INFO, ASIAN_QUERIES, is_photo_valid, search_bing, search_google_direct,
    search_yandex, search_pexels, search_youtube_clip, get_streamer_media,
    add_to_last_posts, is_similar, clear_prompt_cache, check_date_in_content
)
from payment_system import (
    broadcast_prices, save_broadcast_price, load_broadcast_price,
    create_freekassa_payment_link, check_freekassa_payment_status,
    create_aurapay_payment, check_aurapay_payment_status,
    aurapay_webhook, freekassa_webhook,
    broadcast_data, pending_broadcasts
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
users = []
history = []
schedule_data = {}

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

# ===== ФУНКЦИИ РАБОТЫ С ФОТО (с историей) =====

async def get_random_photo(style: str = "streamer", streamer_key: str = None) -> Optional[str]:
    """Получает случайное фото с проверкой истории и даты"""
    global history
    
    if len(history) > 80:
        logger.info("История переполнена, очищаю...")
        history = []
        save_history(history)
    
    if streamer_key:
        photo = get_streamer_photo(streamer_key)
        if photo and photo not in history:
            # Проверяем дату
            if check_date_in_content("", photo):
                history.append(photo)
                save_history(history)
                return photo
        elif photo and photo in history:
            logger.info("⏭️ Фото уже использовалось")
            return None
    
    if style == 'streamer':
        streamers = ['voodoosh', 'praden', 'bratishkinoff', 'sasavot', 
                     'alina_rin', 'lasqa', 'arrowwoods', 'evelone', 'buster']
        random.shuffle(streamers)
        
        for streamer in streamers:
            photo = get_streamer_photo(streamer)
            if photo and photo not in history:
                if check_date_in_content("", photo):
                    history.append(photo)
                    save_history(history)
                    return photo
        
        logger.warning("⚠️ Не найдены фото стримеров, пробую общий поиск")
        fallback_queries = ["russian streamer face", "twitch streamer russian", "streamer portrait"]
        random.shuffle(fallback_queries)
        
        search_functions = [search_bing, search_google_direct, search_yandex]
        random.shuffle(search_functions)
        
        for query in fallback_queries[:2]:
            for search_func in search_functions[:2]:
                try:
                    photo = search_func(query)
                    if photo and photo not in history:
                        if check_date_in_content("", photo):
                            history.append(photo)
                            save_history(history)
                            return photo
                except Exception as e:
                    continue
    
    queries = ASIAN_QUERIES.copy()
    random.shuffle(queries)
    
    search_functions = [search_bing, search_google_direct, search_yandex, search_pexels]
    random.shuffle(search_functions)
    
    for query in queries[:3]:
        for search_func in search_functions[:2]:
            try:
                photo = search_func(query)
                if photo and photo not in history and is_photo_valid(photo):
                    if check_date_in_content("", photo):
                        history.append(photo)
                        save_history(history)
                        return photo
            except Exception as e:
                continue
    
    logger.error("❌ Не удалось найти подходящее фото!")
    return None

async def analyze_photo_for_comment(image_url: str) -> Optional[str]:
    if not DEEPSEEK_API_KEY:
        return None
    
    try:
        import base64
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(image_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        
        base64_image = base64.b64encode(response.content).decode('utf-8')
        
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "deepseek-vl-chat",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Коротко опиши что на фото. 1-2 предложения. Грубо, с юмором. Используй мат."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 150,
            "temperature": 1.1
        }
        
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            comment = result["choices"][0]["message"]["content"].strip()
            logger.info(f"🖼️ Комментарий к фото: {comment}")
            return comment
        return None
    except Exception as e:
        logger.error(f"Ошибка анализа фото: {e}")
        return None

# ===== ФУНКЦИИ ОТПРАВКИ =====

async def send_post(chat_id, photo_url=None, caption=None, media_type='photo', clip_url=None):
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
        logger.error(f"❌ Ошибка Telegram при отправке в {chat_id}: {e}")
        if "forbidden" in str(e).lower() or "chat not found" in str(e).lower():
            users_list = load_users()
            if chat_id in users_list:
                users_list.remove(chat_id)
                save_users(users_list)
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка отправки в {chat_id}: {e}")
        return False

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
            await send_post(chat_id, None, caption)
            return True
        
        if media_type == 'photo' and random.random() < 0.1 and DEEPSEEK_API_KEY:
            photo_comment = await analyze_photo_for_comment(media_url)
            if photo_comment:
                caption = caption.rstrip() + "\n\n" + photo_comment
        
        if media_type == 'photo' and media_url not in history:
            history.append(media_url)
            save_history(history)
        
        post_data = {
            'chat_id': chat_id,
            'photo_url': media_url if media_type == 'photo' else None,
            'clip_url': clip_url,
            'media_type': media_type,
            'caption': caption,
            'user_id': user_id,
            'timestamp': time.time(),
            'needs_moderation': not skip_moderation,
            'streamer_key': streamer_key
        }
        
        logger.info(f"✅ Пост создан для {chat_id}")
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
        
        # Отправляем всем пользователям
        for chat_id in users_list:
            await send_post(chat_id, media_url, caption, media_type, clip_url)
            await asyncio.sleep(0.3)
        
        # Отправляем в канал
        channel_id = CHANNEL_ID
        if channel_id:
            await send_post(channel_id, media_url, caption, media_type, clip_url)
        
        logger.info(f"✅ Пост отправлен {len(users_list)} пользователям")
    except Exception as e:
        logger.error(f"Ошибка в send_to_all_users: {e}")

# ===== КОМАНДЫ =====

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

@dp.message(Command("start"))
async def start(msg: Message):
    try:
        chat_id = msg.chat.id
        if chat_id not in users:
            users.append(chat_id)
            save_users(users)
        
        current_schedule = load_schedule()
        times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
        stars_price = broadcast_prices.get("stars", 100)
        rub_price = broadcast_prices.get("rub", 100)
        
        await msg.answer(
            f"✅ Вы подписаны на рассылку!\n"
            f"📸 Посты про стримеров и Азию\n"
            f"⏰ Расписание: {times}\n"
            f"🔄 /photo - получить пост сейчас (до 10 раз в день)\n"
            f"⏰ /schedule - изменить расписание\n"
            f"📢 /broadcast - отправить сообщение всем (⭐ {stars_price} звёзд или 💳 {rub_price} RUB)\n"
            f"🛑 /stop - отписаться"
        )
    except Exception as e:
        logger.error(f"Ошибка в команде start: {e}")

@dp.message(Command("photo"))
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
            f"✅ Пост отправлен в очередь!\n"
            f"📊 Осталось запросов на сегодня: {remaining} из {limit}"
        )
    except Exception as e:
        logger.error(f"Ошибка в команде photo: {e}")
        await message.answer("❌ Произошла ошибка")

@dp.message(Command("post"))
async def post_command(message: Message):
    try:
        if message.from_user.id != OWNER_ID:
            await message.answer("⛔ Доступ запрещён")
            return
        
        await create_post_with_photo(str(message.chat.id), message.from_user.id, skip_moderation=True)
        await message.answer("✅ Пост создан!")
    except Exception as e:
        logger.error(f"Ошибка в команде post: {e}")

@dp.message(Command("stop"))
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
async def status(msg: Message):
    try:
        users_list = load_users()
        current_schedule = load_schedule()
        times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
        
        await msg.answer(
            f"📊 Статус бота:\n"
            f"• Подписчиков: {len(users_list)}\n"
            f"• Фото в истории: {len(history)}\n"
            f"• Расписание: {times}\n"
            f"• Канал: {'✅' if CHANNEL_ID else '❌'}"
        )
    except Exception as e:
        logger.error(f"Ошибка в команде status: {e}")

# ===== ЗАДАЧИ ПО РАСПИСАНИЮ =====

async def scheduler():
    global is_sending, last_post_time
    await asyncio.sleep(10)
    logger.info("Планировщик запущен")
    
    while True:
        try:
            current_time = time.time()
            if current_time - last_post_time < MIN_POST_INTERVAL:
                await asyncio.sleep(1800)
                continue
            
            now = datetime.now()
            current_time_str = now.strftime("%H:%M")
            
            schedule_times = schedule_data.get("times", ["12:00", "21:00"])
            if current_time_str in schedule_times:
                if not is_sending:
                    is_sending = True
                    try:
                        logger.info(f"📢 Отправка по расписанию {current_time_str}")
                        await send_to_all_users()
                        last_post_time = time.time()
                    except Exception as e:
                        logger.error(f"Ошибка отправки: {e}")
                    finally:
                        is_sending = False
            
            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}")
            await asyncio.sleep(60)

# ===== ЗАПУСК =====

async def main():
    try:
        logger.info("=" * 60)
        logger.info("🤖 БОТ ЗАПУЩЕН")
        logger.info("📸 85% постов про стримеров, 15% про Азию")
        logger.info("=" * 60)
        
        # Запускаем веб-сервер для webhook
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
        
        # Запускаем планировщик
        asyncio.create_task(scheduler())
        
        # Запускаем бота
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
