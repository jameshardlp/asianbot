import asyncio
import os
import random
import sys
import re
import requests
import json
import time
import gc
import hashlib
import hmac
from urllib.parse import quote, urlencode
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass
from enum import Enum
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Для Redis (опционально)
REDIS_AVAILABLE = False
try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    pass

# Для Telegram
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    Message, ChatMember, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, PreCheckoutQuery, LabeledPrice
)
from aiogram.exceptions import TelegramConflictError, TelegramAPIError
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# ===== КОНФИГУРАЦИЯ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_ID = int(os.getenv("OWNER_ID", 0))

# === НАСТРОЙКИ FREEKASSA ===
FREEKASSA_MERCHANT_ID = os.getenv("FREEKASSA_MERCHANT_ID", "")  # ID магазина
FREEKASSA_SECRET_KEY = os.getenv("FREEKASSA_SECRET_KEY", "")    # Секретный ключ (для подписи)
FREEKASSA_API_KEY = os.getenv("FREEKASSA_API_KEY", "")          # API ключ (для проверки статуса)
FREEKASSA_CURRENCY = os.getenv("FREEKASSA_CURRENCY", "RUB")     # Валюта: RUB, USD, EUR, UAH, KZT
FREEKASSA_WEBHOOK_URL = os.getenv("FREEKASSA_WEBHOOK_URL", "")  # URL для уведомлений (ваш сервер)

# Разрешённые пользователи для команды /photo в ЛС
ALLOWED_PHOTO_USERS = [OWNER_ID, 1361723521]

# Разрешённые пользователи для команды /balance
ALLOWED_BALANCE_USERS = [OWNER_ID, 1361723521]

# Настройки для Stars (оставляем для совместимости)
STARS_CHANNEL_ID = -1003893727881

# Redis настройки
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_URL = os.getenv("REDIS_URL", None)

# Очередь задач
QUEUE_NAME = "post_queue"
MODERATION_QUEUE = "moderation_queue"

if not BOT_TOKEN:
    logger.error("BOT_TOKEN не задан")
    sys.exit(1)

if not OWNER_ID:
    logger.warning("OWNER_ID не задан. Команды для владельца НЕ РАБОТАЮТ.")

