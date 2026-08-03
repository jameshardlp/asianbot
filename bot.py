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

# Шифрование
try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

REDIS_AVAILABLE = False
try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    pass

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

FREEKASSA_MERCHANT_ID = os.getenv("FREEKASSA_MERCHANT_ID", "")
FREEKASSA_SECRET_KEY = os.getenv("FREEKASSA_SECRET_KEY", "")
FREEKASSA_API_KEY = os.getenv("FREEKASSA_API_KEY", "")
FREEKASSA_CURRENCY = os.getenv("FREEKASSA_CURRENCY", "RUB")
FREEKASSA_WEBHOOK_URL = os.getenv("FREEKASSA_WEBHOOK_URL", "")

if not BOT_TOKEN:
    logger.error("BOT_TOKEN не задан")
    sys.exit(1)

if not OWNER_ID:
    logger.warning("OWNER_ID не задан")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===== ФАЙЛЫ ДЛЯ ХРАНЕНИЯ =====
USERS_FILE = "users.json"
HISTORY_FILE = "history.json"
SCHEDULE_FILE = "schedule.json"
MEMORY_FILE = "memory.json"
BROADCAST_PRICE_FILE = "broadcast_price.json"

# ===== ШИФРОВАНИЕ =====
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")
if not ENCRYPTION_KEY and CRYPTO_AVAILABLE:
    key = Fernet.generate_key()
    ENCRYPTION_KEY = base64.urlsafe_b64encode(key).decode()
    logger.warning(f"⚠️ Сгенерирован новый ключ шифрования: {ENCRYPTION_KEY}")
    logger.warning("📌 Сохраните этот ключ в ENCRYPTION_KEY в переменных окружения!")

if CRYPTO_AVAILABLE and ENCRYPTION_KEY:
    try:
        cipher = Fernet(ENCRYPTION_KEY.encode())
    except Exception as e:
        logger.error(f"Ошибка инициализации шифрования: {e}")
        cipher = None
else:
    cipher = None

def encrypt_broadcast_data(text: str, media_type: str = "", media_file_id: str = "") -> str:
    """Шифрует данные рассылки"""
    if not CRYPTO_AVAILABLE or not cipher:
        return base64.urlsafe_b64encode(text.encode()).decode()
    
    try:
        data = {
            "text": text,
            "media_type": media_type,
            "media_file_id": media_file_id,
            "timestamp": time.time()
        }
        json_str = json.dumps(data, ensure_ascii=False)
        encrypted = cipher.encrypt(json_str.encode('utf-8'))
        return base64.urlsafe_b64encode(encrypted).decode()
    except Exception as e:
        logger.error(f"Ошибка шифрования: {e}")
        return base64.urlsafe_b64encode(text.encode()).decode()

def decrypt_broadcast_data(encrypted_data: str) -> dict:
    """Расшифровывает данные рассылки"""
    if not CRYPTO_AVAILABLE or not cipher:
        try:
            text = base64.urlsafe_b64decode(encrypted_data.encode()).decode()
            return {"text": text, "media_type": "", "media_file_id": ""}
        except:
            return {"text": encrypted_data, "media_type": "", "media_file_id": ""}
    
    try:
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
        decrypted = cipher.decrypt(encrypted_bytes)
        return json.loads(decrypted.decode('utf-8'))
    except Exception as e:
        logger.error(f"Ошибка расшифровки: {e}")
        try:
            text = base64.urlsafe_b64decode(encrypted_data.encode()).decode()
            return {"text": text, "media_type": "", "media_file_id": ""}
        except:
            return {"text": encrypted_data, "media_type": "", "media_file_id": ""}

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

# ===== ХРАНИЛИЩА ДАННЫХ =====
broadcast_data = {}
pending_broadcasts = {}

