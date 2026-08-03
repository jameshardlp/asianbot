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
import base64
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
    logger.warning("Redis не установлен. Использую локальную очередь")

# Для Telegram
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, ChatMember, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, PreCheckoutQuery, LabeledPrice
from aiogram.exceptions import TelegramConflictError, TelegramAPIError

# Для веб-сервера (FreeKassa webhook)
from aiohttp import web

# ===== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ =====
is_sending = False
last_post_time = time.time()  # ✅ ИНИЦИАЛИЗИРУЕМ ПЕРЕМЕННУЮ
MIN_POST_INTERVAL = 2 * 60 * 60

# ===== КОНФИГУРАЦИЯ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_ID = int(os.getenv("OWNER_ID", 0))

# Настройки для Stars
STARS_CHANNEL_ID = -1003893727881

# Настройки для FreeKassa
FREEKASSA_SHOP_ID = os.getenv("FREEKASSA_SHOP_ID", "")
FREEKASSA_SECRET1 = os.getenv("FREEKASSA_SECRET1", "")
FREEKASSA_SECRET2 = os.getenv("FREEKASSA_SECRET2", "")
FREEKASSA_API_KEY = os.getenv("FREEKASSA_API_KEY", "")
FREEKASSA_CURRENCY = os.getenv("FREEKASSA_CURRENCY", "RUB")
FREEKASSA_WEBHOOK_URL = os.getenv("FREEKASSA_WEBHOOK_URL", "")

BROADCAST_PRICE_FILE = "broadcast_price.json"

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

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===== ФАЙЛЫ ДЛЯ ХРАНЕНИЯ ДАННЫХ =====
USERS_FILE = "users.json"
HISTORY_FILE = "history.json"
SCHEDULE_FILE = "schedule.json"

# ===== РАБОТА С ЦЕНОЙ =====

def load_broadcast_price() -> dict:
    try:
        with open(BROADCAST_PRICE_FILE, "r") as f:
            data = json.load(f)
            return data
    except:
        return {"stars": 100, "rub": 100}

def save_broadcast_price(prices: dict):
    try:
        with open(BROADCAST_PRICE_FILE, "w") as f:
            json.dump(prices, f)
        return True
    except:
        return False

broadcast_prices = load_broadcast_price()

# ===== FREEKASSA =====
def generate_freekassa_signature(shop_id: str, amount: str, order_id: str) -> str:
    """Генерация подписи для FreeKassa (использует SECRET1)"""
    sign_str = f"{shop_id}:{amount}:{FREEKASSA_SECRET1}:{FREEKASSA_CURRENCY}:{order_id}"
    logger.info(f"🔑 Подпись сгенерирована для заказа {order_id}")
    return hashlib.md5(sign_str.encode()).hexdigest()

def verify_freekassa_webhook_signature(data: dict) -> bool:
    """Проверка подписи webhook (использует SECRET2)"""
    required_fields = ['MERCHANT_ID', 'AMOUNT', 'MERCHANT_ORDER_ID', 'SIGN']
    for field in required_fields:
        if field not in data:
            return False
    
    shop_id = str(data.get('MERCHANT_ID'))
    amount = str(data.get('AMOUNT'))
    order_id = str(data.get('MERCHANT_ORDER_ID'))
    sign = str(data.get('SIGN'))
    
    sign_str = f"{shop_id}:{amount}:{FREEKASSA_SECRET2}:{FREEKASSA_CURRENCY}:{order_id}"
    expected_sign = hashlib.md5(sign_str.encode()).hexdigest()
    
    return sign == expected_sign

def create_freekassa_payment_link(amount: float, order_id: str, description: str = "") -> str:
    """Создание ссылки для оплаты через FreeKassa"""
    if not FREEKASSA_SHOP_ID or not FREEKASSA_SECRET1:
        logger.error("❌ FreeKassa не настроен")
        return ""
    
    shop_id = str(FREEKASSA_SHOP_ID)
    amount_int = int(amount)
    amount_str = str(amount_int)
    order_id_str = str(order_id)
    
    signature = generate_freekassa_signature(
        shop_id,
        amount_str,
        order_id_str
    )
    
    params = {
        "m": shop_id,
        "oa": amount_str,
        "currency": FREEKASSA_CURRENCY,
        "o": order_id_str,
        "s": signature,
    }
    
    if description:
        params["description"] = description[:255]
    
    query_string = urlencode(params)
    link = f"https://pay.fk.money/?{query_string}"
    
    logger.info(f"🔗 Ссылка для оплаты создана для заказа {order_id}")
    return link