if not DEEPSEEK_API_KEY:
    logger.warning("DEEPSEEK_API_KEY не задан. Генерация текста будет использовать резервные варианты.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===== ФАЙЛЫ ДЛЯ ХРАНЕНИЯ ДАННЫХ =====
USERS_FILE = "users.json"
HISTORY_FILE = "history.json"
SCHEDULE_FILE = "schedule.json"
MEMORY_FILE = "memory.json"
BROADCAST_PRICE_FILE = "broadcast_price.json"

# ===== РАБОТА С ЦЕНОЙ =====

def load_broadcast_price() -> int:
    try:
        with open(BROADCAST_PRICE_FILE, "r") as f:
            data = json.load(f)
            return data.get("price", 100)
    except:
        return 100

def save_broadcast_price(price: int):
    try:
        with open(BROADCAST_PRICE_FILE, "w") as f:
            json.dump({"price": price}, f)
        return True
    except:
        return False

broadcast_price = load_broadcast_price()

# ===== РАБОТА С FREEKASSA =====

# Хранилище для данных рассылки
broadcast_data = {}
pending_broadcasts = {}

def generate_freekassa_signature(merchant_id: str, order_id: str, amount: str, secret_key: str) -> str:
    """Генерация подписи для FreeKassa"""
    sign_str = f"{merchant_id}:{amount}:{secret_key}:{order_id}"
    return hashlib.md5(sign_str.encode()).hexdigest()

def verify_freekassa_signature(data: dict, secret_key: str) -> bool:
    """Проверка подписи от FreeKassa (для webhook)"""
    required_fields = ['MERCHANT_ID', 'AMOUNT', 'MERCHANT_ORDER_ID', 'SIGN']
    for field in required_fields:
        if field not in data:
            return False
    
    merchant_id = data.get('MERCHANT_ID')
    amount = data.get('AMOUNT')
    order_id = data.get('MERCHANT_ORDER_ID')
    sign = data.get('SIGN')
    
    # Сначала проверяем подпись с секретным ключом
    sign_str = f"{merchant_id}:{amount}:{secret_key}:{order_id}"
    expected_sign = hashlib.md5(sign_str.encode()).hexdigest()
    
    if sign != expected_sign:
        return False
    
    return True

async def check_freekassa_payment_status(order_id: str) -> Optional[dict]:
    """Проверка статуса платежа через API FreeKassa"""
    if not FREEKASSA_API_KEY:
        logger.error("FREEKASSA_API_KEY не задан")
        return None
    
    try:
        url = "https://api.freekassa.ru/v1/orders/status"
        headers = {"Content-Type": "application/json"}
        data = {
            "merchant_id": FREEKASSA_MERCHANT_ID,
            "api_key": FREEKASSA_API_KEY,
            "order_id": order_id
        }
        response = requests.post(url, headers=headers, json=data, timeout=10)
        if response.status_code == 200:
            result = response.json()
            if result.get("status") == "success":
                return result.get("data", {})
        return None
    except Exception as e:
        logger.error(f"Ошибка проверки статуса FreeKassa: {e}")
        return None

def create_freekassa_payment_link(amount: float, order_id: str, description: str = "") -> str:
    """Создание ссылки для оплаты через FreeKassa"""
    if not FREEKASSA_MERCHANT_ID or not FREEKASSA_SECRET_KEY:
        logger.error("FreeKassa не настроен")
        return ""
    
    # Формируем данные для оплаты
    params = {
        "m": FREEKASSA_MERCHANT_ID,
        "oa": amount,
        "o": order_id,
        "s": generate_freekassa_signature(FREEKASSA_MERCHANT_ID, order_id, str(amount), FREEKASSA_SECRET_KEY),
        "currency": FREEKASSA_CURRENCY,
        "lang": "ru",
    }
    
    # Если есть описание
    if description:
        params["description"] = description[:255]
    
    # Формируем URL
    query_string = urlencode(params)
    return f"https://pay.freekassa.ru/?{query_string}"

# ===== ФУНКЦИИ ДЛЯ ПАМЯТИ =====

def load_memory():
    try:
        with open(MEMORY_FILE, "r") as f:
            data = json.load(f)
            return data.get("last_posts", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    except Exception as e:
        logger.error(f"Ошибка загрузки памяти: {e}")
        return []

def save_memory(last_posts_list):
    try:
        to_save = last_posts_list[-50:] if len(last_posts_list) > 50 else last_posts_list
        with open(MEMORY_FILE, "w") as f:
            json.dump({"last_posts": to_save}, f)
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения памяти: {e}")
        return False

# ===== КЭШ И ПАМЯТЬ =====
last_posts = load_memory()
used_fallbacks = []

def add_to_last_posts(text: str):
    global last_posts, used_fallbacks
    if not text or len(text) < 10:
        return
    key = text[:100]
    if key in last_posts:
        return
    last_posts.append(key)
    if len(last_posts) > 50:
        last_posts.pop(0)
    save_memory(last_posts)

def is_similar(text: str) -> bool:
    global last_posts
    if not text:
        return False
    key = text[:150]
    for post in last_posts:
        same_chars = sum(1 for a, b in zip(key, post) if a == b)
        if len(key) > 10 and same_chars / len(key) > 0.65:
            return True
    return False

def format_text_with_paragraphs(text: str, style: str) -> str:
    if not text:
        return text
    
    if style == 'short_joke':
        return text.strip()
    
    if '\n\n' in text:
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        if len(paragraphs) > 3:
            if style == 'long':
                text = '\n\n'.join(paragraphs[:3])
            else:
                text = '\n\n'.join(paragraphs[:2])
        return text
    
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    if not sentences:
        return text
    
    if style == 'long' and len(sentences) >= 6:
        third = len(sentences) // 3
        p1 = ' '.join(sentences[:third])
        p2 = ' '.join(sentences[third:third*2])
        p3 = ' '.join(sentences[third*2:])
        return '\n\n'.join([p1, p2, p3])
    else:
        half = len(sentences) // 2
        if half == 0:
            return text
        p1 = ' '.join(sentences[:half])
        p2 = ' '.join(sentences[half:])
        return '\n\n'.join([p1, p2])

def is_coherent_text(text: str) -> bool:
    """Проверяет, является ли текст логически связным"""
    if not text or len(text) < 50:
        return False
    
    sentences = re.split(r'[.!?]+\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    if len(sentences) < 2:
        return False
    
    # Проверяем на наличие явных маркеров связности
    coherence_markers = [
        'поэтому', 'потому что', 'так как', 'из-за', 'благодаря',
        'затем', 'потом', 'после', 'сначала', 'в итоге',
        'однако', 'но', 'а', 'хотя', 'несмотря на',
        'вдруг', 'неожиданно', 'когда', 'пока', 'в то время как',
        'например', 'кстати', 'между тем',
        'я понял', 'я подумал', 'я решил', 'я вспомнил',
        'со мной', 'у меня', 'мне пришлось', 'я оказался',
        'забавно', 'смешно', 'интересно',
    ]
    
    text_lower = text.lower()
    has_marker = any(marker in text_lower for marker in coherence_markers)
    
    # Если есть маркеры связности - скорее всего текст связный
    if has_marker:
        return True
    
    # Проверяем наличие вводных слов
    intro_words = ['однажды', 'вчера', 'сегодня', 'недавно', 'как-то', 'помню', 'сижу']
    has_intro = any(word in text_lower for word in intro_words)
    
    # Проверяем наличие личных местоимений
    pronouns = ['я', 'мне', 'меня', 'мой', 'моя', 'моё']
    has_pronouns = any(pronoun in text_lower for pronoun in pronouns)
    
    # Проверяем наличие глаголов
    verbs = ['был', 'была', 'было', 'пришёл', 'пошёл', 'сделал', 'сказал', 'подумал', 'решил', 'сижу', 'стою', 'лежу']
    has_verbs = any(verb in text_lower for verb in verbs)
    
    if has_intro and has_pronouns and has_verbs:
        return True
    
    # Проверяем соотношение длины текста к количеству предложений
    total_chars = len(text)
    avg_sentence_len = total_chars / max(len(sentences), 1)
    
    if avg_sentence_len < 20 and len(sentences) > 3:
        return False
    
    return True

def get_fallback_caption() -> str:
    global used_fallbacks
    
    all_fallbacks = [
        "Сижу в кафе в Бангкоке, пью кофе, смотрю на прохожих. И вдруг понимаю — я уже полгода здесь, а всё ещё удивляюсь, как тайцы умудряются улыбаться даже в пробках. Я бы на их месте уже давно завёлся, а они просто включают музыку и подпевают. Это не про лаки, это про отношение к жизни. И я учусь. Медленно, но учусь.",
        
        "Вчера я решил, что пора завязывать с дошираками и начать готовить сам. Купил овощи, рис, приправы. Стою на кухне, смотрю на всё это богатство и понимаю — я даже не знаю, с чего начать. В итоге сварил рис, порезал помидор, посыпал всё приправами. Получилось съедобно. Даже вкусно. Теперь я шеф-повар. Ну, или хотя бы ученик.",
        
        "Сегодня утром я чуть не опоздал на встречу. Выхожу из дома, а мой мотоцикл не заводится. Я начинаю паниковать, дёргать ручки, пинать колёса. Проходит 10 минут — я уже весь мокрый, а он даже не чихнул. И тут я вспоминаю, что я в Таиланде, и у меня есть Grab. Заказал такси за 5 минут и уехал. Весь этот цирк был только для того, чтобы я вспомнил, что я не механик. И что мне нужно выпить кофе.",
    ]
    
    available_fallbacks = []
    for fb in all_fallbacks:
        key = fb[:50]
        if key not in [u[:50] for u in used_fallbacks[-10:]]:
            available_fallbacks.append(fb)
    
    if not available_fallbacks:
        available_fallbacks = all_fallbacks
        used_fallbacks.clear()
    
    chosen = random.choice(available_fallbacks)
    used_fallbacks.append(chosen[:50])
    if len(used_fallbacks) > 20:
        used_fallbacks.pop(0)
    
    return chosen

# ===== СТИЛИ ДЛЯ ГЕНЕРАЦИИ =====

style_prompts = {
    'short_joke': """
Ты — Анатолий, холостой мужчина средних лет, который живёт в Азии. Ты обычный парень с чувством юмора, рассказываешь забавные истории из жизни.

ВАЖНО:
- Это КОРОТКИЙ пост (250-450 символов)
- БЕЗ АБЗАЦЕВ — сплошной текст
- Реальная история из жизни
- Лёгкий юмор, самоирония
- Заканчивай выводом или смешным наблюдением

Напиши короткий жизненный пост с юмором.
""",

    'medium': """
Ты — Анатолий, холостой мужчина средних лет, который живёт в Азии. Ты рассказываешь истории из жизни.

ВАЖНО:
- Это СРЕДНИЙ пост (450-700 символов)
- 2 АБЗАЦА
- История из жизни или наблюдение
- Юмор вплетён в историю

Структура:
1. Ситуация
2. Развитие
3. Вывод или ирония
""",

    'long': """
Ты — Анатолий, холостой мужчина средних лет, который живёт в Азии. Ты рассказываешь истории из жизни.

ВАЖНО:
- Это ДЛИННЫЙ пост (700-900 символов) — КРАЙНЕ РЕДКО!
- 3 АБЗАЦА
- Полноценная история с деталями

Структура:
1. Завязка
2. Развитие с деталями
3. Вывод
""",
}

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

def clean_punctuation(text: str) -> str:
    if not text:
        return ''
    text = re.sub(r'[.!?]{2,}', '.', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def ensure_ends_with_dot(text: str) -> str:
    if not text:
        return ''
    text = text.strip()
    if text[-1] in ('.', '!', '?'):
        return text
    return text + '.'

def get_sentences(text: str) -> list:
    if not text:
        return []
    return re.split(r'(?<=[.!?])\s+', text.strip())

def is_sentence_complete(sentence: str) -> bool:
    if not sentence:
        return False
    clean = re.sub(r'[.!?]$', '', sentence).strip()
    words = clean.split()
    if len(words) < 5:
        return False
    return True

def truncate_by_sentences(text: str, max_length: int = 1023) -> str:
    if not text:
        return ''
    text = text.strip()
    if len(text) <= max_length:
        return ensure_ends_with_dot(text)
    sentences = re.split(r'(?<=[.!?])\s+', text)
    result = []
    current_length = 0
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if current_length + len(sentence) + 1 <= max_length:
            result.append(sentence)
            current_length += len(sentence) + 1
        else:
            break
    final_text = ' '.join(result).strip()
    if final_text:
        final_text = ensure_ends_with_dot(final_text)
    return final_text

def validate_caption(text: str, min_length: int = 500, max_length: int = 1023) -> Tuple[str, Optional[str]]:
    if not text:
        return '', 'Текст пустой'
    text = clean_text(text)
    if len(text) < 10:
        return '', 'Слишком короткий'
    
    if len(text) > max_length:
        text = truncate_by_sentences(text, max_length)
        if not text:
            return '', 'Текст слишком длинный и не может быть обрезан'
    
    if not text.endswith(('.', '!', '?')):
        text = ensure_ends_with_dot(text)
    
    all_sentences = get_sentences(text)
    if not all_sentences:
        return '', 'Нет предложений'
    
    if min_length > 0 and len(text) < min_length:
        return '', f'Слишком короткий ({len(text)} символов, нужно {min_length})'
    
    return text, None

def clean_text(text: str) -> str:
    if not text:
        return ''
    text = text.replace('—', '-').replace('–', '-')
    text = re.sub(r'\s+', ' ', text).strip()
    text = clean_punctuation(text)
    return text

# ===== РАБОТА С ФАЙЛАМИ =====

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

schedule_data = load_schedule()

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

users = load_users()

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

history = load_history()

# ===== [ЗДЕСЬ ВСЕ ВАШИ СУЩЕСТВУЮЩИЕ ФУНКЦИИ: search_bing, search_google_direct, search_yandex, search_pexels, search_pinterest, get_random_photo, generate_caption, TaskQueue, ContentModerator, и т.д.] =====

# ВНИМАНИЕ: ВСЕ ВАШИ СУЩЕСТВУЮЩИЕ ФУНКЦИИ ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ
# Я ПРИВОЖУ ТОЛЬКО ИЗМЕНЕННУЮ КОМАНДУ /BROADCAST И НОВЫЕ ОБРАБОТЧИКИ

# ===== НОВАЯ КОМАНДА /BROADCAST С FREEKASSA =====

@dp.message(Command("broadcast"))
async def broadcast_command(message: Message):
    try:
        if message.chat.type != "private":
            await message.answer("ℹ️ Эта команда работает только в личных сообщениях с ботом.")
            return
        
        user_id = message.from_user.id
        chat_id = message.chat.id
        
        # Проверяем настройки FreeKassa
        if not FREEKASSA_MERCHANT_ID or not FREEKASSA_SECRET_KEY:
            await message.answer(
                "❌ Платёжная система не настроена.\n"
                "Администратор должен настроить FreeKassa в переменных окружения:\n"
                "FREEKASSA_MERCHANT_ID, FREEKASSA_SECRET_KEY"
            )
            return
        
        # Проверяем, есть ли вложение
        has_media = False
        media_type = None
        media_file_id = None
        text = ""
        
        # Проверяем текст
        if message.text:
            text = message.text.replace("/broadcast", "").strip()
        
        # Проверяем вложения
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
        
        # Если нет ни текста, ни вложения
        if not text and not has_media:
            current_price = load_broadcast_price()
            await message.answer(
                f"📢 Чтобы отправить сообщение всем подписчикам, отправьте:\n"
                f"• Текст: /broadcast Ваше сообщение\n"
                f"• Фото: подпись к фото или без\n"
                f"• Видео: подпись к видео или без\n"
                f"• Документ: подпись к документу или без\n"
                f"• GIF: подпись к GIF или без\n\n"
                f"💰 Стоимость: {current_price} {FREEKASSA_CURRENCY}\n"
                f"💳 Оплата через FreeKassa (карты, электронные кошельки)\n\n"
                f"После оплаты сообщение будет отправлено на модерацию."
            )
            return
        
        # Убираем команду из текста, если она есть
        if text and text.startswith("/broadcast"):
            text = text.replace("/broadcast", "").strip()
        
        current_price = load_broadcast_price()
        
        # Создаём ID заказа
        order_id = f"broadcast_{user_id}_{int(time.time())}"
        
        # Формируем описание
        description = "Рассылка сообщения всем подписчикам"
        if text:
            description += f"\n\nТекст: {text[:100]}{'...' if len(text) > 100 else ''}"
        if has_media:
            media_names = {
                "photo": "📸 Фото",
                "video": "🎬 Видео",
                "document": "📄 Документ",
                "animation": "🎥 GIF",
                "audio": "🎵 Аудио",
                "voice": "🎤 Голосовое",
                "video_note": "🔄 Видео-кружок"
            }
            description += f"\n{media_names.get(media_type, '📎 Медиафайл')}"
        
        # Сохраняем данные для отправки после оплаты
        broadcast_data[user_id] = {
            'text': text,
            'has_media': has_media,
            'media_type': media_type,
            'media_file_id': media_file_id,
            'timestamp': time.time(),
            'chat_id': chat_id,
            'user_id': user_id,
            'order_id': order_id,
            'price': current_price
        }
        
        # Создаём кнопку для оплаты
        payment_url = create_freekassa_payment_link(current_price, order_id, description[:255])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"💳 Оплатить {current_price} {FREEKASSA_CURRENCY}",
                url=payment_url
            )],
            [InlineKeyboardButton(
                text="✅ Проверить оплату",
                callback_data=f"check_payment_{order_id}"
            )]
        ])
        
        await message.answer(
            f"📢 Для отправки рассылки необходимо оплатить {current_price} {FREEKASSA_CURRENCY}.\n\n"
            f"📝 Текст: {text[:100]}{'...' if len(text) > 100 else '' if text else '(без текста)'}\n"
            f"{'📎 С медиафайлом' if has_media else ''}\n\n"
            f"💳 Нажмите кнопку ниже для оплаты.\n"
            f"После оплаты нажмите 'Проверить оплату'.",
            reply_markup=keyboard
        )
        
        logger.info(f"Счёт FreeKassa создан для пользователя {user_id}, заказ {order_id}")
        
    except Exception as e:
        logger.error(f"Ошибка в команде broadcast: {e}")
        await message.answer(f"❌ Произошла ошибка: {str(e)[:100]}")


