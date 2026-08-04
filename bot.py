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
last_post_time = time.time()
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

# ===== НАСТРОЙКИ AURAPAY =====
AURAPAY_MERCHANT_ID = os.getenv("AURAPAY_MERCHANT_ID", "6a70ee5492726")
AURAPAY_API_KEY = os.getenv("AURAPAY_API_KEY", "")
AURAPAY_API_URL = os.getenv("AURAPAY_API_URL", "https://api.aurapay.tech/v1")
AURAPAY_WEBHOOK_URL = os.getenv("AURAPAY_WEBHOOK_URL", "")
AURAPAY_MINIAPP_URL = os.getenv("AURAPAY_MINIAPP_URL", "https://ваш-username.github.io/aura-payment.html")

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

# ===== ФУНКЦИИ AURAPAY =====

def create_aurapay_payment(amount: float, order_id: str, user_id: int, method: str = "card") -> Optional[dict]:
    """Создание платежа через AuraPay (по документации docs.aurapay.tech)"""
    if not AURAPAY_API_KEY:
        logger.error("❌ AuraPay API ключ не настроен")
        return None
    
    try:
        url = f"{AURAPAY_API_URL}/payment/create"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": AURAPAY_API_KEY,
            "X-Merchant-Id": AURAPAY_MERCHANT_ID
        }
        
        payload = {
            "merchant_id": AURAPAY_MERCHANT_ID,
            "order_id": order_id,
            "amount": str(amount),
            "currency": "RUB",
            "description": f"Оплата рассылки #{order_id}",
            "callback_url": f"{AURAPAY_WEBHOOK_URL}/aurapay/webhook",
            "success_url": f"{AURAPAY_WEBHOOK_URL}/aurapay-success",
            "fail_url": f"{AURAPAY_WEBHOOK_URL}/aurapay-fail",
            "payment_methods": [method] if method else ["card", "sbp", "crypto"],
            "metadata": {
                "user_id": str(user_id),
                "order_type": "broadcast"
            }
        }
        
        logger.info(f"📤 Запрос к AuraPay: {url}")
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code in [200, 201]:
            result = response.json()
            logger.info(f"📥 Ответ AuraPay: {result}")
            
            if result.get("payment_url"):
                return {
                    "payment_url": result["payment_url"],
                    "payment_id": result.get("payment_id"),
                    "status": result.get("status", "pending")
                }
            elif result.get("redirect_url"):
                return {
                    "payment_url": result["redirect_url"],
                    "payment_id": result.get("payment_id"),
                    "status": "pending"
                }
            else:
                logger.error(f"Неизвестный формат ответа: {result}")
                return None
        else:
            logger.error(f"❌ Ошибка AuraPay: {response.status_code} - {response.text}")
            return None
        
    except Exception as e:
        logger.error(f"Исключение при создании платежа AuraPay: {e}")
        return None

async def check_aurapay_payment_status(order_id: str) -> Optional[dict]:
    """Проверка статуса платежа через API AuraPay"""
    if not AURAPAY_API_KEY:
        return None
    
    try:
        url = f"{AURAPAY_API_URL}/payment/status"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": AURAPAY_API_KEY,
            "X-Merchant-Id": AURAPAY_MERCHANT_ID
        }
        payload = {"order_id": order_id}
        
        logger.info(f"📤 Запрос статуса: {order_id}")
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"📥 Статус: {result}")
            return result.get("data") or result
        else:
            logger.error(f"Ошибка статуса: {response.status_code}")
            return None
        
    except Exception as e:
        logger.error(f"Ошибка проверки статуса AuraPay: {e}")
        return None

async def aurapay_webhook(request):
    """Обработка вебхуков от AuraPay"""
    try:
        data = await request.json()
        logger.info(f"📩 Получен webhook от AuraPay: {data}")
        
        # Проверка подписи (алгоритм может отличаться, сверьте с документацией)
        # signature = data.get('signature')
        # if not verify_aurapay_signature(data, AURAPAY_API_KEY):
        #     logger.warning("❌ Неверная подпись в webhook AuraPay")
        #     return web.Response(text="Invalid signature", status=400)
        
        order_id = data.get('order_id') or data.get('merchant_order_id')
        status = data.get('status') or data.get('payment_status')
        payment_id = data.get('payment_id')
        
        if not order_id:
            return web.Response(text="Missing order_id", status=400)
        
        if status in ['paid', 'success', 'completed']:
            base_order_id = order_id.replace('_aurapay', '')
            found = False
            
            for uid, info in broadcast_data.items():
                if info.get('order_id') == base_order_id:
                    found = True
                    logger.info(f"✅ Платёж {order_id} подтверждён для {uid}")
                    
                    try:
                        await bot.send_message(
                            chat_id=uid,
                            text="✅ Оплата через AuraPay подтверждена! Ваш заказ обрабатывается."
                        )
                    except Exception as e:
                        logger.error(f"Ошибка уведомления: {e}")
                    
                    await process_successful_payment_broadcast(uid, info, "aurapay")
                    break
            
            if not found:
                logger.warning(f"⚠️ Заказ {base_order_id} не найден в broadcast_data")
        
        return web.Response(text="OK", status=200)
        
    except Exception as e:
        logger.error(f"Ошибка в webhook AuraPay: {e}")
        return web.Response(text="Error", status=500)

async def aurapay_create_payment_api(request):
    """API для создания платежа через AuraPay (для Mini App)"""
    try:
        data = await request.json()
        order_id = data.get('order_id')
        user_id = data.get('user_id')
        amount = data.get('amount', 100)
        method = data.get('method', 'card')
        
        logger.info(f"📱 Запрос создания платежа AuraPay: order_id={order_id}, user_id={user_id}, amount={amount}")
        
        if not order_id or not user_id:
            return web.json_response({"success": False, "error": "Missing parameters"})
        
        if int(user_id) not in broadcast_data:
            return web.json_response({"success": False, "error": "Order not found"})
        
        broadcast_info = broadcast_data[int(user_id)]
        if broadcast_info.get('order_id') != order_id:
            return web.json_response({"success": False, "error": "Invalid order"})
        
        full_order_id = f"{order_id}_aurapay"
        payment = create_aurapay_payment(float(amount), full_order_id, int(user_id), method)
        
        if payment and payment.get('payment_url'):
            return web.json_response({
                "success": True,
                "payment_url": payment['payment_url'],
                "payment_id": payment.get('payment_id'),
                "order_id": full_order_id
            })
        else:
            return web.json_response({"success": False, "error": "Payment creation failed"})
            
    except Exception as e:
        logger.error(f"Ошибка создания платежа AuraPay API: {e}")
        return web.json_response({"success": False, "error": str(e)})

async def aurapay_status_api(request):
    """API для проверки статуса платежа (для Mini App)"""
    try:
        data = await request.json()
        order_id = data.get('order_id')
        
        logger.info(f"📱 Запрос статуса AuraPay: order_id={order_id}")
        
        if not order_id:
            return web.json_response({"success": False, "error": "Missing order_id"})
        
        status_data = await check_aurapay_payment_status(f"{order_id}_aurapay")
        
        if status_data:
            return web.json_response({
                "success": True,
                "status": status_data.get('status', 'pending'),
                "data": status_data
            })
        else:
            return web.json_response({
                "success": True,
                "status": "pending"
            })
            
    except Exception as e:
        logger.error(f"Ошибка проверки статуса AuraPay API: {e}")
        return web.json_response({"success": False, "error": str(e)})

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

# ===== K-POP ЗАПРОСЫ =====

K_POP_QUERIES = [
    "blackpink jennie casual photo",
    "blackpink lisa everyday life",
    "blackpink rosé street style",
    "blackpink jisoo natural photo",
    "twice nayeon casual outfit",
    "twice sana everyday photo",
    "twice momo street fashion",
    "twice dahyun natural shot",
    "twice tzuyu casual style",
    "red velvet irene everyday life",
    "red velvet seulgi street photo",
    "red velvet wendy casual look",
    "aespa karina natural photo",
    "aespa winter street style",
    "aespa ningning everyday outfit",
    "aespa giselle casual fashion",
    "itzy yeji street style",
    "itzy ryujin casual photo",
    "itzy chaeryeong everyday life",
    "itzy yuna natural shot",
    "itzy lia casual outfit",
    "newjeans minji everyday photo",
    "newjeans hanni street style",
    "newjeans danielle natural shot",
    "newjeans haerin casual look",
    "newjeans hyein everyday life",
    "le sserafim chaewon street photo",
    "le sserafim sakura casual style",
    "le sserafim yunjin natural photo",
    "le sserafim kazuha everyday outfit",
    "le sserafim eunchae casual shot",
    "ive yujin street style",
    "ive wonyoung everyday photo",
    "ive liz natural casual",
    "ive rei street fashion",
    "ive leeseo everyday life",
    "gidle soyeon casual style",
    "gidle miyeon street photo",
    "gidle minnie natural look",
    "gidle yuqi everyday outfit",
    "gidle shuhua casual shot",
    "kpop idol street style",
    "kpop girl group casual photo",
    "kpop idol everyday life",
    "kpop girl natural street fashion",
    "kpop idol coffee shop casual",
    "kpop idol shopping street style",
    "kpop girl group airport fashion",
    "kpop idol casual outfit daily",
    "kpop girl natural photo outdoors",
]

# ===== K-POP ЗАПРОСЫ С КРОП-ТОПАМИ =====