async def check_freekassa_payment_status(order_id: str) -> Optional[dict]:
    """Проверка статуса платежа через API FreeKassa"""
    if not FREEKASSA_API_KEY:
        return None
    
    try:
        url = "https://api.freekassa.ru/v1/orders/status"
        headers = {"Content-Type": "application/json"}
        data = {
            "merchant_id": FREEKASSA_SHOP_ID,
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
        logger.error(f"Ошибка проверки статуса: {e}")
        return None

# ===== СТРАНИЦЫ ДЛЯ ПОЛЬЗОВАТЕЛЯ (для FreeKassa) =====
async def success_page(request):
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Оплата прошла успешно</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; text-align: center; padding: 50px 20px; background: #f0f4f8; margin: 0; min-height: 100vh; display: flex; justify-content: center; align-items: center; }
            .container { max-width: 500px; margin: 0 auto; background: white; padding: 40px 30px; border-radius: 16px; box-shadow: 0 10px 40px rgba(0,0,0,0.1); }
            .icon { font-size: 64px; margin-bottom: 16px; }
            h1 { color: #1a73e8; font-size: 28px; margin: 0 0 12px 0; }
            p { color: #5f6368; font-size: 16px; line-height: 1.6; margin: 8px 0; }
            .btn { display: inline-block; padding: 14px 32px; background: #1a73e8; color: white !important; text-decoration: none; border-radius: 8px; margin-top: 24px; font-weight: 600; transition: background 0.2s; border: none; cursor: pointer; }
            .btn:hover { background: #1557b0; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">✅</div>
            <h1>Оплата прошла успешно!</h1>
            <p>Ваше сообщение отправлено на модерацию.</p>
            <a href="https://t.me/asianpicbot" class="btn">Вернуться в бота</a>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def fail_page(request):
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Оплата не прошла</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; text-align: center; padding: 50px 20px; background: #fef3f2; margin: 0; min-height: 100vh; display: flex; justify-content: center; align-items: center; }
            .container { max-width: 500px; margin: 0 auto; background: white; padding: 40px 30px; border-radius: 16px; box-shadow: 0 10px 40px rgba(0,0,0,0.1); }
            .icon { font-size: 64px; margin-bottom: 16px; }
            h1 { color: #d93025; font-size: 28px; margin: 0 0 12px 0; }
            p { color: #5f6368; font-size: 16px; line-height: 1.6; margin: 8px 0; }
            .btn { display: inline-block; padding: 14px 32px; background: #1a73e8; color: white !important; text-decoration: none; border-radius: 8px; margin-top: 24px; font-weight: 600; transition: background 0.2s; border: none; cursor: pointer; }
            .btn:hover { background: #1557b0; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">❌</div>
            <h1>Оплата не прошла</h1>
            <p>Платёж был отменён или произошла ошибка.</p>
            <a href="https://t.me/asianpicbot" class="btn">Вернуться в бота</a>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def health_check(request):
    return web.Response(text="Bot is running! ✅")

# ===== РАСШИРЕННЫЕ СПИСКИ КЛЮЧЕВЫХ СЛОВ =====

ASIAN_KEYWORDS = [
    'asian', 'japanese', 'korean', 'chinese', 'thai', 'vietnamese',
    'filipino', 'indonesian', 'malaysian', 'singaporean', 'taiwanese',
    'mongolian', 'burmese', 'cambodian', 'laotian', 'east asian',
    'south east asian', 'oriental', 'asia girl', 'asia woman',
    'japan', 'korea', 'china', 'thailand', 'vietnam', 'philippines',
    'indonesia', 'malaysia', 'singapore', 'taiwan', 'mongolia',
    'myanmar', 'cambodia', 'laos', 'hong kong', 'macau',
]

NON_ASIAN_KEYWORDS = [
    'african', 'black', 'white', 'caucasian', 'european', 'american',
    'latina', 'mexican', 'brazilian', 'indian', 'middle eastern',
    'arab', 'persian', 'turkish', 'russian', 'ukrainian', 'polish',
    'german', 'french', 'italian', 'spanish', 'british', 'swedish',
    'norwegian', 'danish', 'dutch', 'belgian', 'swiss', 'austrian',
    'australian', 'canadian', 'colombian', 'peruvian', 'chilean',
    'argentinian', 'venezuelan', 'ecuadorian', 'bolivian', 'paraguayan',
    'uruguayan', 'guyanese', 'surinamese', 'egyptian', 'moroccan',
    'algerian', 'tunisian', 'libyan', 'nigerian', 'kenyan',
    'south african', 'ethiopian', 'ghanaian', 'senegalese', 'ugandan',
    'rwandan', 'somali', 'sudanese', 'american girl', 'european girl',
    'russian girl', 'ukrainian girl', 'indian girl', 'african girl',
    'american woman', 'european woman', 'russian woman', 'ukrainian woman',
    'latina girl', 'brazilian girl', 'mexican girl', 'arab girl',
    'persian girl', 'turkish girl', 'caucasian girl', 'white girl',
    'black girl', 'african woman', 'latina woman', 'brazilian woman',
]

ASIAN_NAMES = [
    'yuki', 'haruka', 'sakura', 'ai', 'miyu', 'rina', 'mika', 'kaori',
    'hana', 'momoko', 'chihiro', 'nanami', 'hinata', 'yui', 'mizuki',
    'yeon', 'jiwoo', 'eunji', 'yuna', 'hyejin', 'sooyoung', 'jisoo',
    'minji', 'nayeon', 'jeongyeon', 'momo', 'sana', 'mina', 'dahyun',
    'chaeyoung', 'tzuyu', 'jungkook', 'taehyung', 'jimin', 'namjoon',
    'seokjin', 'yoongi', 'hoseok', 'jennie', 'lisa', 'rosé', 'jisoo',
    'xiao', 'mei', 'ling', 'fang', 'li', 'hua', 'xia', 'wei', 'ting',
    'chen', 'wang', 'zhang', 'liu', 'yang', 'zhao', 'huang', 'wu',
    'somchai', 'somsak', 'somporn', 'nong', 'lek', 'noi', 'kaew',
    'mai', 'ploy', 'fah', 'mild', 'baitoey', 'gift', 'new', 'oil',
    'aom', 'joong', 'ki', 'hoon', 'jin', 'soo', 'young', 'sun',
]

AGE_POSITIVE_KEYWORDS = [
    '18', '19', '20', '21', '22', '23', '24', '25',
    '26', '27', '28', '29', '30',
    '18year', '19year', '20year', '21year', '22year',
    '18yo', '19yo', '20yo', '21yo', '22yo', '23yo',
    '20s', 'twenties', 'young', 'college', 'university',
    'student', 'freshman', 'sophomore', 'junior', 'senior',
]

TRADITIONAL_EXCLUDE = [
    'kimono', 'hanbok', 'cheongsam', 'qi pao', 'sari', 'ao dai',
    'traditional', 'folk costume', 'national dress', 'hanfu',
    'mongolian traditional', 'tibetan traditional', 'uyghur traditional',
]

CHILD_EXCLUDE_WORDS = [
    'child', 'children', 'kid', 'kids', 'baby', 'babies', 'toddler',
    'infant', 'preschool', 'kindergarten', 'schoolgirl', 'schoolboy',
    'girl scout', 'boy scout', 'cub scout', 'teen', 'teenager',
    'minor', 'underage', 'little girl', 'little boy', 'young girl',
    'young boy', 'daughter', 'son', 'family', 'family photo',
    'childhood', 'baby girl', 'baby boy', 'newborn', 'cute baby',
    'child model', 'kid model', 'baby model', 'toddler girl', 'toddler boy',
]

MEN_EXCLUDE_WORDS = [
    'man', 'men', 'boy', 'male', 'guy', 'dude', 'brother',
    'father', 'husband', 'boyfriend', 'gentleman', 'sir',
    'bloke', 'chap', 'fellow', 'lad', 'young man',
]

# ===== ПОИСКОВЫЕ ЗАПРОСЫ =====
SEARCH_QUERIES = [
    "japanese girl friend photo casual",
    "japanese woman everyday life candid",
    "japanese girl natural shot street",
    "japanese woman friend taking picture",
    "japanese girl candid moment cafe",
    "japanese woman casual day out",
    "japanese girl authentic daily life",
    "japanese woman spontaneous photo",
    "japanese girl real life snapshot",
    "japanese woman friend photo outside",
    "korean girl friend photo casual",
    "korean woman everyday life candid",
    "korean girl natural shot street",
    "korean woman friend taking picture",
    "korean girl candid moment cafe",
    "korean woman casual day out",
    "korean girl authentic daily life",
    "korean woman spontaneous photo",
    "korean girl real life snapshot",
    "korean woman friend photo outside",
    "chinese girl friend photo casual",
    "chinese woman everyday life candid",
    "chinese girl natural shot street",
    "chinese woman friend taking picture",
    "chinese girl candid moment cafe",
    "chinese woman casual day out",
    "chinese girl authentic daily life",
    "chinese woman spontaneous photo",
    "chinese girl real life snapshot",
    "chinese woman friend photo outside",
    "thai girl friend photo casual",
    "thai woman everyday life candid",
    "thai girl natural shot street",
    "thai woman friend taking picture",
    "thai girl candid moment cafe",
    "thai woman casual day out",
    "thai girl authentic daily life",
    "thai woman spontaneous photo",
    "thai girl real life snapshot",
    "thai woman friend photo outside",
    "vietnamese girl friend photo casual",
    "vietnamese woman everyday life candid",
    "vietnamese girl natural shot street",
    "vietnamese woman friend photo",
    "vietnamese girl candid moment cafe",
    "vietnamese woman casual day out",
    "filipino girl friend photo casual",
    "filipina woman everyday life candid",
    "filipino girl natural shot street",
    "filipina woman friend photo",
    "filipino girl candid moment cafe",
    "indonesian girl friend photo casual",
    "indonesian woman everyday life candid",
    "indonesian girl natural shot street",
    "indonesian woman friend photo",
    "asian girl friend photo outside",
    "asian woman everyday life candid",
    "asian girl natural shot street",
    "asian woman friend taking picture",
    "asian girl candid moment cafe",
    "asian woman casual day out",
    "asian girl authentic daily life",
    "asian woman spontaneous photo",
    "asian girl real life snapshot",
    "asian woman friend photo casual",
    "asian girl laughing with friend",
    "asian woman talking to friend",
    "asian girl walking with friend",
    "asian woman sitting with friend",
    "asian girl shopping with friend",
    "asian woman eating with friend",
    "asian girl coffee with friend",
    "asian woman market with friend",
    "asian girl street food friend",
    "asian woman casual outfit friend",
    "asian girl candid laugh",
    "asian woman natural smile",
    "asian girl genuine moment",
    "asian woman carefree day",
    "asian girl relaxed photo",
    "asian woman happy moment",
    "asian girl friend group photo",
    "asian woman friend gathering",
]

FITNESS_QUERIES = [
    "japanese fitness girl friend photo",
    "korean gym girl friend photo",
    "chinese fitness woman friend photo",
    "thai sport girl friend photo",
    "asian girl gym with friend",
]

# ===== ФУНКЦИИ ФИЛЬТРАЦИИ =====

def has_man_in_photo(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    for word in MEN_EXCLUDE_WORDS:
        if word in url_lower:
            return True
    return False

def is_child_photo(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    for word in CHILD_EXCLUDE_WORDS:
        if word in url_lower:
            return True
    child_age_patterns = [
        r'\b(0|1|2|3|4|5|6|7|8|9|10|11|12|13|14|15|16|17)\b',
        r'\b(infant|toddler|child|kid|teen)\b',
        r'\b(grade|class|school)\s+[1-9]\b',
    ]
    for pattern in child_age_patterns:
        if re.search(pattern, url_lower, re.IGNORECASE):
            return True
    return False

def is_asian_photo(url: str, additional_context: str = "") -> bool:
    if not url:
        return False
    text_to_check = url.lower()
    if additional_context:
        text_to_check += " " + additional_context.lower()
    for keyword in ASIAN_KEYWORDS:
        if keyword in text_to_check:
            return True
    for keyword in NON_ASIAN_KEYWORDS:
        if keyword in text_to_check:
            return False
    for name in ASIAN_NAMES:
        if name in text_to_check:
            return True
    has_age = False
    for pattern in AGE_POSITIVE_KEYWORDS:
        if pattern in text_to_check:
            has_age = True
            break
    if has_age:
        for keyword in ['blonde', 'blue eyes', 'green eyes', 'redhead', 'ginger']:
            if keyword in text_to_check:
                return False
        return True
    asian_features = [
        'slender', 'petite', 'olive skin', 'dark hair', 'black hair',
        'straight hair', 'bangs', 'double eyelid', 'monolid',
        'kawaii', 'cute', 'innocent', 'pure', 'delicate',
        'slender figure', 'small face', 'fair skin',
    ]
    for feature in asian_features:
        if feature in text_to_check:
            return True
    asian_domains = ['.jp', '.kr', '.cn', '.tw', '.hk', '.mo', '.sg', '.th', '.vn', '.ph', '.my', '.id']
    for domain in asian_domains:
        if domain in url.lower():
            return True
    return False

def is_age_appropriate(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    if is_child_photo(url):
        return False
    for word in AGE_POSITIVE_KEYWORDS:
        if word in url_lower:
            return True
    if re.search(r'\b(age|years?|yo|y/o)\b', url_lower, re.IGNORECASE):
        for word in AGE_POSITIVE_KEYWORDS:
            if word in url_lower:
                return True
        return False
    if 'mature' in url_lower or 'old' in url_lower or 'senior' in url_lower:
        return False
    return True

def is_traditional_clothing(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    for word in TRADITIONAL_EXCLUDE:
        if word in url_lower:
            return True
    if 'traditional dress' in url_lower or 'folk costume' in url_lower:
        return True
    return False

def is_photo_valid(url: str) -> bool:
    """Проверяет фото по всем критериям"""
    if not url:
        return False
    if is_child_photo(url):
        return False
    if has_man_in_photo(url):
        return False
    if not is_asian_photo(url):
        return False
    if not is_age_appropriate(url):
        return False
    if is_traditional_clothing(url):
        return False
    unwanted = ['naked', 'nude', 'porn', 'xxx', 'sex', 'erotic', 'bikini']
    for word in unwanted:
        if word in url.lower():
            return False
    return True

# ===== СТИЛИ ДЛЯ ГЕНЕРАЦИИ =====
# [ЗДЕСЬ ВСЕ СТИЛИ: short_joke, medium, long, everyday, funny, romantic, envy, joke, russia - ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ]

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
# [ЗДЕСЬ ВСЕ ФУНКЦИИ: clean_punctuation, ensure_ends_with_dot, get_sentences, is_sentence_complete, drop_incomplete_tail, truncate_by_sentences, validate_caption, clean_text - ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ]

# ===== РАБОТА С ФАЙЛАМИ =====
# [ЗДЕСЬ ВСЕ ФУНКЦИИ: load_schedule, save_schedule, load_users, save_users, load_history, save_history - ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ]

# ===== КЭШ =====
# [ЗДЕСЬ ФУНКЦИИ: add_to_last_posts, is_similar - ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ]

# ===== ПРОДОЛЖЕНИЕ ОБРЕЗАННОГО ТЕКСТА =====
# [ЗДЕСЬ ФУНКЦИИ: request_continuation, complete_truncated_text - ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ]

# ===== РЕЗЕРВНЫЙ ТЕКСТ =====
# [ЗДЕСЬ ФУНКЦИЯ: get_fallback_caption - ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ]

# ===== ОБНОВЛЁННАЯ ГЕНЕРАЦИЯ ПОСТОВ =====
# [ЗДЕСЬ ФУНКЦИЯ: generate_caption - ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ]

# ===== ПОИСК ФОТО =====
# [ЗДЕСЬ ФУНКЦИИ: search_bing, search_google_direct, search_yandex, search_pexels, get_random_photo - ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ]

# ===== ОЧЕРЕДЬ ЗАДАЧ =====
# [ЗДЕСЬ КЛАССЫ: TaskQueue, ModerationStatus, PostContent, ContentModerator - ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ]

# ===== ОБРАБОТЧИК ОЧЕРЕДИ =====
# [ЗДЕСЬ ВСЕ ФУНКЦИИ: send_post, queue_processor, process_post_task, process_moderation_task, notify_owner_for_moderation, generate_and_queue_post, send_to_all_users, get_channel_id - ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ]

# ===== КОМАНДЫ =====
# [ЗДЕСЬ ВСЕ КОМАНДЫ: /photo, /post, /price, /broadcast, /start, /stop, /schedule, /status, /check_channel - ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ]

# ===== ФОНОВЫЕ ЗАДАЧИ =====

async def scheduler():
    global is_sending, last_post_time
    await asyncio.sleep(10)
    logger.info("Планировщик запущен с случайным временем отправки (не чаще 1 раза в 2 часа)")
    while True:
        try:
            current_time = time.time()
            time_since_last = current_time - last_post_time
            if time_since_last < MIN_POST_INTERVAL:
                wait_time = random.randint(1800, 3600)
                logger.info(f"Следующая проверка через {wait_time // 60} минут")
                await asyncio.sleep(wait_time)
                continue
            random_delay = random.randint(3600, 14400)
            post_time = datetime.now() + timedelta(seconds=random_delay)
            logger.info(f"Следующий пост запланирован на {post_time.strftime('%Y-%m-%d %H:%M:%S')} "
                       f"(через {random_delay // 3600} часов {random_delay % 3600 // 60} минут)")
            await asyncio.sleep(random_delay)
            if time.time() - last_post_time < MIN_POST_INTERVAL:
                logger.info("Пост уже был отправлен, пропускаем")
                continue
            if not is_sending:
                is_sending = True
                try:
                    logger.info("Отправка запланированного поста...")
                    await send_to_all_users()
                    last_post_time = time.time()
                    logger.info(f"Пост отправлен! Следующий не ранее чем через {MIN_POST_INTERVAL // 3600} часов")
                except Exception as e:
                    logger.error(f"Ошибка отправки: {e}")
                finally:
                    is_sending = False
            else:
                logger.warning("Отправка уже идёт, пропускаем")
        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}")
            await asyncio.sleep(60)

async def freekassa_webhook(request):
    # [ОСТАЁТСЯ БЕЗ ИЗМЕНЕНИЙ]
    pass

# ===== ЗАПУСК =====

async def main():
    try:
        logger.info("=" * 60)
        logger.info("🤖 БОТ ЗАПУЩЕН")
        logger.info("📸 /photo — для всех пользователей")
        logger.info("📝 /post — только для владельца (дублируется в канал)")
        logger.info("📢 /broadcast — платная рассылка с медиа")
        logger.info("=" * 60)
        
        if FREEKASSA_SHOP_ID and FREEKASSA_SECRET1:
            port = int(os.getenv("PORT", 8080))
            app = web.Application()
            app.router.add_get("/", health_check)
            app.router.add_get("/success", success_page)
            app.router.add_get("/fail", fail_page)
            app.router.add_post('/freekassa/webhook', freekassa_webhook)
            
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            logger.info(f"🌐 Webhook сервер запущен на порту {port}")
        
        await task_queue.connect()
        
        asyncio.create_task(queue_processor())
        asyncio.create_task(scheduler())
        
        await bot.delete_webhook(drop_pending_updates=True)
        
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "pre_checkout_query"],
            skip_updates=True,
            polling_timeout=30
        )
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}")
        sys.exit(1)