# ===== FREEKASSA - ИСПРАВЛЕННАЯ ВЕРСИЯ (ТОЛЬКО ОБЯЗАТЕЛЬНЫЕ ПАРАМЕТРЫ) =====
def generate_freekassa_signature(merchant_id: str, order_id: str, amount: str, secret_key: str) -> str:
    """
    Генерация подписи для FreeKassa
    ПОРЯДОК: merchant_id:amount:secret_key:order_id
    """
    sign_str = f"{merchant_id}:{amount}:{secret_key}:{order_id}"
    return hashlib.md5(sign_str.encode()).hexdigest()

def verify_freekassa_signature(data: dict, secret_key: str) -> bool:
    """Проверка подписи от FreeKassa для webhook"""
    required_fields = ['MERCHANT_ID', 'AMOUNT', 'MERCHANT_ORDER_ID', 'SIGN']
    for field in required_fields:
        if field not in data:
            return False
    
    merchant_id = data.get('MERCHANT_ID')
    amount = data.get('AMOUNT')
    order_id = data.get('MERCHANT_ORDER_ID')
    sign = data.get('SIGN')
    
    sign_str = f"{merchant_id}:{amount}:{secret_key}:{order_id}"
    expected_sign = hashlib.md5(sign_str.encode()).hexdigest()
    
    return sign == expected_sign

def create_freekassa_payment_link(amount: float, order_id: str, description: str = "") -> str:
    """
    Создание МИНИМАЛЬНОЙ правильной ссылки для оплаты через FreeKassa
    Только обязательные параметры: m, oa, currency, o, s
    """
    if not FREEKASSA_MERCHANT_ID or not FREEKASSA_SECRET_KEY:
        logger.error("FreeKassa не настроен")
        return ""
    
    # Сумма должна быть целым числом
    amount_int = int(amount)
    
    # Формируем подпись
    signature = generate_freekassa_signature(
        FREEKASSA_MERCHANT_ID,
        order_id,
        str(amount_int),
        FREEKASSA_SECRET_KEY
    )
    
    # ✅ ТОЛЬКО ОБЯЗАТЕЛЬНЫЕ ПАРАМЕТРЫ
    params = {
        "m": FREEKASSA_MERCHANT_ID,      # ID мерчанта
        "oa": str(amount_int),            # Сумма (целое число)
        "currency": FREEKASSA_CURRENCY,   # Валюта
        "o": order_id,                    # ID заказа
        "s": signature,                   # Подпись
    }
    
    # Опционально: добавляем описание (необязательно)
    if description:
        params["description"] = description[:255]
    
    query_string = urlencode(params)
    
    # ✅ ПРАВИЛЬНЫЙ ДОМЕН
    return f"https://pay.fk.money/?{query_string}"

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

# ===== РАБОТА С ФАЙЛАМИ =====
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

def load_schedule():
    try:
        with open(SCHEDULE_FILE, "r") as f:
            data = json.load(f)
            if not data or not data.get("times"):
                return {"times": ["10:00", "12:00", "15:00", "18:00", "21:00"]}
            return data
    except:
        return {"times": ["10:00", "12:00", "15:00", "18:00", "21:00"]}

def save_schedule(schedule_data):
    try:
        with open(SCHEDULE_FILE, "w") as f:
            json.dump(schedule_data, f)
        return True
    except:
        return False

schedule_data = load_schedule()

# ===== ГЕНЕРАЦИЯ ТЕКСТОВ =====
def clean_text(text: str) -> str:
    if not text:
        return ''
    text = text.replace('—', '-').replace('–', '-')
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def truncate_by_sentences(text: str, max_length: int = 1023) -> str:
    if not text:
        return ''
    text = text.strip()
    if len(text) <= max_length:
        return text
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
    return ' '.join(result).strip()