K_POP_CROP_TOP_QUERIES = [
    "kpop idol crop top street style",
    "kpop girl group crop top casual",
    "jennie crop top everyday photo",
    "lisa crop top street fashion",
    "rosé crop top casual look",
    "jisoo crop top natural shot",
    "nayeon crop top everyday style",
    "sana crop top street photo",
    "momo crop top casual outfit",
    "irene crop top street style",
    "seulgi crop top everyday photo",
    "karina crop top casual look",
    "winter crop top street fashion",
    "ningning crop top everyday outfit",
    "yeji crop top street photo",
    "ryujin crop top casual style",
    "yuna crop top everyday life",
    "minji crop top street fashion",
    "hanni crop top casual photo",
    "chaewon crop top everyday style",
    "sakura crop top street look",
    "yunjin crop top casual outfit",
    "yujin crop top street style",
    "wonyoung crop top everyday photo",
    "soyeon crop top casual fashion",
    "miyeon crop top street photo",
    "kpop idol crop top stage outfit",
    "kpop girl group crop top performance",
    "kpop idol crop top concert photo",
    "kpop girl crop top street fashion",
    "kpop idol crop top summer style",
    "kpop girl group crop top daily",
    "kpop idol crop top outdoors",
    "kpop girl crop top casual street",
    "kpop idol crop top natural photo",
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

# ===== ФУНКЦИЯ ДЛЯ ВЫБОРА ЗАПРОСА В ЗАВИСИМОСТИ ОТ СТИЛЯ =====

def get_search_queries_for_style(style: str) -> List[str]:
    """
    Возвращает список поисковых запросов в зависимости от стиля поста.
    Для романтичных и смешных стилей добавляет K-pop запросы.
    """
    base_queries = SEARCH_QUERIES.copy()
    
    # Стили, для которых добавляются K-pop запросы
    kpop_styles = ['romantic', 'funny', 'joke', 'envy']
    
    if style in kpop_styles:
        # Добавляем K-pop запросы с вероятностью 70%
        if random.random() < 0.7:
            # Выбираем случайные K-pop запросы
            all_kpop = K_POP_QUERIES + K_POP_CROP_TOP_QUERIES
            selected = random.sample(all_kpop, min(5, len(all_kpop)))
            base_queries.extend(selected)
            logger.info(f"🎵 Добавлены K-pop запросы для стиля {style}")
    
    # Для всех стилей иногда добавляем crop-top запросы (редко, 10%)
    if random.random() < 0.1:
        crop_queries = random.sample(K_POP_CROP_TOP_QUERIES, min(3, len(K_POP_CROP_TOP_QUERIES)))
        base_queries.extend(crop_queries)
        logger.info("👕 Добавлены crop-top запросы")
    
    return base_queries

# ===== ФУНКЦИЯ АНАЛИЗА КАРТИНКИ (ЭКОНОМНАЯ) =====

def encode_image_to_base64_url(image_url: str) -> str:
    """Загружает картинку по URL и кодирует в base64"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(image_url, headers=headers, timeout=10)
        if response.status_code == 200:
            return base64.b64encode(response.content).decode('utf-8')
        return None
    except Exception as e:
        logger.error(f"Ошибка загрузки картинки: {e}")
        return None

async def analyze_photo_for_comment(image_url: str) -> Optional[str]:
    """
    Анализирует фото и возвращает комментарий о девушке на фото.
    Используется только в 15% случаев для экономии токенов.
    """
    if not DEEPSEEK_API_KEY:
        return None
    
    try:
        # Кодируем картинку
        base64_image = encode_image_to_base64_url(image_url)
        if not base64_image:
            return None
        
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
                            "text": """Ты — Анатолий, холостой мужик за 40, который вынужденно свайпнул в Азию.

Опиши девушку на этом фото как обычный мужик в баре. Сделай это с юмором, самоиронией и лёгкой завистью.

Важно:
- Не пиши длинно, 1-2 предложения максимум
- Не упоминай точный возраст (только "молодая", "юная")
- Пиши в стиле: "посмотрите какая милая девушка, наверняка богатая, ухаживает за собой"
- Не используй оскорбления, только лёгкая ирония
- Добавь комментарий про то, что она выглядит ухоженно/дорого/стильно

Примеры:
"посмотрите какая милая девушка, наверняка богатая, ухаживает за собой"
"красотка, сразу видно — не из дешёвых, ухоженная, улыбка на миллион"
"вот это стиль, я бы тоже так оделся, но мне уже поздно"

Ответь ТОЛЬКО комментарием, без рассуждений."""
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
        else:
            logger.error(f"Ошибка анализа фото: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"Ошибка анализа фото: {e}")
        return None

# ===== СТИЛИ ДЛЯ ГЕНЕРАЦИИ =====
style_prompts = {
    'short_joke': """
Ты — Анатолий, холостой мужик за 40, который вынужденно свайпнул в Азию.

ВАЖНО:
- Это КОРОТКИЙ пост (200-350 символов)
- Одна острая шутка про жизнь, кризис, идиотов вокруг
- Колко, дерзко, с самоиронией
- Можно спросить у подписчиков: "как у вас там, выжили?"

Твой стиль:
- Как будто ты выпил пива и решил высказаться
- Прямо, грубо, но смешно
- Напоминай, что ты оказался в Азии не от хорошей жизни
- НЕ называй точный возраст — только "в мои годы", "старый пердун", "скуф" (редко)
- Если хочешь упомянуть возраст — используй "средних лет" или самоиронично "старый пердун"

Напиши короткий колкий пост.

Требования:
- 200-350 символов
- Мат 0-1 раз
- Одна острая шутка
- Обращайся к читателям на "вы"
- Пиши только готовый пост
""",

    'medium': """
Ты — Анатолий, холостой мужик за 40, который вынужденно свайпнул в Азию.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- Одна история из жизни
- 70% — ситуация, 30% — колкая шутка
- Ты НЕ переезжаешь из страны в страну чаще раза в неделю
- Ты описываешь как путешествия, так и семейную жизнь с азиатками
- У тебя НЕТ жены, но когда-то она была (НЕ упоминай когда именно и кто это был)
- ИНОГДА давай советы о жизни в Азии (как секретный разговор)
- РЕДКО вспоминай события из детства или из жизни в России (1-2 раза в неделю максимум)
- ЕЩЁ РЕЖЕ сравнивай это со своей вынужденной поездкой в Азию
- Можно спросить у подписчиков: "как у вас там?"
- НЕ называй точный возраст — используй "в мои годы", "средних лет", изредка "скуф" или "старый пердун"

Твой стиль:
- Рассказываешь реальную историю
- Самоирония и чёрный юмор
- Добавляй одну острую шутку в конце

Структура:
1. Зацепка (1 предложение)
2. История с деталями
3. Острая шутка или колкий вывод

Требования:
- 500-700 символов
- Мат 1-2 раза
- Одна острая шутка
- Обращайся к читателям на "вы"
- НЕ упоминай жену (бывшую тоже)
- Пиши только готовый пост
""",

    'long': """
Ты — Анатолий, холостой мужик за 40, который вынужденно свайпнул в Азию.

ВАЖНО:
- Это ДЛИННЫЙ пост (850-1023 символов)
- Полноценная история с несколькими событиями
- 60% — история, 40% — колкие шутки
- Ты НЕ переезжаешь из страны в страну чаще раза в неделю
- Ты описываешь как путешествия, так и семейную жизнь с азиатками
- У тебя НЕТ жены, но когда-то она была (НЕ упоминай когда именно и кто это был)
- МОЖНО дать развёрнутый совет о жизни в Азии (как секретный разговор)
- РЕДКО вспоминай события из детства или из жизни в России (1-2 раза в неделю максимум)
- ЕЩЁ РЕЖЕ сравнивай это со своей вынужденной поездкой в Азию
- Можно задать вопрос подписчикам
- НЕ называй точный возраст — только "в мои годы", "старый пердун", "скуф" (редко)

Твой стиль:
- Детальный рассказ
- Самоирония и чёрный юмор
- Добавляй 2-3 острые шутки

Структура:
1. Зацепка (1-2 предложения)
2. Развитие истории с деталями
3. Неожиданный поворот или шутка
4. Естественный вывод

Требования:
- 850-1023 символов
- Мат 2-3 раза
- 2-3 острые шутки
- Обращайся к читателям на "вы"
- НЕ упоминай жену (бывшую тоже)
- Пиши только готовый пост
""",

    'everyday': """
Ты — Анатолий, холостой мужик за 40, который вынужденно свайпнул в Азию.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- Одна история или ситуация
- Ты НЕ переезжаешь из страны в страну чаще раза в неделю
- Ты описываешь как путешествия, так и семейную жизнь с азиатками
- У тебя НЕТ жены, но когда-то она была (НЕ упоминай когда именно и кто это был)
- ИНОГДА давай советы о выгодной жизни в Азии (как секретный разговор)
- РЕДКО вспоминай события из детства или из жизни в России (1-2 раза в неделю максимум)
- ЕЩЁ РЕЖЕ сравнивай это со своей вынужденной поездкой в Азию
- Чаще спрашивай у подписчиков в духе: "как там у вас, всё ещё дошираки доедаете?"
- НЕ называй точный возраст — только "в мои годы", "старый пердун", "скуф" (редко)

Твой стиль:
- Рассказываешь реальные истории
- Самоирония и чёрный юмор
- Добавляй одну острую шутку

Напиши пост про реальную ситуацию из жизни.

Структура:
1. Зацепка
2. История с деталями
3. Самоироничные размышления
4. Естественный вывод (НЕ мораль)

Требования:
- 500-700 символов
- Мат 1-2 раза
- Одна острая шутка
- Обращайся к читателям на "вы"
- НЕ упоминай жену (бывшую тоже)
- Пиши только готовый пост
""",

    'funny': """
Ты — Анатолий, холостой мужик за 40, который вынужденно свайпнул в Азию.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- Смешная история
- Ты НЕ переезжаешь из страны в страну чаще раза в неделю
- Ты описываешь как путешествия, так и семейную жизнь с азиатками
- У тебя НЕТ жены, но когда-то она была (НЕ упоминай когда именно и кто это был)
- РЕДКО вспоминай события из детства или из жизни в России
- НЕ называй точный возраст — только "в мои годы", "старый пердун", "скуф" (редко)

Твой стиль:
- Рассказываешь смешные истории
- Главный объект шуток — ты сам
- Юмор самоироничный с чёрным оттенком
- Добавляй одну острую шутку

Напиши смешной пост про свою жизнь.

Структура:
1. Необычная ситуация
2. Подробности с диалогами
3. Самоирония
4. Смешной вывод

Требования:
- 500-700 символов
- Мат 1-2 раза
- Одна острая шутка
- Обращайся к читателям на "вы"
- Пиши только готовый пост
""",

    'romantic': """
Ты — Анатолий, холостой мужик за 40, который вынужденно свайпнул в Азию.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- Романтичная история с чёрным юмором
- Ты НЕ переезжаешь из страны в страну чаще раза в неделю
- Ты описываешь как путешествия, так и семейную жизнь с азиатками
- У тебя НЕТ жены, но когда-то она была (НЕ упоминай когда именно и кто это был)
- РЕДКО вспоминай события из детства или из жизни в России
- НЕ называй точный возраст — только "в мои годы", "старый пердун", "скуф" (редко)

Твой стиль:
- Рассказываешь о своих чувствах с самоиронией
- Немного романтики, но с чёрным юмором
- Честно говоришь о своих недостатках
- Добавляй одну острую шутку (про себя)

Напиши романтичный пост о встрече с азиаткой.

Структура:
1. Неожиданная встреча
2. Твои чувства и сомнения
3. Самоирония над собой
4. Тёплый вывод

Требования:
- 500-700 символов
- Мат 1-2 раза
- Одна острая шутка
- Обращайся к читателям на "вы"
- Пиши только готовый пост
""",

    'envy': """
Ты — Анатолий, холостой мужик за 40, который вынужденно свайпнул в Азию.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- Зависть с чёрным юмором
- Ты НЕ переезжаешь из страны в страну чаще раза в неделю
- Ты описываешь как путешествия, так и семейную жизнь с азиатками
- У тебя НЕТ жены, но когда-то она была (НЕ упоминай когда именно и кто это был)
- ИНОГДА давай советы о жизни в Азии (как секретный разговор)
- РЕДКО вспоминай события из детства или из жизни в России
- НЕ называй точный возраст — только "в мои годы", "старый пердун", "скуф" (редко)

Твой стиль:
- Рассказываешь о том, чему завидуешь, с юмором
- Самоирония
- Добавляй одну острую шутку

Напиши пост о том, чему ты завидуешь.

Структура:
1. Что тебя поразило
2. Твои размышления
3. Сравнение с собой
4. Ироничный вывод

Требования:
- 500-700 символов
- Мат 1-2 раза
- Одна острая шутка
- Обращайся к читателям на "вы"
- Пиши только готовый пост
""",

    'joke': """
Ты — Анатолий, холостой мужик за 40, который вынужденно свайпнул в Азию.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- 70% шуток, 30% наблюдений
- Ты НЕ переезжаешь из страны в страну чаще раза в неделю
- Ты описываешь как путешествия, так и семейную жизнь с азиатками
- У тебя НЕТ жены, но когда-то она была (НЕ упоминай когда именно и кто это был)
- Можно спросить у подписчиков: "как у вас там?"
- НЕ называй точный возраст — только "в мои годы", "старый пердун", "скуф" (редко)

Твой стиль:
- Острые шутки без оскорблений
- Можно использовать мат
- Пишешь как в баре с мужиками

Напиши пост с острой шуткой.

Структура:
1. Жизненная ситуация
2. Острая шутка
3. Развитие
4. Ещё одна шутка или вывод

Требования:
- 500-700 символов
- Мат 1-3 раза
- 2-3 шутки, одна острая
- Обращайся к читателям на "вы"
- Пиши только готовый пост
""",

    'russia': """
Ты — Анатолий, холостой мужик за 40, который вынужденно свайпнул в Азию.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- История из России, которую ты РЕДКО вспоминаешь
- Сравниваешь свою прошлую жизнь в России с теперешней в Азии
- Но НЕ ноешь — шутишь над этим
- Только 1-2 раза в неделю такие посты
- НЕ называй точный возраст — только "в мои годы", "старый пердун", "скуф" (редко)

Твой стиль:
- Вспоминаешь прошлое с иронией
- Сравниваешь, но без ностальгии
- Добавляй одну острую шутку

Напиши пост про жизнь в России из прошлого.

Структура:
1. Воспоминание
2. Сравнение с Азией
3. Острая шутка
4. Вывод

Требования:
- 500-700 символов
- Мат 1-2 раза
- Одна острая шутка
- Обращайся к читателям на "вы"
- Пиши только готовый пост
""",
}

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

def clean_punctuation(text: str) -> str:
    if not text:
        return ''
    text = re.sub(r'[.!?]{2,}', '.', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.replace('«', '"').replace('»', '"')
    text = text.replace('„', '"').replace('“', '"')
    text = text.replace('`', "'").replace('´', "'")
    text = re.sub(r'[()\[\]{}<>]', '', text)
    text = re.sub(r',\s*\.', '.', text)
    return text.strip()

def ensure_ends_with_dot(text: str) -> str:
    if not text:
        return ''
    text = text.strip()
    if text[-1] in ('.', '!', '?'):
        return text
    last_end = max(text.rfind('.'), text.rfind('!'), text.rfind('?'))
    if last_end != -1:
        return text[:last_end + 1].strip()
    return text

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
    incomplete_words = ['и', 'а', 'но', 'да', 'или', 'либо', 'за', 'перед', 'под', 'над', 'без', 'для', 'про', 'через', 'между', 'среди', 'у', 'о', 'об', 'от', 'до', 'из', 'с', 'к', 'по', 'на', 'в', 'во', 'вот', 'тем', 'того', 'этого', 'того']
    last_word = words[-1].lower()
    if last_word in incomplete_words:
        return False
    incomplete_endings = [
        'в её глазах', 'в моей голове', 'в моих мыслях', 'в моей душе',
        'в моём сердце', 'в моей жизни', 'в моём мире', 'в его глазах',
        'в её голове', 'в моём сознании', 'в моей памяти', 'в моих мечтах',
        'на его лице', 'на её лице', 'в моём воображении',
        'и вы знаете', 'и я понимаю', 'и мне кажется', 'и я думаю',
        'но вы понимаете', 'но я знаю', 'и вы понимаете',
        'и я чувствую', 'и я понимаю, что', 'и я думаю, что',
        'я начинаю', 'я продолжаю', 'я хочу сказать', 'я хочу отметить',
        'я думаю о том', 'я говорю о том', 'я говорю про', 'я думаю про',
        'в общем', 'короче говоря', 'так что', 'поэтому',
        'в темноте', 'в тем', 'на тем', 'в том', 'о том',
        'и я', 'но я', 'а я', 'что я', 'когда я', 'пока я',
        'она берет', 'он берет', 'они берут', 'я беру', 'ты берешь',
        'упа', 'будто', 'как', 'словно', 'точно', 'прямо', 'почти'
    ]
    clean_lower = clean.lower()
    for ending in incomplete_endings:
        if clean_lower.endswith(ending):
            return False
    incomplete_adverbs = ['тогда', 'потом', 'сейчас', 'здесь', 'там', 'тут', 'вчера', 'сегодня', 'завтра', 'всегда', 'никогда', 'иногда', 'уже', 'ещё', 'просто', 'даже', 'почти', 'совсем', 'очень', 'слишком', 'также', 'тоже']
    if last_word in incomplete_adverbs and len(words) < 8:
        return False
    verbs = [
        'быть', 'стать', 'являться', 'иметь', 'делать', 'сказать', 'пойти',
        'знать', 'думать', 'смотреть', 'видеть', 'слышать', 'чувствовать',
        'понимать', 'хотеть', 'мочь', 'бывать', 'начинать', 'продолжать',
        'заканчивать', 'становиться', 'оставаться', 'казаться', 'стоить',
        'говорить', 'идти', 'стоять', 'сидеть', 'лежать', 'бежать',
        'плыть', 'лететь', 'ехать', 'работать', 'учиться', 'читать',
        'писать', 'рисовать', 'петь', 'танцевать', 'играть', 'смотреть',
        'слушать', 'дышать', 'жить', 'умирать', 'родиться', 'расти',
        'помнить', 'забывать', 'любить', 'ненавидеть', 'мечтать',
        'получаться', 'получиться', 'случаться', 'случиться', 'происходить',
        'произойти', 'существовать', 'обладать', 'пользоваться', 'управлять',
        'думаю', 'знаю', 'понимаю', 'вижу', 'слышу', 'чувствую'
    ]
    has_verb = any(verb in clean_lower for verb in verbs)
    has_subject = bool(re.search(r'\b(я|ты|он|она|оно|мы|вы|они|это|тот|всё|все|кто|что|который|которые|которое|эта|этот|эти|сам|себя)\b', clean, re.IGNORECASE))
    if len(clean) > 50:
        return True
    return has_verb and has_subject

def drop_incomplete_tail(text: str) -> str:
    text = text.strip()
    if not text:
        return ''
    if text[-1] in '.!?':
        return text
    last_end = max(text.rfind('.'), text.rfind('!'), text.rfind('?'))
    if last_end != -1:
        return text[:last_end + 1].strip()
    return text

def truncate_by_sentences(text: str, max_length: int = 1023) -> str:
    if not text:
        return ''
    text = text.strip()
    text = drop_incomplete_tail(text)
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
    if not result and sentences:
        first = sentences[0].strip()
        if len(first) <= max_length:
            result.append(first)
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
    last_sentence = all_sentences[-1].strip() if all_sentences else ''
    if last_sentence:
        if not last_sentence.endswith(('.', '!', '?')):
            if len(all_sentences) > 1:
                text = ' '.join(all_sentences[:-1]).strip()
                text = ensure_ends_with_dot(text)
            else:
                return '', 'Последнее предложение не завершено'
        word_count = len(last_sentence.split())
        if word_count < 5:
            if len(all_sentences) > 1:
                text = ' '.join(all_sentences[:-1]).strip()
                text = ensure_ends_with_dot(text)
            else:
                return '', f'Последнее предложение слишком короткое ({word_count} слов)'
        if not is_sentence_complete(last_sentence):
            if len(all_sentences) > 1:
                text = ' '.join(all_sentences[:-1]).strip()
                text = ensure_ends_with_dot(text)
            else:
                return '', 'Последнее предложение не завершено логически'
    if min_length > 0 and len(text) < min_length:
        if len(all_sentences) < 2:
            return '', f'Слишком короткий ({len(text)} символов, нужно {min_length})'
    return text, None

def clean_text(text: str) -> str:
    if not text:
        return ''
    text = text.replace('—', '-').replace('–', '-')
    text = text.replace('@maddysontg', '').replace('@Maddysontg', '').replace('@MADDYSONTG', '')
    text = text.replace('maddysontg', '').replace('Maddysontg', '').replace('MADDYSONTG', '')
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

# ===== КЭШ =====
last_posts = []

def add_to_last_posts(text: str):
    global last_posts
    if not text or len(text) < 10:
        return
    key = text[:100]
    last_posts.append(key)
    if len(last_posts) > 20:
        last_posts.pop(0)

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

# ===== ПРОДОЛЖЕНИЕ ОБРЕЗАННОГО ТЕКСТА =====

def request_continuation(previous_text: str) -> str:
    try:
        url = "https://api.deepseek.com/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        tail = previous_text[-500:]
        data = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Ты стендап-комик Анатолий. Текст поста был обрезан. Допиши ТОЛЬКО концовку — 1-3 завершающих предложения с логическим выводом. Не повторяй уже написанное. Только текст продолжения."},
                {"role": "user", "content": f"Вот текст, который оборвался:\n\n...{tail}\n\nДопиши концовку (1-3 предложения, завершающих мысль). Не повторяй текст выше."}
            ],
            "temperature": 0.9,
            "max_tokens": 400,
        }
        response = requests.post(url, headers=headers, json=data, timeout=30)
        if response.status_code == 200:
            result = response.json()
            if result.get("choices") and len(result["choices"]) > 0:
                return result["choices"][0].get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.error(f"Ошибка запроса продолжения: {e}")
    return ""

def complete_truncated_text(content: str, finish_reason: str) -> str:
    if finish_reason == "length" and content:
        logger.warning(f"Текст обрезан (finish_reason=length, {len(content)} символов). Запрашиваю продолжение...")
        continuation = request_continuation(content)
        if continuation:
            continuation = clean_text(continuation)
            if continuation:
                tail_100 = content[-100:].lower()
                cont_start = continuation[:100].lower()
                if tail_100 and cont_start and (tail_100 in cont_start or cont_start in tail_100):
                    logger.warning("Продолжение дублирует хвост, не склеиваю")
                else:
                    content = content.rstrip() + " " + continuation.strip()
                    logger.info(f"Продолжение получено (+{len(continuation)} символов)")
        else:
            logger.warning("Продолжение не получено, работаю с тем что есть")
    return content

# ===== РЕЗЕРВНЫЙ ТЕКСТ =====

def get_fallback_caption() -> str:
    fallbacks = [
        "Вчера в Бангкоке ко мне подошла стайка тайских девчонок и попросила сфоткаться. Я сразу расправил плечи - ну, думаю, наконец-то заметили мой шарм, мою харизму. Делаю serious face, как будто я важный чел. А они визжат, тычут пальцами. И тут одна тянет мой телефон, начинает листать и показывает на фото какого-то китайского блогера с двумя миллионами подписчиков. Оказалось, я просто попал в кадр, потому что стоял на том же месте, где он снимал своё видосик. Стою, улыбаюсь, а в голове: Анатолий, ну ты и дурак, опять повёлся. Ну и ладно, зато теперь я типа знаменит локально - сегодня меня уже трижды окликнули эй, Толик! на базаре. Вывод один: слава - это когда тебя путают с другим, но ты всё равно рад, что хоть с кем-то перепутали. И это пиздец как греет душу, честно вам скажу.",
        "Сижу в кафе в Чиангмае, пью кофе, смотрю на прохожих. Вдруг подходит местная девушка и говорит: Вы тот самый блогер? Я сразу напрягся, думаю - неужели узнали? А она показывает на мою футболку с логотипом какой-то группы и говорит, что ей нравится их музыка. Оказалось, она думала, что я участник группы. Я даже не стал её разочаровывать - улыбнулся, сфоткался с ней и пошёл дальше. Теперь я официально музыкант. Хотя на гитаре играю только в голове. Но знаете, приятно, когда тебя замечают, даже если по ошибке. Вот так и живём, ребята.",
        "Вчера на рынке в Бангкоке продавщица назвала меня красивым иностранным мужчиной. Я чуть не подавился соком. Расправил плечи, уже приготовился торговаться с чувством собственного достоинства. А она оказалась просто вежливая - так она всех мужиков называет, чтобы цену набить. Но осадочек остался, приятный такой. Домой пришёл, в зеркало посмотрел - ну вроде ничего, харизма есть. Наверное, я всё-таки красавчик, просто в этом городе слишком много настоящих красавчиков. Но мы не сдаёмся, коллеги!",
        "Тайские девушки - это отдельный вид искусства. Вчера одна сказала мне: Ты такой забавный, как мой папа. Я чуть кофе не поперхнулся. Думаю - ну всё, старость пришла. А она потом говорит: Это комплимент, папа у меня крутой! Ну ладно, тогда норм. Буду теперь гордо носить звание папик в Таиланде. Хотя, сука, обидно было первые пять секунд.",
    ]
    return random.choice(fallbacks)

# ===== ОБНОВЛЁННАЯ ГЕНЕРАЦИЯ ПОСТОВ =====

def generate_caption() -> str:
    logger.info("Генерирую уникальный пост...")
    
    if not DEEPSEEK_API_KEY:
        logger.warning("Нет ключа DeepSeek, использую резерв")
        caption = get_fallback_caption()
        caption = clean_text(caption)
        caption = truncate_by_sentences(caption)
        validated, error = validate_caption(caption, min_length=500, max_length=1023)
        if validated:
            return validated
        return clean_text(truncate_by_sentences(get_fallback_caption()))
    
    rand = random.random()
    if rand < 0.05:
        style = 'russia'
        logger.info("Выбран РЕДКИЙ пост про Россию")
        min_len, max_len = 500, 700
    elif rand < 0.20:
        style = 'short_joke'
        logger.info("Выбран КОРОТКИЙ пост (шутка)")
        min_len, max_len = 200, 400
    elif rand < 0.40:
        style = 'long'
        logger.info("Выбран ДЛИННЫЙ пост")
        min_len, max_len = 850, 1023
    else:
        weighted_styles = ['everyday', 'everyday', 'funny', 'romantic', 'envy', 'joke']
        style = random.choice(weighted_styles)
        logger.info(f"Выбран СРЕДНИЙ пост (стиль: {style})")
        min_len, max_len = 500, 700
    
    prompt = style_prompts.get(style, style_prompts['medium'])
    prompt += """

⚠️ ВАЖНОЕ ТРЕБОВАНИЕ: 
Твой ответ ДОЛЖЕН быть строго по теме, указанной в промпте. 
НЕ уходи в рассуждения, НЕ переключайся на другие темы.
НЕ используй штампы, НЕ пиши абстрактных фраз.
Только конкретная история или ситуация по теме.
Если в промпте про Азию — пиши про Азию.
Если про Россию — пиши про Россию.
НЕ МЕШАЙ ТЕМЫ В ОДНОМ ПОСТЕ.
НЕ НАЗЫВАЙ ТОЧНЫЙ ВОЗРАСТ — только "в мои годы", "средних лет", изредка "скуф" или "старый пердун".

Твой ответ (ТОЛЬКО ПОСТ, БЕЗ РАССУЖДЕНИЙ):"""
    
    alternative_prompts = {
        'short_joke': [
            "Напиши короткую колкую шутку про жизнь. 200-350 символов. ТОЛЬКО ПО ТЕМЕ.",
            "Короткая острая шутка. 200-350 символов. БЕЗ ОТСТУПЛЕНИЙ.",
            "Забавное наблюдение с колкостью. 200-350 символов. НЕ ОТВЛЕКАЙСЯ.",
        ],
        'long': [
            "Напиши длинный пост с историей. 850-1023 символов. СТРОГО ПО ТЕМЕ.",
            "Подробный рассказ с колкими шутками. 850-1023 символов. НЕ ПЕРЕСКАКИВАЙ.",
            "Развёрнутая история с чёрным юмором. 850-1023 символов. ТОЛЬКО ПО ЗАДАННОЙ ТЕМЕ.",
        ],
        'medium': [
            "Напиши пост с юмором. 500-700 символов. СТРОГО ПО ТЕМЕ.",
            "История с острой шуткой. 500-700 символов. НЕ УХОДИ В СТОРОНУ.",
            "Забавная ситуация с колким выводом. 500-700 символов. БЕЗ ОТСТУПЛЕНИЙ.",
        ],
        'russia': [
            "Напиши пост про жизнь в России из прошлого. 500-700 символов. ТОЛЬКО ПРО РОССИЮ.",
            "Вспомни свою прошлую жизнь в России с иронией. 500-700 символов. НЕ ПРО АЗИЮ.",
            "Расскажи про Россию с чёрным юмором. 500-700 символов. НЕ СМЕШИВАЙ ТЕМЫ.",
        ]
    }
    
    attempt = 0
    while True:
        attempt += 1
        try:
            url = "https://api.deepseek.com/chat/completions"
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            current_prompt = prompt
            if attempt > 1:
                if style == 'short_joke':
                    alt = random.choice(alternative_prompts['short_joke'])
                elif style == 'long':
                    alt = random.choice(alternative_prompts['long'])
                elif style == 'russia':
                    alt = random.choice(alternative_prompts['russia'])
                else:
                    alt = random.choice(alternative_prompts['medium'])
                current_prompt = alt + "\n\n⚠️ НЕ ОТВЛЕКАЙСЯ ОТ ТЕМЫ! Твой ответ (ТОЛЬКО ПОСТ, БЕЗ РАССУЖДЕНИЙ):"
                logger.info(f"Пробую альтернативный промпт (попытка {attempt})...")
            
            data = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": """Ты — Анатолий, холостой мужик за 40.

⚠️ ГЛАВНОЕ ПРАВИЛО:
Ты ДОЛЖЕН писать строго по теме, которая указана в промпте.
НЕ переключайся на другие темы.
НЕ смешивай Азию и Россию в одном посте.
НЕ пиши абстрактных рассуждений.
Только конкретная история или ситуация по теме.
Если в промпте про Азию — пиши про Азию.
Если в промпте про Россию — пиши про Россию.
Никаких отклонений от темы!
НЕ НАЗЫВАЙ ТОЧНЫЙ ВОЗРАСТ — используй "в мои годы", "средних лет", изредка "скуф" или "старый пердун".

Твой стиль:
- Колкий, дерзкий, с чёрным юмором
- Рассказываешь реальные истории из жизни
- Самоирония и сарказм
- Пиши так, будто рассказываешь друзьям в баре

Важно:
- Пиши от первого лица
- Используй мат для эмоций (не перебарщивай)
- Обращайся к читателям на "вы"
- Не упоминай жену
- Никогда не пиши о том, что твой контент запрещён
- Отвечай ТОЛЬКО готовым постом. БЕЗ РАССУЖДЕНИЙ."""},
                    {"role": "user", "content": current_prompt}
                ],
                "temperature": 1.1,
                "max_tokens": 1500,
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 400:
                error_text = response.text.lower()
                if "извините" in error_text or "не могу" in error_text or "не разрешено" in error_text:
                    logger.warning(f"Контент заблокирован, пробую другой промпт (попытка {attempt})...")
                    continue
            
            if response.status_code != 200:
                logger.error(f"DeepSeek ошибка: {response.status_code}")
                continue
            
            result = response.json()
            if not result.get("choices") or len(result["choices"]) == 0:
                logger.warning("Нет choices в ответе")
                continue
            
            choice = result["choices"][0]
            generated_content = choice.get("message", {}).get("content", "")
            finish_reason = choice.get("finish_reason", "")
            usage = result.get("usage", {})
            logger.info(f"finish_reason={finish_reason} | tokens={usage.get('completion_tokens', '?')} | chars={len(generated_content)}")
            
            if not generated_content:
                logger.warning("Пустой ответ")
                continue
            
            if finish_reason == "length":
                generated_content = complete_truncated_text(generated_content, finish_reason)
            
            if not generated_content or len(generated_content.strip()) < 20:
                logger.warning("Пустой или короткий ответ")
                continue
            
            caption = generated_content.strip().strip('"').strip("'")
            
            if not caption:
                continue
            
            if caption.lower().startswith(("мы должны", "нужно", "я должен", "напиши", "вот", "давайте", "попробуем", "извините", "к сожалению")):
                logger.warning("DeepSeek выдал рассуждение или отказ, пробуем другой промпт...")
                continue
            
            if style == 'russia' and 'ази' in caption.lower():
                logger.warning("Пост про Россию содержит упоминание Азии — отклоняем")
                continue
            
            if is_similar(caption):
                logger.info("Пост похож на недавний, пробуем ещё...")
                continue
            
            caption = clean_text(caption)
            caption = truncate_by_sentences(caption, max_length=1023)
            
            if len(caption) < min_len:
                logger.warning(f"Пост слишком короткий ({len(caption)} символов, нужно {min_len}), пробуем ещё...")
                continue
            
            if len(caption) > max_len + 50:
                logger.warning(f"Пост слишком длинный ({len(caption)} символов, нужно {max_len}), пробуем ещё...")
                continue
            
            if style == 'short_joke':
                validated, error = validate_caption(caption, min_length=100, max_length=400)
            else:
                validated, error = validate_caption(caption, min_length=min_len, max_length=max_len)
            
            if validated:
                logger.info(f"Сгенерирован уникальный пост ({len(validated)} символов, тип: {style}, попытка {attempt})")
                add_to_last_posts(validated)
                return validated
            else:
                logger.warning(f"Текст не прошёл проверку: {error}, пробуем ещё...")
                continue
            
        except Exception as e:
            logger.error(f"Ошибка генерации (попытка {attempt}): {e}")
            continue

# ===== ПОИСК ФОТО =====

def search_bing(query):
    if not query:
        return None
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        encoded_query = quote(query)
        url = f"https://www.bing.com/images/search?q={encoded_query}&form=HDRSC3&first=1&count=35&safeSearch=moderate"
        response = requests.get(url, headers=headers, timeout=15)
        patterns = [
            r'"murl":"([^"]+)"',
            r'"mediaurl":"([^"]+)"',
            r'"contentUrl":"([^"]+)"',
            r'"url":"([^"]+)"',
        ]
        images = []
        for pattern in patterns:
            found = re.findall(pattern, response.text)
            images.extend(found)
        clean_images = []
        for img in images:
            img = img.replace('\\u0026', '&').replace('\\/', '/')
            if not any(ext in img.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                continue
            if any(x in img.lower() for x in ['gstatic', 'google', 'favicon', 'logo', 'bing', 'avatar']):
                continue
            if is_photo_valid(img):
                clean_images.append(img)
        if clean_images:
            clean_images = list(dict.fromkeys(clean_images))
            return random.choice(clean_images)
        return None
    except Exception as e:
        logger.error(f"Ошибка Bing: {e}")
        return None

def search_google_direct(query):
    if not query:
        return None
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        encoded_query = quote(query)
        url = f"https://www.google.com/search?q={encoded_query}&tbm=isch&safe=active&tbs=isz:l,itp:photo"
        response = requests.get(url, headers=headers, timeout=15)
        pattern = r'imgurl=([^&]+)'
        images = re.findall(pattern, response.text)
        pattern2 = r'"([^"]+\.jpg[^"]*)"'
        images.extend(re.findall(pattern2, response.text))
        clean_images = []
        for img in images:
            img = img.replace('\\u0026', '&')
            img = img.replace('\\/', '/')
            if any(ext in img.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                if not any(x in img.lower() for x in ['gstatic', 'google', 'favicon', 'logo']):
                    if not img.startswith('data:'):
                        if is_photo_valid(img):
                            clean_images.append(img)
        clean_images = list(dict.fromkeys(clean_images))
        if clean_images:
            return random.choice(clean_images)
        return None
    except Exception as e:
        logger.error(f"Ошибка Google: {e}")
        return None

def search_yandex(query):
    if not query:
        return None
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        encoded_query = quote(query)
        url = f"https://yandex.ru/images/search?text={encoded_query}&rdrnd=1&rpt=imageview&noreask=1"
        response = requests.get(url, headers=headers, timeout=15)
        patterns = [
            r'"img_url":"([^"]+)"',
            r'"url":"([^"]+\.(jpg|jpeg|png|webp))"',
            r'<img[^>]+src="([^"]+\.(jpg|jpeg|png|webp))"',
        ]
        images = []
        for pattern in patterns:
            found = re.findall(pattern, response.text)
            for item in found:
                if isinstance(item, tuple):
                    item = item[0]
                if item and not any(x in item.lower() for x in ['logo', 'favicon', 'gif']):
                    images.append(item.replace('\\u0026', '&').replace('\\/', '/'))
        clean_images = []
        for img in images:
            if any(ext in img.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                if not any(x in img.lower() for x in ['gstatic', 'google', 'favicon', 'logo']):
                    if not img.startswith('data:'):
                        if is_photo_valid(img):
                            clean_images.append(img)
        clean_images = list(dict.fromkeys(clean_images))
        if clean_images:
            return random.choice(clean_images)
        return None
    except Exception as e:
        logger.error(f"Ошибка Yandex: {e}")
        return None

def search_pexels(query):
    if not query:
        return None
    try:
        PEXELS_KEY = os.getenv("PEXELS_KEY")
        if not PEXELS_KEY:
            return None
        url = "https://api.pexels.com/v1/search"
        headers = {"Authorization": PEXELS_KEY}
        params = {
            "query": query,
            "per_page": 30,
            "orientation": "portrait",
            "size": "large"
        }
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("photos"):
                photos = data["photos"]
                random.shuffle(photos)
                for photo in photos:
                    url = photo["src"]["large"]
                    if is_photo_valid(url):
                        return url
        return None
    except Exception as e:
        logger.error(f"Ошибка Pexels: {e}")
        return None

# ===== АСИНХРОННАЯ ФУНКЦИЯ ПОЛУЧЕНИЯ ФОТО =====

async def get_random_photo(style: str = "medium"):
    global history
    
    if len(history) > 80:
        logger.info("История переполнена, очищаю...")
        history = []
        save_history(history)
    
    # Получаем запросы в зависимости от стиля
    queries = get_search_queries_for_style(style)
    random.shuffle(queries)
    
    # Добавляем фитнес-запросы (редко)
    if random.random() < 0.1:
        queries.extend(FITNESS_QUERIES)
        logger.info("Добавлен фитнес-запрос (редко)")
    
    search_functions = [
        ('Bing', search_bing),
        ('Google', search_google_direct),
        ('Yandex', search_yandex),
        ('Pexels', search_pexels),
    ]
    
    for query in queries:
        for source_name, search_func in search_functions:
            try:
                logger.info(f"Поиск в {source_name}: {query}")
                photo = search_func(query)
                if photo and photo not in history:
                    if is_photo_valid(photo):
                        history.append(photo)
                        save_history(history)
                        logger.info(f"Найдено подходящее фото: {photo[:60]}...")
                        return photo
            except Exception as e:
                logger.error(f"Ошибка в {source_name}: {e}")
                continue
            await asyncio.sleep(0.3)
    
    logger.warning("Не удалось найти новое фото, очищаю историю...")
    history = []
    save_history(history)
    
    for query in queries[:10]:
        for source_name, search_func in search_functions:
            try:
                photo = search_func(query)
                if photo and is_photo_valid(photo):
                    history.append(photo)
                    save_history(history)
                    logger.info(f"Найдено фото после очистки: {photo[:60]}...")
                    return photo
            except:
                continue
    
    logger.error("Не удалось найти подходящее фото!")
    return None

# ===== ОБНОВЛЁННАЯ ФУНКЦИЯ СОЗДАНИЯ ПОСТА (С АНАЛИЗОМ КАРТИНКИ) =====

async def create_post_with_photo(chat_id, user_id=0, skip_moderation=False, style="medium"):
    """
    Создаёт пост с фото и текстом. ИНОГДА анализирует картинку и добавляет комментарий.
    """
    try:
        # Ищем фото
        photo_url = await get_random_photo(style)
        if not photo_url:
            logger.error("Не удалось найти фото")
            return False
        
        # Генерируем текст
        caption = generate_caption()
        if not caption:
            logger.error("Не удалось сгенерировать текст")
            return False
        
        # ===== АНАЛИЗ КАРТИНКИ (ТОЛЬКО ИНОГДА) =====
        # Анализируем только для определённых стилей и с вероятностью 15%
        analyze_styles = ['romantic', 'funny', 'joke', 'envy', 'everyday']
        should_analyze = (
            style in analyze_styles and 
            random.random() < 0.15 and 
            DEEPSEEK_API_KEY
        )
        
        photo_comment = None
        if should_analyze:
            logger.info(f"🖼️ Анализирую картинку для стиля {style} (15% вероятность)")
            photo_comment = await analyze_photo_for_comment(photo_url)
            if photo_comment:
                # Добавляем комментарий в конец поста
                caption = caption.rstrip() + "\n\n" + photo_comment
                logger.info(f"✅ Добавлен комментарий к фото: {photo_comment}")
            else:
                logger.info("⚠️ Не удалось получить комментарий к фото")
        
        # Сохраняем в историю
        history.append(photo_url)
        save_history(history)
        
        # Создаём задачу
        post_id = f"post_{int(time.time())}_{hashlib.md5(caption.encode()).hexdigest()[:8]}"
        post_data = {
            'id': post_id,
            'chat_id': chat_id,
            'photo_url': photo_url,
            'caption': caption,
            'user_id': user_id,
            'timestamp': time.time(),
            'needs_moderation': not skip_moderation,
            'style': style,
            'has_photo_comment': photo_comment is not None
        }
        
        if skip_moderation:
            await task_queue.push(QUEUE_NAME, post_data)
            logger.info(f"Пост {post_id} добавлен в очередь отправки")
            return True
        else:
            await task_queue.push(MODERATION_QUEUE, {
                'id': post_id,
                'post_data': post_data
            })
            logger.info(f"Пост {post_id} добавлен в очередь модерации")
            return True
            
    except Exception as e:
        logger.error(f"Ошибка создания поста: {e}")
        return False

# ===== ОЧЕРЕДЬ ЗАДАЧ =====

class TaskQueue:
    def __init__(self):
        self.redis = None
        self.connected = False
        self._local_queue: Dict[str, List[Dict[str, Any]]] = {}
    
    async def connect(self):
        if not REDIS_AVAILABLE:
            logger.warning("Redis недоступен, использую локальную очередь")
            return False
        try:
            if REDIS_URL:
                self.redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            else:
                self.redis = redis.Redis(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    db=REDIS_DB,
                    password=REDIS_PASSWORD,
                    decode_responses=True
                )
            await self.redis.ping()
            self.connected = True
            logger.info("Redis подключен")
            return True
        except Exception as e:
            logger.error(f"Ошибка подключения к Redis: {e}")
            self.connected = False
            return False
    
    async def push(self, queue_name: str, data: Dict[str, Any]):
        try:
            if self.connected:
                task_id = f"{queue_name}:{int(time.time())}:{hashlib.md5(str(data).encode()).hexdigest()[:8]}"
                await self.redis.rpush(queue_name, json.dumps({
                    "id": task_id,
                    "data": data,
                    "created_at": time.time()
                }))
                logger.info(f"Задача добавлена в очередь {queue_name}: {task_id}")
                return True
            else:
                if queue_name not in self._local_queue:
                    self._local_queue[queue_name] = []
                self._local_queue[queue_name].append(data)
                logger.info(f"Задача добавлена в локальную очередь {queue_name}")
                return True
        except Exception as e:
            logger.error(f"Ошибка добавления в очередь: {e}")
            return False
    
    async def pop(self, queue_name: str) -> Optional[Dict[str, Any]]:
        try:
            if self.connected:
                item = await self.redis.lpop(queue_name)
                if item:
                    return json.loads(item)
                return None
            else:
                if queue_name in self._local_queue and self._local_queue[queue_name]:
                    return self._local_queue[queue_name].pop(0)
                return None
        except Exception as e:
            logger.error(f"Ошибка получения из очереди: {e}")
            return None
    
    async def get_queue_length(self, queue_name: str) -> int:
        try:
            if self.connected:
                return await self.redis.llen(queue_name) or 0
            else:
                if queue_name in self._local_queue:
                    return len(self._local_queue[queue_name])
                return 0
        except:
            return 0

task_queue = TaskQueue()

# ===== СИСТЕМА МОДЕРАЦИИ =====

class ModerationStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"

@dataclass
class PostContent:
    photo_url: str
    caption: str
    chat_id: str
    user_id: int
    timestamp: float
    status: ModerationStatus = ModerationStatus.PENDING
    moderator_id: Optional[int] = None
    moderation_note: Optional[str] = None
    moderation_timestamp: Optional[float] = None

class ContentModerator:
    def __init__(self):
        self.pending_posts = {}
        self.approved_history = []
        self.rejected_history = []
        self.auto_approve_threshold = 0.85
        self.banned_words = [
            'naked', 'nude', 'explicit', 'porn', 'sex', 'fuck',
            'наркотики', 'оружие', 'насилие', 'убийство', 'экстремизм'
        ]
        self.suspicious_patterns = [
            r'https?://\S+\.(ru|su|cc|to|top|club|online|site|xyz|click|win|bid)',
            r'\b(купить|продать|деньги|заработать|бизнес|инвестиции)\b',
        ]
    
    async def moderate_content(self, post: PostContent) -> Tuple[Optional[bool], str]:
        try:
            text_lower = post.caption.lower()
            photo_lower = post.photo_url.lower()
            for word in self.banned_words:
                if word in text_lower or word in photo_lower:
                    return False, f"Обнаружено запрещенное слово: {word}"
            for pattern in self.suspicious_patterns:
                if re.search(pattern, post.caption, re.IGNORECASE):
                    return False, "Обнаружена подозрительная ссылка"
            if len(post.caption) < 100:
                return False, "Слишком короткий текст"
            if len(post.caption) > 1024:
                return False, "Превышен лимит символов"
            caption_hash = hashlib.md5(post.caption.encode()).hexdigest()
            if caption_hash in [p.get('hash') for p in self.approved_history[-50:]]:
                return False, "Похожий пост уже был опубликован"
            quality_score = self._check_text_quality(post.caption)
            if quality_score >= self.auto_approve_threshold:
                return True, "auto_approved"
            return None, "manual_review_required"
        except Exception as e:
            logger.error(f"Ошибка модерации: {e}")
            return False, f"Ошибка: {str(e)}"
    
    def _check_text_quality(self, text: str) -> float:
        try:
            score = 0.0
            if 500 <= len(text) <= 900:
                score += 0.3
            elif 300 <= len(text) < 500:
                score += 0.2
            sentences = re.split(r'[.!?]+', text)
            if 5 <= len(sentences) <= 15:
                score += 0.2
            if re.search(r'\b(бля|сука|пиздец|хуйня)\b', text.lower()):
                score += 0.1
            if re.search(r'\b(вы|вам|вас|ваши)\b', text.lower()):
                score += 0.1
            if re.search(r'\b(я|меня|мне|мой|моя|моего|моему)\b', text.lower()):
                if re.search(r'\b(дурак|глупый|смешной|неловкий|странный)\b', text.lower()):
                    score += 0.1
            if self._check_structure(text):
                score += 0.2
            return min(score, 1.0)
        except Exception as e:
            logger.error(f"Ошибка проверки качества: {e}")
            return 0.5
    
    def _check_structure(self, text: str) -> bool:
        try:
            sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
            if len(sentences) < 5:
                return False
            first_sentence = sentences[0].lower()
            hooks = ['сижу', 'стою', 'иду', 'вчера', 'сегодня', 'зашел', 'увидел', 'подумал']
            has_hook = any(hook in first_sentence for hook in hooks)
            last_sentence = sentences[-1].lower()
            conclusion_words = ['понял', 'вывод', 'итог', 'вот', 'значит', 'оказывается']
            has_conclusion = any(word in last_sentence for word in conclusion_words)
            return has_hook and has_conclusion
        except Exception as e:
            logger.error(f"Ошибка проверки структуры: {e}")
            return False
    
    async def manual_moderate(self, post_id: str, approved: bool, moderator_id: int, note: str = ""):
        try:
            if post_id in self.pending_posts:
                post = self.pending_posts[post_id]
                post.status = ModerationStatus.APPROVED if approved else ModerationStatus.REJECTED
                post.moderator_id = moderator_id
                post.moderation_note = note
                post.moderation_timestamp = time.time()
                if approved:
                    self.approved_history.append({
                        'id': post_id,
                        'hash': hashlib.md5(post.caption.encode()).hexdigest(),
                        'timestamp': time.time()
                    })
                    if len(self.approved_history) > 100:
                        self.approved_history = self.approved_history[-100:]
                else:
                    self.rejected_history.append({
                        'id': post_id,
                        'note': note,
                        'timestamp': time.time()
                    })
                return True
            return False
        except Exception as e:
            logger.error(f"Ошибка ручной модерации: {e}")
            return False

moderator = ContentModerator()

# ===== ОБРАБОТЧИК ОЧЕРЕДИ =====

async def send_post(chat_id, photo_url=None, caption=None):
    try:
        if not photo_url:
            photo_url = await get_random_photo()
        
        if not photo_url:
            logger.error("Не удалось найти фото")
            return False
        
        if not is_photo_valid(photo_url):
            logger.warning(f"Фото не прошло проверку: {photo_url[:60]}...")
            return False
        
        if not caption:
            caption = generate_caption()
            caption = clean_text(caption)
            caption = truncate_by_sentences(caption, max_length=1023)
            validated, error = validate_caption(caption, min_length=500, max_length=1023)
            if validated:
                caption = validated
            else:
                caption = clean_text(get_fallback_caption())
                caption = truncate_by_sentences(caption, max_length=1023)
                validated, error = validate_caption(caption, min_length=500, max_length=1023)
                if validated:
                    caption = validated
        
        if not caption:
            await bot.send_photo(chat_id=chat_id, photo=photo_url)
            logger.info(f"Фото (без подписи) отправлено в чат {chat_id}")
            return True
        
        if len(caption) > 1024:
            caption = truncate_by_sentences(caption, max_length=1023)
        
        await bot.send_photo(
            chat_id=chat_id,
            photo=photo_url,
            caption=caption
        )
        logger.info(f"Пост отправлен в чат {chat_id}")
        return True
        
    except TelegramAPIError as e:
        logger.error(f"Ошибка Telegram при отправке в {chat_id}: {e}")
        if "forbidden" in str(e).lower() or "chat not found" in str(e).lower():
            users_list = load_users()
            if chat_id in users_list:
                users_list.remove(chat_id)
                save_users(users_list)
                logger.info(f"Пользователь {chat_id} удалён из-за ошибки")
        return False
    except Exception as e:
        logger.error(f"Ошибка отправки в {chat_id}: {e}")
        return False

async def queue_processor():
    logger.info("Запущен обработчик очереди...")
    while True:
        try:
            task = await task_queue.pop(QUEUE_NAME)
            if task:
                logger.info(f"Получена задача из очереди: {task.get('id', 'unknown')}")
                if 'data' in task:
                    data = task['data']
                else:
                    data = task
                if data.get('needs_moderation', False):
                    await task_queue.push(MODERATION_QUEUE, data)
                    logger.info("Задача отправлена на модерацию")
                    continue
                await process_post_task(data)
            mod_task = await task_queue.pop(MODERATION_QUEUE)
            if mod_task:
                logger.info(f"Получена задача модерации: {mod_task.get('id', 'unknown')}")
                if 'data' in mod_task:
                    data = mod_task['data']
                else:
                    data = mod_task
                await process_moderation_task(data)
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка в обработчике очереди: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(5)

async def process_post_task(data: Dict[str, Any]):
    try:
        chat_id = data.get('chat_id')
        photo_url = data.get('photo_url')
        caption = data.get('caption')
        if not chat_id:
            logger.error("Нет chat_id в задаче")
            return
        await send_post(chat_id, photo_url, caption)
        logger.info(f"Пост отправлен в {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка обработки задачи: {e}")

async def process_moderation_task(data: Dict[str, Any]):
    try:
        post_data = data.get('post_data', {})
        if not post_data:
            post_data = data
        post_id = post_data.get('id', f"post_{int(time.time())}")
        post = PostContent(
            photo_url=post_data.get('photo_url', ''),
            caption=post_data.get('caption', ''),
            chat_id=post_data.get('chat_id', ''),
            user_id=post_data.get('user_id', 0),
            timestamp=time.time()
        )
        approved, reason = await moderator.moderate_content(post)
        if approved is True:
            post.status = ModerationStatus.AUTO_APPROVED
            logger.info(f"Пост {post_id} автоматически одобрен: {reason}")
            await task_queue.push(QUEUE_NAME, {
                'id': post_id,
                'chat_id': post.chat_id,
                'photo_url': post.photo_url,
                'caption': post.caption,
                'user_id': post.user_id,
                'timestamp': post.timestamp,
                'needs_moderation': False
            })
        elif approved is None:
            post.status = ModerationStatus.PENDING
            moderator.pending_posts[post_id] = post
            await notify_owner_for_moderation(post_id, post)
            logger.info(f"Пост {post_id} отправлен на ручную модерацию")
        else:
            post.status = ModerationStatus.REJECTED
            logger.info(f"Пост {post_id} отклонен: {reason}")
    except Exception as e:
        logger.error(f"Ошибка модерации: {e}")
        import traceback
        traceback.print_exc()

async def notify_owner_for_moderation(post_id: str, post: PostContent):
    if not OWNER_ID:
        return
    try:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"mod_approve_{post_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mod_reject_{post_id}")
            ]
        ])
        caption_preview = post.caption[:200] + "..." if len(post.caption) > 200 else post.caption
        await bot.send_message(
            chat_id=OWNER_ID,
            text=f"📋 Требуется модерация поста #{post_id}\n\n"
                 f"📸 Фото: {post.photo_url[:100]}...\n"
                 f"📝 Текст:\n{caption_preview}\n\n"
                 f"👤 Автор: {post.user_id}\n"
                 f"📢 Канал: {post.chat_id}",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления владельца: {e}")

async def generate_and_queue_post(chat_id: str, user_id: int = 0, skip_moderation: bool = False, style: str = "medium"):
    """Обёртка для обратной совместимости"""
    return await create_post_with_photo(chat_id, user_id, skip_moderation, style)

async def send_to_all_users():
    try:
        users_list = load_users()
        if not users_list:
            logger.warning("Нет пользователей для отправки")
            return
        logger.info(f"Добавление постов в очередь для {len(users_list)} пользователей...")
        
        # Определяем случайный стиль для автоматической рассылки
        styles = ["medium", "everyday", "funny", "romantic", "joke"]
        style = random.choice(styles)
        logger.info(f"Автоматический пост будет в стиле: {style}")
        
        photo_url = await get_random_photo(style)
        if not photo_url:
            logger.error("Не удалось найти фото")
            return
        
        caption = generate_caption()
        caption = clean_text(caption)
        caption = truncate_by_sentences(caption, max_length=1023)
        validated, error = validate_caption(caption, min_length=500, max_length=1023)
        if validated:
            caption = validated
        else:
            caption = clean_text(get_fallback_caption())
            caption = truncate_by_sentences(caption, max_length=1023)
            validated, error = validate_caption(caption, min_length=500, max_length=1023)
            if validated:
                caption = validated
        
        # Иногда добавляем комментарий к фото для автоматической рассылки
        if random.random() < 0.1 and DEEPSEEK_API_KEY:
            photo_comment = await analyze_photo_for_comment(photo_url)
            if photo_comment:
                caption = caption.rstrip() + "\n\n" + photo_comment
                logger.info(f"✅ Добавлен комментарий к фото в автоматической рассылке")
        
        base_post_id = f"post_{int(time.time())}"
        for chat_id in users_list:
            post_data = {
                'id': f"{base_post_id}_{chat_id}",
                'chat_id': chat_id,
                'photo_url': photo_url,
                'caption': caption,
                'user_id': 0,
                'timestamp': time.time(),
                'needs_moderation': False
            }
            await task_queue.push(QUEUE_NAME, post_data)
        
        channel_id = CHANNEL_ID
        if not channel_id or not channel_id.strip():
            channel_id = await get_channel_id()
        if channel_id:
            await task_queue.push(QUEUE_NAME, {
                'id': f"{base_post_id}_channel",
                'chat_id': channel_id,
                'photo_url': photo_url,
                'caption': caption,
                'user_id': 0,
                'timestamp': time.time(),
                'needs_moderation': False
            })
        
        logger.info(f"{len(users_list)} задач добавлены в очередь, стиль: {style}")
    except Exception as e:
        logger.error(f"Ошибка в send_to_all_users: {e}")

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

# ===== КОМАНДЫ =====

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

@dp.message(Command("photo"))
async def photo_command(message: Message):
    try:
        chat_id = message.chat.id
        user_id = message.from_user.id
        chat_type = message.chat.type
        
        if chat_type != "private":
            await message.answer("ℹ️ Эта команда работает только в личных сообщениях.")
            return
        
        if chat_id not in users:
            await message.answer("⚠️ Бот не активирован. Напишите /start")
            return
        
        # Определяем стиль для поиска (по умолчанию medium)
        args = message.text.replace("/photo", "").strip().lower()
        styles = ["short_joke", "medium", "long", "everyday", "funny", "romantic", "envy", "joke", "russia"]
        style = "medium"
        if args in styles:
            style = args
        
        # Используем новую функцию с анализом картинки
        await create_post_with_photo(str(chat_id), user_id, skip_moderation=True, style=style)
        
        await message.answer("✅ Пост с фото отправлен в очередь!\n📸 Ищем и генерируем...")
        
        logger.info(f"📸 Команда /photo от {user_id}, стиль: {style}")
        
    except Exception as e:
        logger.error(f"Ошибка в команде photo: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")

@dp.message(Command("post"))
async def post_command(message: Message):
    try:
        user_id = message.from_user.id
        chat_id = message.chat.id
        
        if user_id != OWNER_ID:
            await message.answer("⛔ Доступ запрещён. Только для владельца.")
            return
        
        if message.chat.type != "private":
            await message.answer("ℹ️ Используйте команду в личных сообщениях.")
            return
        
        # Определяем стиль для поиска
        args = message.text.replace("/post", "").strip().lower()
        styles = ["short_joke", "medium", "long", "everyday", "funny", "romantic", "envy", "joke", "russia"]
        style = "medium"
        if args in styles:
            style = args
        
        # Создаём пост
        result = await create_post_with_photo(str(chat_id), user_id, skip_moderation=True, style=style)
        
        if result:
            await message.answer("✅ Пост сгенерирован и отправлен в очередь!\n📸 Будет отправлен в ЛС и канал.")
            
            # Дублируем в канал
            if CHANNEL_ID and CHANNEL_ID.strip():
                # Создаём ещё один пост для канала
                await create_post_with_photo(str(CHANNEL_ID), user_id, skip_moderation=True, style=style)
                await message.answer("✅ Пост также добавлен в очередь для канала!")
        else:
            await message.answer("❌ Не удалось создать пост. Попробуйте позже.")
        
        logger.info(f"📝 Команда /post от владельца, стиль: {style}")
        
    except Exception as e:
        logger.error(f"Ошибка в команде post: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")

@dp.message(Command("price"))
async def set_price(message: Message):
    try:
        if message.from_user.id != OWNER_ID:
            await message.answer("⛔ Доступ запрещён. Только для владельца.")
            return
        args = message.text.replace("/price", "").strip()
        if not args:
            stars_price = broadcast_prices.get("stars", 100)
            rub_price = broadcast_prices.get("rub", 100)
            await message.answer(
                f"💰 Текущие цены рассылки:\n"
                f"⭐ Звёзды: {stars_price}\n"
                f"💳 Рубли: {rub_price} {FREEKASSA_CURRENCY}\n\n"
                f"Чтобы изменить:\n"
                f"/price stars 10 — цена в звёздах\n"
                f"/price rub 100 — цена в рублях"
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
                await message.answer("❌ Цена должна быть больше 0.")
                return
            if currency == "stars":
                broadcast_prices["stars"] = price
                save_broadcast_price(broadcast_prices)
                await message.answer(f"✅ Цена в звёздах установлена: {price} ⭐")
            elif currency == "rub":
                broadcast_prices["rub"] = price
                save_broadcast_price(broadcast_prices)
                await message.answer(f"✅ Цена в рублях установлена: {price} {FREEKASSA_CURRENCY}")
            else:
                await message.answer("❌ Укажите stars или rub")
        except ValueError:
            await message.answer("❌ Введите число")
    except Exception as e:
        logger.error(f"Ошибка в команде price: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")

# ===== КОМАНДА /BROADCAST (с поддержкой медиа) =====

broadcast_data = {}
pending_broadcasts = {}

@dp.message(Command("broadcast"))
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
                f"💰 Цена: {stars_price} ⭐ или {rub_price} {FREEKASSA_CURRENCY}\n"
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
        
        # Обновленная клавиатура с тремя кнопками
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
        
        preview_text += f"💰 Цена: {stars_price} ⭐ или {rub_price} {FREEKASSA_CURRENCY}\n"
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
        
        logger.info(f"📢 Рассылка создана для {user_id}, заказ {order_id}, медиа: {has_media}")
        
    except Exception as e:
        logger.error(f"Ошибка в команде broadcast: {e}", exc_info=True)
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
            [InlineKeyboardButton(text=f"💳 Оплатить {rub_price} {FREEKASSA_CURRENCY}", url=payment_url)],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_rub_payment_{order_id}")]
        ])
        
        preview_text = f"💳 **Оплата в рублях**\n\n"
        if text:
            preview_text += f"📝 Текст: {text[:100]}{'...' if len(text) > 100 else ''}\n"
        else:
            preview_text += f"📝 (без текста)\n"
        if has_media:
            preview_text += f"📎 С медиафайлом\n"
        preview_text += f"💰 Сумма: {rub_price} {FREEKASSA_CURRENCY}\n\n"
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

# ===== ОБРАБОТЧИКИ AURAPAY =====

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
        
        # Создаем Mini App URL с параметрами
        miniapp_url = f"{AURAPAY_MINIAPP_URL}?order_id={order_id}&user_id={user_id}&amount={rub_price}&currency=RUB"
        
        # Создаем кнопку с WebApp
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Оплатить через AuraPay", web_app=types.WebAppInfo(url=miniapp_url))],
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
                callback.message.text + "\n\n✅ ОДОБРЕНО (будет опубликовано через 5 минут)",
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
                        await asyncio.sleep(0.3)
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

# ===== ОСТАЛЬНЫЕ КОМАНДЫ =====

@dp.message(Command("start"))
async def start(msg: Message):
    try:
        chat_id = msg.chat.id
        user_id = msg.from_user.id
        chat_type = msg.chat.type
        if chat_type == "channel":
            await msg.answer("ℹ️ Я работаю в канале автоматически, команды не требуются.")
            return
        if not await check_user_can_use_command(msg):
            await msg.reply("⛔ Эта команда только для администраторов группы.")
            return
        if chat_type in ["group", "supergroup"]:
            try:
                chat_member = await bot.get_chat_member(chat_id, bot.id)
                is_admin = chat_member.status in ["administrator", "creator"]
            except:
                is_admin = False
            if not is_admin:
                await msg.answer("❌ Я должен быть администратором группы!")
                return
        if chat_id not in users:
            users.append(chat_id)
            save_users(users)
            logger.info(f"Добавлен пользователь: {chat_id}")
        await create_post_with_photo(str(chat_id), user_id, skip_moderation=True)
        channel_status = f"\n📢 Канал: {'✅ подключён' if CHANNEL_ID and CHANNEL_ID.strip() else '🔄 авто-поиск'}"
        current_schedule = load_schedule()
        times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
        stars_price = broadcast_prices.get("stars", 100)
        rub_price = broadcast_prices.get("rub", 100)
        await msg.answer(
            f"✅ Вы подписаны на рассылку!\n"
            f"📸 Уникальные посты про молодых азиаток (18-30 лет)\n"
            f"⏰ Расписание: {times}\n"
            f"{channel_status}\n"
            f"🔄 /photo - получить фото сейчас\n"
            f"⏰ /schedule - изменить расписание\n"
            f"📢 /broadcast - отправить сообщение всем (⭐ {stars_price} звёзд или 💳 {rub_price} {FREEKASSA_CURRENCY})\n"
            f"🛑 /stop - отписаться"
        )
    except Exception as e:
        logger.error(f"Ошибка в команде start: {e}")
        await msg.answer("❌ Произошла ошибка. Попробуйте позже.")

@dp.message(Command("stop"))
async def stop(msg: Message):
    try:
        chat_id = msg.chat.id
        chat_type = msg.chat.type
        if chat_type == "channel":
            await msg.answer("ℹ️ В канале отписка не требуется.")
            return
        if not await check_user_can_use_command(msg):
            await msg.reply("⛔ Только администраторы могут отключить бота.")
            return
        if chat_id in users:
            users.remove(chat_id)
            save_users(users)
            await msg.answer("🛑 Вы отписаны от рассылки")
            logger.info(f"Удалён пользователь: {chat_id}")
        else:
            await msg.answer("ℹ️ Вы и так не подписаны")
    except Exception as e:
        logger.error(f"Ошибка в команде stop: {e}")
        await msg.answer("❌ Произошла ошибка. Попробуйте позже.")

@dp.message(Command("schedule"))
async def schedule(msg: Message):
    try:
        if not await check_user_can_use_command(msg):
            await msg.reply("⛔ Только администраторы могут изменять расписание.")
            return
        if msg.from_user.id != OWNER_ID:
            await msg.answer("⛔ Доступ запрещён. Только для владельца.")
            return
        args = msg.text.replace("/schedule", "").strip()
        if not args:
            current_schedule = load_schedule()
            times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
            await msg.answer(
                f"📅 Текущее расписание: {times}\n\n"
                f"Чтобы изменить, напишите:\n"
                f"/schedule 10:00, 15:00, 22:00\n\n"
                f"Укажите от 1 до 4 времен в формате ЧЧ:ММ через запятую."
            )
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
        if not new_times:
            await msg.answer("❌ Неверный формат. Используйте: /schedule 12:00, 21:00")
            return
        if len(new_times) > 4:
            await msg.answer("❌ Максимум 4 времени.")
            return
        schedule_data["times"] = new_times
        save_schedule(schedule_data)
        times = ", ".join(new_times)
        await msg.answer(f"✅ Расписание обновлено: {times}")
    except Exception as e:
        logger.error(f"Ошибка в команде schedule: {e}")
        await msg.answer("❌ Произошла ошибка. Попробуйте позже.")

@dp.message(Command("status"))
async def status(msg: Message):
    try:
        chat_id = msg.chat.id
        chat_type = msg.chat.type
        if chat_type == "channel":
            channel_info = f"📊 Статус канала:\n"
            channel_info += f"• ID: {chat_id}\n"
            channel_info += f"• Бот: {'✅ админ' if await is_user_admin(chat_id, bot.id) else '❌ не админ'}"
            await msg.answer(channel_info)
            return
        if not await check_user_can_use_command(msg):
            await msg.reply("⛔ Только администраторы могут смотреть статус.")
            return
        is_subscribed = chat_id in users
        channel_id = CHANNEL_ID or await get_channel_id()
        current_schedule = load_schedule()
        times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
        stars_price = broadcast_prices.get("stars", 100)
        rub_price = broadcast_prices.get("rub", 100)
        status_text = (
            f"📊 Статус бота:\n"
            f"• Подписка: {'✅ Активна' if is_subscribed else '❌ Неактивна'}\n"
            f"• Всего подписчиков: {len(users)}\n"
            f"• Фото в истории: {len(history)}\n"
            f"• Расписание: {times}\n"
            f"• Канал: {'✅ ' + channel_id if channel_id else '❌ не найден'}\n"
            f"• Цена (звёзды): {stars_price} ⭐\n"
            f"• Цена (рубли): {rub_price} {FREEKASSA_CURRENCY}\n"
            f"• Канал для звёзд: {STARS_CHANNEL_ID}"
        )
        await msg.answer(status_text)
    except Exception as e:
        logger.error(f"Ошибка в команде status: {e}")
        await msg.answer("❌ Произошла ошибка. Попробуйте позже.")

@dp.message(Command("check_channel"))
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
    try:
        data = await request.post()
        data = dict(data)
        
        logger.info(f"📩 Получен webhook: {data.get('MERCHANT_ORDER_ID', 'unknown')}")
        
        if not verify_freekassa_webhook_signature(data):
            logger.warning("❌ Неверная подпись в webhook")
            return web.Response(text="Invalid signature", status=400)
        
        order_id = data.get('MERCHANT_ORDER_ID')
        status = data.get('STATUS')
        
        if status == 'SUCCESS':
            base_order_id = order_id.replace('_rub', '')
            for uid, info in broadcast_data.items():
                if info.get('order_id') == base_order_id:
                    logger.info(f"✅ Платёж {order_id} подтверждён")
                    try:
                        await bot.send_message(
                            chat_id=uid,
                            text="✅ Оплата подтверждена! Ваш заказ обрабатывается."
                        )
                    except Exception as e:
                        logger.error(f"Ошибка уведомления: {e}")
                    break
        
        return web.Response(text="OK", status=200)
        
    except Exception as e:
        logger.error(f"Ошибка в webhook: {e}")
        return web.Response(text="Error", status=500)

# ===== ЗАПУСК =====

async def main():
    try:
        logger.info("=" * 60)
        logger.info("🤖 БОТ ЗАПУЩЕН")
        logger.info("📸 /photo — для всех пользователей")
        logger.info("📝 /post — только для владельца (дублируется в канал)")
        logger.info("📢 /broadcast — платная рассылка с медиа")
        logger.info("🖼️ Анализ картинок — 15% вероятности для романтичных/смешных постов")
        logger.info("=" * 60)
        
        if FREEKASSA_SHOP_ID and FREEKASSA_SECRET1:
            port = int(os.getenv("PORT", 8080))
            app = web.Application()
            app.router.add_get("/", health_check)
            app.router.add_get("/success", success_page)
            app.router.add_get("/fail", fail_page)
            app.router.add_post('/freekassa/webhook', freekassa_webhook)
            
            # Добавляем маршруты для AuraPay
            app.router.add_post('/aurapay/webhook', aurapay_webhook)
            app.router.add_post('/api/aurapay/create', aurapay_create_payment_api)
            app.router.add_post('/api/aurapay/status', aurapay_status_api)
            app.router.add_get('/aurapay-success', success_page)
            app.router.add_get('/aurapay-fail', fail_page)
            
            # Добавляем CORS для работы с Mini App
            async def cors_middleware(request, handler):
                response = await handler(request)
                response.headers['Access-Control-Allow-Origin'] = '*'
                response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
                response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Merchant-Id, X-API-Key'
                return response
            
            app.middlewares.append(cors_middleware)
            
            async def options_handler(request):
                return web.Response(status=200, headers={
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
                    'Access-Control-Allow-Headers': 'Content-Type, X-Merchant-Id, X-API-Key'
                })
            
            app.router.add_options('/api/aurapay/create', options_handler)
            app.router.add_options('/api/aurapay/status', options_handler)
            
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