# ===== ПРОВЕРКА ОПЛАТЫ =====

@dp.callback_query(lambda c: c.data and c.data.startswith('check_payment_'))
async def check_payment(callback: CallbackQuery):
    try:
        order_id = callback.data.replace('check_payment_', '')
        user_id = callback.from_user.id
        
        # Проверяем, есть ли данные о рассылке
        if user_id not in broadcast_data:
            await callback.answer("❌ Данные о заказе не найдены", show_alert=True)
            return
        
        broadcast_info = broadcast_data[user_id]
        if broadcast_info.get('order_id') != order_id:
            await callback.answer("❌ Неверный заказ", show_alert=True)
            return
        
        # Проверяем статус через API FreeKassa
        await callback.answer("⏳ Проверяю статус платежа...")
        
        payment_status = await check_freekassa_payment_status(order_id)
        
        if payment_status:
            # Проверяем, оплачен ли заказ
            if payment_status.get('status') == 'paid':
                # Оплата подтверждена
                await process_broadcast_payment(callback, user_id, broadcast_info)
            else:
                # Не оплачен
                await callback.message.answer(
                    "❌ Платёж ещё не оплачен.\n"
                    "Пожалуйста, оплатите счёт и нажмите 'Проверить оплату' снова.\n"
                    "Если вы уже оплатили, подождите 1-2 минуты и повторите проверку."
                )
        else:
            await callback.message.answer(
                "⚠️ Не удалось проверить статус платежа.\n"
                "Пожалуйста, попробуйте ещё раз через несколько минут.\n"
                "Если проблема повторяется, свяжитесь с администратором."
            )
        
    except Exception as e:
        logger.error(f"Ошибка проверки платежа: {e}")
        await callback.answer("❌ Ошибка при проверке", show_alert=True)