def get_fallback_caption() -> str:
    all_fallbacks = [
        "Сижу в кафе в Бангкоке, пью кофе, смотрю на прохожих. И вдруг понимаю — я уже полгода здесь, а всё ещё удивляюсь, как тайцы умудряются улыбаться даже в пробках.",
        "Вчера я решил, что пора завязывать с дошираками и начать готовить сам. Купил овощи, рис, приправы. Стою на кухне, смотрю на всё это богатство и понимаю — я даже не знаю, с чего начать.",
        "Сегодня утром я чуть не опоздал на встречу. Выхожу из дома, а мой мотоцикл не заводится. Я начинаю паниковать, дёргать ручки, пинать колёса.",
    ]
    return random.choice(all_fallbacks)

async def generate_caption(style: str) -> str:
    if not DEEPSEEK_API_KEY:
        return get_fallback_caption()
    
    try:
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Ты — генератор текстов для постов в Telegram."},
                {"role": "user", "content": f"Создай пост в стиле {style}"}
            ],
            "temperature": 0.9,
            "max_tokens": 500
        }
        
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            caption = result["choices"][0]["message"]["content"].strip()
            if caption and len(caption) > 20:
                return caption
    except Exception as e:
        logger.error(f"Ошибка генерации: {e}")
    
    return get_fallback_caption()

# ===== КОМАНДЫ БОТА =====
@dp.message(Command("broadcast"))
async def broadcast_command(message: Message):
    try:
        if message.chat.type != "private":
            await message.answer("ℹ️ Эта команда работает только в личных сообщениях с ботом.")
            return
        
        user_id = message.from_user.id
        chat_id = message.chat.id
        
        if not FREEKASSA_MERCHANT_ID or not FREEKASSA_SECRET_KEY:
            await message.answer(
                "❌ Платёжная система не настроена.\n"
                "Администратор должен настроить FreeKassa в переменных окружения:\n"
                "FREEKASSA_MERCHANT_ID, FREEKASSA_SECRET_KEY"
            )
            return
        
        has_media = False
        media_type = None
        media_file_id = None
        text = ""
        
        if message.text:
            text = message.text.replace("/broadcast", "").strip()
        
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
        
        if not text and not has_media:
            current_price = load_broadcast_price()
            await message.answer(
                f"📢 Использование: /broadcast Ваше сообщение\n\n"
                f"💰 Стоимость: {current_price} {FREEKASSA_CURRENCY}\n"
                f"💳 Оплата через FreeKassa\n\n"
                f"После оплаты сообщение будет отправлено на модерацию."
            )
            return
        
        if text and text.startswith("/broadcast"):
            text = text.replace("/broadcast", "").strip()
        
        current_price = load_broadcast_price()
        order_id = f"broadcast_{user_id}_{int(time.time())}"
        
        # Шифруем данные
        encrypted_text = encrypt_broadcast_data(
            text=text,
            media_type=media_type or "",
            media_file_id=media_file_id or ""
        )
        
        broadcast_data[user_id] = {
            'text': text,
            'has_media': has_media,
            'media_type': media_type,
            'media_file_id': media_file_id,
            'timestamp': time.time(),
            'chat_id': chat_id,
            'user_id': user_id,
            'order_id': order_id,
            'price': current_price,
            'encrypted_data': encrypted_text
        }
        
        # ✅ ПРАВИЛЬНАЯ ССЫЛКА (ТОЛЬКО ОБЯЗАТЕЛЬНЫЕ ПАРАМЕТРЫ)
        payment_url = create_freekassa_payment_link(
            current_price, 
            order_id, 
            "Рассылка в Telegram"
        )
        
        # Логируем для отладки
        logger.info(f"🔗 Ссылка для оплаты: {payment_url}")
        logger.info(f"📋 Merchant: {FREEKASSA_MERCHANT_ID}, Order: {order_id}, Amount: {current_price}")
        
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
            f"📝 Текст: {text[:100]}{'...' if len(text) > 100 else ''}\n"
            f"{'📎 С медиафайлом' if has_media else ''}\n\n"
            f"🔐 Данные зашифрованы и защищены.\n"
            f"💳 Нажмите кнопку ниже для оплаты.",
            reply_markup=keyboard
        )
        
        logger.info(f"💳 Счёт создан для пользователя {user_id}, заказ {order_id}")
        
    except Exception as e:
        logger.error(f"Ошибка в команде broadcast: {e}", exc_info=True)
        await message.answer(f"❌ Произошла ошибка: {str(e)[:100]}")