# ===== ОБРАБОТЧИК УСПЕШНОЙ ОПЛАТЫ =====

async def process_broadcast_payment(callback: CallbackQuery, user_id: int, broadcast_info: dict):
    try:
        text = broadcast_info.get('text', '')
        has_media = broadcast_info.get('has_media', False)
        media_type = broadcast_info.get('media_type')
        media_file_id = broadcast_info.get('media_file_id')
        
        broadcast_id = f"broadcast_{int(time.time())}_{hashlib.md5(str(broadcast_info).encode()).hexdigest()[:8]}"
        
        # Сохраняем данные о рассылке
        pending_broadcasts[broadcast_id] = {
            'text': text,
            'has_media': has_media,
            'media_type': media_type,
            'media_file_id': media_file_id,
            'user_id': user_id,
            'timestamp': time.time(),
            'chat_id': broadcast_info.get('chat_id')
        }
        
        # Удаляем данные из временного хранилища
        del broadcast_data[user_id]
        
        # Отправляем на модерацию
        await send_broadcast_for_moderation(broadcast_id, pending_broadcasts[broadcast_id])
        
        await callback.message.edit_text(
            f"✅ Оплата подтверждена! Сообщение отправлено на модерацию.\n"
            f"📝 Текст: {text[:100]}{'...' if len(text) > 100 else '' if text else 'Без текста'}\n"
            f"{'📎 С медиафайлом' if has_media else ''}\n\n"
            f"⏳ Ожидайте подтверждения от администратора."
        )
        await callback.answer("✅ Оплата подтверждена!", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка обработки оплаты: {e}")
        await callback.message.answer(f"❌ Ошибка: {str(e)[:100]}")
        await callback.answer("❌ Ошибка", show_alert=True)


# ===== WEBHOOK ДЛЯ FREEKASSA =====

async def freekassa_webhook(request):
    """Обработчик уведомлений от FreeKassa"""
    try:
        data = await request.post()
        data = dict(data)
        
        logger.info(f"Получен webhook от FreeKassa: {data}")
        
        # Проверяем подпись
        if not verify_freekassa_signature(data, FREEKASSA_SECRET_KEY):
            logger.warning("Неверная подпись в webhook от FreeKassa")
            return web.Response(text="Invalid signature", status=400)
        
        # Извлекаем данные
        merchant_id = data.get('MERCHANT_ID')
        amount = data.get('AMOUNT')
        order_id = data.get('MERCHANT_ORDER_ID')
        status = data.get('STATUS')  # WAIT, SUCCESS, CANCEL, ERROR
        
        logger.info(f"Обработка webhook: order_id={order_id}, status={status}, amount={amount}")
        
        # Проверяем статус
        if status != 'SUCCESS':
            logger.info(f"Платёж {order_id} не успешен: {status}")
            return web.Response(text="OK", status=200)
        
        # Проверяем, есть ли данные о заказе
        # Ищем в broadcast_data по user_id (храним order_id)
        found = False
        for uid, info in broadcast_data.items():
            if info.get('order_id') == order_id:
                # Нашли заказ
                found = True
                # Здесь можно обработать оплату автоматически без кнопки
                logger.info(f"Платёж {order_id} подтверждён через webhook для пользователя {uid}")
                # Проверяем, не обработан ли уже
                # Можно отправить уведомление пользователю
                try:
                    await bot.send_message(
                        chat_id=uid,
                        text=f"✅ Оплата подтверждена! Ваш заказ обрабатывается.\n"
                             f"Скоро он будет отправлен на модерацию."
                    )
                    # Автоматически обрабатываем оплату
                    # process_broadcast_payment(...)
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления пользователю {uid}: {e}")
                break
        
        if not found:
            logger.warning(f"Заказ {order_id} не найден в broadcast_data")
        
        return web.Response(text="OK", status=200)
        
    except Exception as e:
        logger.error(f"Ошибка в webhook FreeKassa: {e}")
        return web.Response(text="Error", status=500)


# ===== ОТПРАВКА НА МОДЕРАЦИЮ =====

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
        
        # Создаём превью сообщения
        preview_text = f"📋 Новая рассылка на модерацию #{broadcast_id}\n\n"
        preview_text += f"👤 Заказчик ID: {user_id}\n"
        preview_text += f"💰 Оплачено: {broadcast_info.get('price', broadcast_price)} {FREEKASSA_CURRENCY}\n"
        preview_text += f"💳 Через FreeKassa\n"
        
        if text:
            preview_text += f"\n📝 Текст:\n{text[:300]}{'...' if len(text) > 300 else ''}\n"
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
                "video_note": "🔄 Видео-кружок"
            }
            preview_text += f"\n📎 {media_names.get(media_type, 'Медиафайл')} (будет отправлено)\n"
        
        preview_text += f"\n⏳ После подтверждения будет отправлено всем подписчикам."
        
        # Отправляем превью владельцу
        if has_media and media_file_id:
            if media_type == "photo":
                await bot.send_photo(
                    chat_id=OWNER_ID,
                    photo=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard
                )
            elif media_type == "video":
                await bot.send_video(
                    chat_id=OWNER_ID,
                    video=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard
                )
            elif media_type == "document":
                await bot.send_document(
                    chat_id=OWNER_ID,
                    document=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard
                )
            elif media_type == "animation":
                await bot.send_animation(
                    chat_id=OWNER_ID,
                    animation=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard
                )
            elif media_type == "audio":
                await bot.send_audio(
                    chat_id=OWNER_ID,
                    audio=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard
                )
            elif media_type == "voice":
                await bot.send_voice(
                    chat_id=OWNER_ID,
                    voice=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard
                )
            elif media_type == "video_note":
                await bot.send_video_note(
                    chat_id=OWNER_ID,
                    video_note=media_file_id,
                    reply_markup=keyboard
                )
                await bot.send_message(
                    chat_id=OWNER_ID,
                    text=preview_text,
                    reply_markup=keyboard
                )
        else:
            await bot.send_message(
                chat_id=OWNER_ID,
                text=preview_text,
                reply_markup=keyboard
            )
        
        logger.info(f"Рассылка {broadcast_id} отправлена на модерацию владельцу")
    except Exception as e:
        logger.error(f"Ошибка отправки на модерацию: {e}")