@dp.callback_query(lambda c: c.data and c.data.startswith('check_payment_'))
async def check_payment(callback: CallbackQuery):
    try:
        order_id = callback.data.replace('check_payment_', '')
        user_id = callback.from_user.id
        
        if user_id not in broadcast_data:
            await callback.answer("❌ Данные о заказе не найдены", show_alert=True)
            return
        
        broadcast_info = broadcast_data[user_id]
        if broadcast_info.get('order_id') != order_id:
            await callback.answer("❌ Неверный заказ", show_alert=True)
            return
        
        await callback.answer("⏳ Проверяю статус платежа...")
        
        payment_status = await check_freekassa_payment_status(order_id)
        
        if payment_status:
            if payment_status.get('status') == 'paid':
                await process_broadcast_payment(callback, user_id, broadcast_info)
            else:
                await callback.message.answer(
                    "❌ Платёж ещё не оплачен.\n"
                    "Пожалуйста, оплатите счёт и нажмите 'Проверить оплату' снова.\n"
                    "Если вы уже оплатили, подождите 1-2 минуты."
                )
        else:
            await callback.message.answer(
                "⚠️ Не удалось проверить статус платежа.\n"
                "Попробуйте ещё раз через несколько минут."
            )
        
    except Exception as e:
        logger.error(f"Ошибка проверки платежа: {e}")
        await callback.answer("❌ Ошибка при проверке", show_alert=True)

async def process_broadcast_payment(callback: CallbackQuery, user_id: int, broadcast_info: dict):
    try:
        text = broadcast_info.get('text', '')
        has_media = broadcast_info.get('has_media', False)
        media_type = broadcast_info.get('media_type')
        media_file_id = broadcast_info.get('media_file_id')
        
        broadcast_id = f"broadcast_{int(time.time())}_{hashlib.md5(str(broadcast_info).encode()).hexdigest()[:8]}"
        
        pending_broadcasts[broadcast_id] = {
            'text': text,
            'has_media': has_media,
            'media_type': media_type,
            'media_file_id': media_file_id,
            'user_id': user_id,
            'timestamp': time.time(),
            'chat_id': broadcast_info.get('chat_id'),
            'price': broadcast_info.get('price', broadcast_price)
        }
        
        del broadcast_data[user_id]
        
        await send_broadcast_for_moderation(broadcast_id, pending_broadcasts[broadcast_id])
        
        await callback.message.edit_text(
            f"✅ Оплата подтверждена! Сообщение отправлено на модерацию.\n"
            f"📝 Текст: {text[:100]}{'...' if len(text) > 100 else ''}\n"
            f"{'📎 С медиафайлом' if has_media else ''}\n\n"
            f"⏳ Ожидайте подтверждения от администратора."
        )
        await callback.answer("✅ Оплата подтверждена!", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка обработки оплаты: {e}")
        await callback.message.answer(f"❌ Ошибка: {str(e)[:100]}")
        await callback.answer("❌ Ошибка", show_alert=True)

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
        
        preview_text = f"📋 Новая рассылка на модерацию #{broadcast_id}\n\n"
        preview_text += f"👤 Заказчик ID: {user_id}\n"
        preview_text += f"💰 Оплачено: {broadcast_info.get('price', broadcast_price)} {FREEKASSA_CURRENCY}\n"
        
        if text:
            preview_text += f"\n📝 Текст:\n{text[:300]}{'...' if len(text) > 300 else ''}\n"
        else:
            preview_text += f"\n📝 Текст: (без текста)\n"
        
        if has_media:
            media_names = {
                "photo": "📸 Фото",
                "video": "🎬 Видео",
                "document": "📄 Документ",
                "animation": "🎥 GIF"
            }
            preview_text += f"\n📎 {media_names.get(media_type, 'Медиафайл')} (будет отправлено)\n"
        
        preview_text += f"\n⏳ После подтверждения будет отправлено всем подписчикам."
        
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
        else:
            await bot.send_message(
                chat_id=OWNER_ID,
                text=preview_text,
                reply_markup=keyboard
            )
        
        logger.info(f"Рассылка {broadcast_id} отправлена на модерацию")
    except Exception as e:
        logger.error(f"Ошибка отправки на модерацию: {e}")

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
            await callback.answer("✅ Сообщение одобрено", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n✅ ОДОБРЕНО",
                reply_markup=None
            )
            
            text = broadcast_info.get('text', '')
            has_media = broadcast_info.get('has_media', False)
            media_type = broadcast_info.get('media_type')
            media_file_id = broadcast_info.get('media_file_id')
            users_list = load_users()
            
            sent_count = 0
            failed_count = 0
            
            # Отправка подписчикам
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
            
            # Отправка в канал
            try:
                channel_id = CHANNEL_ID
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
                    else:
                        if text:
                            await bot.send_message(chat_id=channel_id, text=text)
                    logger.info(f"✅ Отправлено в канал {channel_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки в канал: {e}")
            
            del pending_broadcasts[broadcast_id]
            
            # Уведомление заказчику
            try:
                user_id = broadcast_info.get('user_id')
                if user_id:
                    await bot.send_message(
                        chat_id=user_id,
                        text=f"✅ Ваше сообщение опубликовано!\n"
                             f"📨 Отправлено: {sent_count} подписчикам"
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

async def get_channel_id() -> Optional[str]:
    if CHANNEL_ID and CHANNEL_ID.strip():
        return CHANNEL_ID.strip()
    return None

# ===== WEBHOOK =====
async def freekassa_webhook(request):
    try:
        data = await request.post()
        data = dict(data)
        
        logger.info(f"📩 Получен webhook от FreeKassa: {data}")
        
        if not verify_freekassa_signature(data, FREEKASSA_SECRET_KEY):
            logger.warning("❌ Неверная подпись в webhook")
            return web.Response(text="Invalid signature", status=400)
        
        order_id = data.get('MERCHANT_ORDER_ID')
        status = data.get('STATUS')
        
        if status != 'SUCCESS':
            logger.info(f"Платёж {order_id} не успешен: {status}")
            return web.Response(text="OK", status=200)
        
        # Обработка успешного платежа
        for uid, info in broadcast_data.items():
            if info.get('order_id') == order_id:
                logger.info(f"✅ Платёж {order_id} подтверждён для пользователя {uid}")
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
        logger.info("🤖 Бот запущен с оплатой через FreeKassa")
        logger.info(f"📊 Подписчиков: {len(load_users())}")
        logger.info(f"💰 Цена: {load_broadcast_price()} {FREEKASSA_CURRENCY}")
        logger.info(f"💳 Merchant ID: {FREEKASSA_MERCHANT_ID[:10] if FREEKASSA_MERCHANT_ID else '❌ не задан'}")
        logger.info(f"🔐 Шифрование: {'✅ включено' if CRYPTO_AVAILABLE and cipher else '❌ выключено'}")
        
        # Запуск webhook сервера
        if FREEKASSA_WEBHOOK_URL:
            app = web.Application()
            app.router.add_post('/freekassa/webhook', freekassa_webhook)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', 8080)
            await site.start()
            logger.info(f"🌐 Webhook запущен на порту 8080")
            logger.info(f"📌 URL: {FREEKASSA_WEBHOOK_URL}/freekassa/webhook")
        
        logger.info("=" * 60)
        
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("🔄 Webhook удалён")
        except Exception as e:
            logger.warning(f"Ошибка webhook: {e}")
        
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
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