# ===== ОБРАБОТЧИК МОДЕРАЦИИ РАССЫЛКИ =====

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
            await callback.answer("✅ Сообщение одобрено. Отправляется всем подписчикам...", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n✅ ОДОБРЕНО (отправляется всем подписчикам)",
                reply_markup=None
            )
            
            text = broadcast_info.get('text', '')
            has_media = broadcast_info.get('has_media', False)
            media_type = broadcast_info.get('media_type')
            media_file_id = broadcast_info.get('media_file_id')
            users_list = load_users()
            
            sent_count = 0
            failed_count = 0
            
            # Отправляем всем пользователям
            for chat_id in users_list:
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
                        elif media_type == "document":
                            await bot.send_document(
                                chat_id=chat_id,
                                document=media_file_id,
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
                        elif media_type == "voice":
                            await bot.send_voice(
                                chat_id=chat_id,
                                voice=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "video_note":
                            await bot.send_video_note(
                                chat_id=chat_id,
                                video_note=media_file_id
                            )
                            if text:
                                await bot.send_message(chat_id=chat_id, text=text)
                    else:
                        if text:
                            await bot.send_message(chat_id=chat_id, text=text)
                    
                    sent_count += 1
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.error(f"Ошибка отправки в {chat_id}: {e}")
                    failed_count += 1
                    if "forbidden" in str(e).lower() or "chat not found" in str(e).lower():
                        if str(chat_id) in [str(u) for u in users_list]:
                            users_list.remove(str(chat_id))
                            save_users(users_list)
                            logger.info(f"Пользователь {chat_id} удалён из-за ошибки")
            
            # Отправляем в канал (если указан)
            try:
                channel_id = CHANNEL_ID
                if not channel_id or not channel_id.strip():
                    channel_id = await get_channel_id()
                if channel_id:
                    if has_media and media_file_id:
                        if media_type == "photo":
                            await bot.send_photo(
                                chat_id=channel_id,
                                photo=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "video":
                            await bot.send_video(
                                chat_id=channel_id,
                                video=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "document":
                            await bot.send_document(
                                chat_id=channel_id,
                                document=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "animation":
                            await bot.send_animation(
                                chat_id=channel_id,
                                animation=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "audio":
                            await bot.send_audio(
                                chat_id=channel_id,
                                audio=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "voice":
                            await bot.send_voice(
                                chat_id=channel_id,
                                voice=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "video_note":
                            await bot.send_video_note(
                                chat_id=channel_id,
                                video_note=media_file_id
                            )
                            if text:
                                await bot.send_message(chat_id=channel_id, text=text)
                    else:
                        if text:
                            await bot.send_message(chat_id=channel_id, text=text)
                    logger.info(f"✅ Отправлено в канал {channel_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки в канал: {e}")
            
            # Удаляем из ожидающих
            del pending_broadcasts[broadcast_id]
            
            # Отчёт владельцу
            try:
                await bot.send_message(
                    chat_id=OWNER_ID,
                    text=f"📊 Рассылка #{broadcast_id} завершена!\n"
                         f"✅ Отправлено подписчикам: {sent_count}\n"
                         f"❌ Ошибок: {failed_count}\n"
                         f"📝 Текст: {text[:200]}{'...' if len(text) > 200 else '' if text else '(без текста)'}\n"
                         f"{'📎 С медиафайлом' if has_media else ''}"
                )
            except Exception as e:
                logger.error(f"Ошибка отправки отчета: {e}")
            
            # Уведомление заказчика
            try:
                user_id = broadcast_info.get('user_id')
                if user_id:
                    await bot.send_message(
                        chat_id=user_id,
                        text=f"✅ Ваше сообщение опубликовано!\n"
                             f"📨 Отправлено: {sent_count} подписчикам\n"
                             f"📝 Текст: {text[:100]}{'...' if len(text) > 100 else '' if text else '(без текста)'}\n"
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


# ===== ФУНКЦИЯ ПОЛУЧЕНИЯ ID КАНАЛА =====

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


# ===== КОМАНДА /PRICE =====

@dp.message(Command("price"))
async def set_price(message: Message):
    try:
        if message.from_user.id != OWNER_ID:
            await message.answer("⛔ Доступ запрещён. Только для владельца.")
            return
        args = message.text.replace("/price", "").strip()
        if not args:
            current_price = load_broadcast_price()
            await message.answer(
                f"💰 Текущая цена рассылки: {current_price} {FREEKASSA_CURRENCY}\n\n"
                f"Чтобы изменить, напишите:\n"
                f"/price 100\n\n"
                f"Цена должна быть от 10 до 10000."
            )
            return
        try:
            price = int(args)
            if price < 10 or price > 10000:
                await message.answer("❌ Цена должна быть от 10 до 10000.")
                return
            save_broadcast_price(price)
            global broadcast_price
            broadcast_price = price
            await message.answer(f"✅ Цена рассылки установлена: {price} {FREEKASSA_CURRENCY}")
            logger.info(f"Цена рассылки изменена на {price} {FREEKASSA_CURRENCY}")
        except ValueError:
            await message.answer("❌ Введите число. Пример: /price 100")
    except Exception as e:
        logger.error(f"Ошибка в команде price: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")


# ===== [ВСЕ ВАШИ ОСТАЛЬНЫЕ КОМАНДЫ: /photo, /post, /start, /stop, /status, /schedule И Т.Д.] =====

# ВНИМАНИЕ: ВСЕ ВАШИ СУЩЕСТВУЮЩИЕ КОМАНДЫ ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ


# ===== ЗАПУСК =====

async def main():
    try:
        logger.info("=" * 60)
        logger.info("Бот запущен с оплатой через FreeKassa")
        logger.info(f"Подписчиков: {len(load_users())}")
        current_schedule = load_schedule()
        times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
        logger.info(f"Расписание: {times}")
        logger.info(f"Канал: {CHANNEL_ID if CHANNEL_ID else 'авто-поиск'}")
        logger.info(f"Владелец: {OWNER_ID if OWNER_ID else '❌ не задан'}")
        current_price = load_broadcast_price()
        logger.info(f"💰 Цена broadcast: {current_price} {FREEKASSA_CURRENCY}")
        logger.info(f"💳 FreeKassa Merchant ID: {FREEKASSA_MERCHANT_ID[:10] if FREEKASSA_MERCHANT_ID else '❌ не задан'}...")
        
        # Запускаем веб-сервер для webhook FreeKassa
        if FREEKASSA_WEBHOOK_URL:
            app = web.Application()
            app.router.add_post('/freekassa/webhook', freekassa_webhook)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', 8080)
            await site.start()
            logger.info(f"🌐 Webhook FreeKassa запущен на порту 8080")
            logger.info(f"📌 URL: {FREEKASSA_WEBHOOK_URL}/freekassa/webhook")
        
        logger.info("=" * 60)
        
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Webhook удалён")
        except Exception as e:
            logger.warning(f"Ошибка webhook: {e}")
        
        # Запускаем polling
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "pre_checkout_query"],
            skip_updates=True,
            polling_timeout=30
        )
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Фатальная ошибка: {e}")
        sys.exit(1)
