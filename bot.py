import asyncio
import os
import sys
import hashlib
import json
import time
import logging
import requests
from typing import Optional, List
from urllib.parse import urlencode

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiohttp import web

# ===== НАСТРОЙКА ЛОГИРОВАНИЯ (скрываем секретные данные) =====
class SensitiveFilter(logging.Filter):
    def filter(self, record):
        if hasattr(record, 'msg'):
            msg = record.msg
            if 'SECRET' in msg or 'BOT_TOKEN' in msg:
                return False
        return True

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logger.addFilter(SensitiveFilter())

# ===== КОНФИГУРАЦИЯ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_ID = int(os.getenv("OWNER_ID", 0))

BOT_LINK = "https://t.me/asianpicbot"

FREEKASSA_SHOP_ID = os.getenv("FREEKASSA_SHOP_ID", "")
FREEKASSA_SECRET1 = os.getenv("FREEKASSA_SECRET1", "")
FREEKASSA_SECRET2 = os.getenv("FREEKASSA_SECRET2", "")
FREEKASSA_API_KEY = os.getenv("FREEKASSA_API_KEY", "")
FREEKASSA_CURRENCY = os.getenv("FREEKASSA_CURRENCY", "RUB")

PRICE_RUB = 100
PRICE_STARS = 10

if not BOT_TOKEN:
    logger.error("BOT_TOKEN не задан")
    sys.exit(1)

if not OWNER_ID:
    logger.warning("OWNER_ID не задан")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===== ХРАНИЛИЩА =====
broadcast_data = {}
pending_broadcasts = {}
BROADCAST_PRICE_FILE = "broadcast_price.json"
TEMP_USERS_FILE = "temp_users.json"

# ===== РАБОТА С ВРЕМЕННЫМИ ПОЛЬЗОВАТЕЛЯМИ =====
def load_temp_users() -> dict:
    try:
        with open(TEMP_USERS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_temp_users(temp_users: dict):
    try:
        with open(TEMP_USERS_FILE, "w") as f:
            json.dump(temp_users, f)
    except Exception as e:
        logger.error(f"Ошибка сохранения: {e}")

def add_temp_user(user_id: str, broadcast_id: str):
    temp_users = load_temp_users()
    temp_users[user_id] = {"added_at": time.time(), "broadcast_id": broadcast_id}
    save_temp_users(temp_users)

def remove_temp_user(user_id: str):
    temp_users = load_temp_users()
    if user_id in temp_users:
        del temp_users[user_id]
        save_temp_users(temp_users)

def get_active_users() -> List[str]:
    temp_users = load_temp_users()
    return list(temp_users.keys())

def load_broadcast_price() -> dict:
    try:
        with open(BROADCAST_PRICE_FILE, "r") as f:
            data = json.load(f)
            return data
    except:
        return {"rub": 100, "stars": 10}

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
    """Генерация подписи с валютой (использует SECRET1)"""
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
    
    # ✅ Убраны параметры us и uf
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

# ===== СТРАНИЦЫ ДЛЯ ПОЛЬЗОВАТЕЛЯ =====
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
            <p>Ваш пост будет опубликован после проверки администратором.</p>
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

# ===== КОМАНДА /START =====
@dp.message(Command("start"))
async def start_command(message: Message):
    user_id = message.from_user.id
    is_owner = (user_id == OWNER_ID)
    
    commands = "📢 **Доступные команды:**\n\n"
    commands += "• `/photo` — отправить фото с подписью\n"
    commands += "• `/broadcast` — платная рассылка\n"
    
    if is_owner:
        commands += "\n🔑 **Команды владельца:**\n"
        commands += "• `/post` — отправить пост в канал\n"
        commands += "• `/price` — цена в рублях\n"
        commands += "• `/price_star` — цена в звёздах\n"
        commands += "• `/users` — список активных пользователей\n"
        commands += "• `/cleanup` — очистка пользователей\n"
        commands += "• `/testfreekassa` — тест FreeKassa\n"
    
    await message.answer(commands, parse_mode="Markdown")

# ===== БЕСПЛАТНАЯ КОМАНДА /PHOTO =====
@dp.message(Command("photo"))
async def photo_command(message: Message):
    try:
        if message.chat.type != "private":
            await message.answer("ℹ️ Эта команда работает только в личных сообщениях.")
            return
        
        if not message.photo:
            await message.answer(
                "📸 **Отправьте фото с подписью**\n\n"
                "Просто отправьте фото с текстом под ним.\n"
                "Бот перешлёт его вам обратно.",
                parse_mode="Markdown"
            )
            return
        
        photo = message.photo[-1]
        caption = message.caption or "Без подписи"
        
        await message.answer_photo(
            photo=photo.file_id,
            caption=f"✅ **Ваше фото получено!**\n\n📝 {caption}",
            parse_mode="Markdown"
        )
        
        logger.info(f"📸 Команда /photo от пользователя {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Ошибка в photo: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")

# ===== БЕСПЛАТНАЯ КОМАНДА /POST =====
@dp.message(Command("post"))
async def post_command(message: Message):
    try:
        user_id = message.from_user.id
        if user_id != OWNER_ID:
            await message.answer("⛔ Доступ запрещён. Только для владельца.")
            return
        
        if message.chat.type != "private":
            await message.answer("ℹ️ Используйте команду в личных сообщениях.")
            return
        
        text = message.text.replace("/post", "").strip()
        if not text:
            await message.answer(
                "📝 **Использование:** /post Текст поста\n\n"
                "Пост будет отправлен в ЛС владельцу и в канал.",
                parse_mode="Markdown"
            )
            return
        
        await message.answer(
            f"✅ **Пост отправлен в канал!**\n\n"
            f"📄 {text}"
        )
        
        if CHANNEL_ID:
            try:
                await bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=f"📢 {text}"
                )
                logger.info(f"📝 Пост отправлен в канал {CHANNEL_ID}")
            except Exception as e:
                logger.error(f"Ошибка отправки в канал: {e}")
                await message.answer("❌ Не удалось отправить пост в канал.")
        else:
            await message.answer("⚠️ Канал не настроен. Пост отправлен только в ЛС.")
        
    except Exception as e:
        logger.error(f"Ошибка в post: {e}")
        await message.answer("❌ Произошла ошибка.")

# ===== ПЛАТНАЯ КОМАНДА /BROADCAST =====
@dp.message(Command("broadcast"))
async def broadcast_command(message: Message):
    try:
        if message.chat.type != "private":
            await message.answer("ℹ️ Эта команда работает только в личных сообщениях.")
            return
        
        user_id = message.from_user.id
        
        if not FREEKASSA_SHOP_ID or not FREEKASSA_SECRET1:
            await message.answer("❌ Платёжная система не настроена.")
            return
        
        text = message.text.replace("/broadcast", "").strip() if message.text else ""
        has_media = False
        media_type = None
        media_file_id = None
        
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
            rub_price = broadcast_prices.get("rub", 100)
            stars_price = broadcast_prices.get("stars", 10)
            await message.answer(
                f"📢 **Платная рассылка**\n\n"
                f"Отправьте сообщение с текстом или медиа.\n\n"
                f"💰 Цена: {rub_price} RUB или {stars_price} ⭐\n"
                f"💳 Оплата через FreeKassa"
            )
            return
        
        rub_price = broadcast_prices.get("rub", 100)
        stars_price = broadcast_prices.get("stars", 10)
        order_id = f"broadcast_{user_id}_{int(time.time())}"
        
        broadcast_data[user_id] = {
            'text': text,
            'has_media': has_media,
            'media_type': media_type,
            'media_file_id': media_file_id,
            'timestamp': time.time(),
            'chat_id': message.chat.id,
            'user_id': user_id,
            'order_id': order_id,
            'price_rub': rub_price,
            'price_stars': stars_price
        }
        
        rub_link = create_freekassa_payment_link(rub_price, f"{order_id}_rub", f"Рассылка RUB")
        stars_link = create_freekassa_payment_link(stars_price, f"{order_id}_stars", f"Рассылка ⭐")
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 Оплатить {rub_price} RUB", url=rub_link)],
            [InlineKeyboardButton(text=f"⭐ Оплатить {stars_price} звёзд", url=stars_link)],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_payment_{order_id}")]
        ])
        
        preview = f"📢 **Платная рассылка**\n\n"
        preview += f"📝 {text[:200]}{'...' if len(text) > 200 else ''}\n"
        if has_media:
            preview += f"\n📎 С медиафайлом\n"
        preview += f"\n💰 Цена: {rub_price} RUB или {stars_price} ⭐"
        
        if has_media and media_file_id:
            if media_type == "photo":
                await message.answer_photo(
                    photo=media_file_id,
                    caption=preview,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            elif media_type == "video":
                await message.answer_video(
                    video=media_file_id,
                    caption=preview,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            else:
                await message.answer(
                    preview + "\n\n📎 Медиафайл прикреплён",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
        else:
            await message.answer(
                preview,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        
        logger.info(f"💳 Рассылка создана для {user_id}, заказ {order_id}")
        
    except Exception as e:
        logger.error(f"Ошибка в broadcast: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка: {str(e)[:100]}")

# ===== ОБРАБОТЧИК ПРОВЕРКИ ОПЛАТЫ =====
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
        
        payment_status = await check_freekassa_payment_status(f"{order_id}_rub")
        if not payment_status:
            payment_status = await check_freekassa_payment_status(f"{order_id}_stars")
        
        if payment_status and payment_status.get('status') == 'paid':
            await process_broadcast_payment(callback, user_id, broadcast_info)
        else:
            await callback.message.answer(
                "❌ Платёж ещё не оплачен.\n"
                "Оплатите счёт и нажмите 'Проверить оплату' снова."
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
        
        add_temp_user(str(user_id), broadcast_id)
        
        pending_broadcasts[broadcast_id] = {
            'text': text,
            'has_media': has_media,
            'media_type': media_type,
            'media_file_id': media_file_id,
            'user_id': user_id,
            'timestamp': time.time(),
            'chat_id': broadcast_info.get('chat_id'),
            'price_rub': broadcast_info.get('price_rub'),
            'price_stars': broadcast_info.get('price_stars')
        }
        
        del broadcast_data[user_id]
        
        await send_broadcast_for_moderation(broadcast_id, pending_broadcasts[broadcast_id])
        
        await callback.message.edit_text(
            f"✅ Оплата подтверждена!\n"
            f"📝 {text[:100]}{'...' if len(text) > 100 else ''}\n\n"
            f"⏳ Сообщение отправлено на модерацию."
        )
        await callback.answer("✅ Оплата подтверждена!", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка обработки оплаты: {e}")
        await callback.message.answer(f"❌ Ошибка: {str(e)[:100]}")

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
        
        preview_text = f"📋 **Новая рассылка на модерацию** #{broadcast_id}\n\n"
        preview_text += f"👤 Заказчик: {user_id}\n"
        preview_text += f"💰 Оплачено: {broadcast_info.get('price_rub', 0)} RUB\n\n"
        
        if text:
            preview_text += f"📝 Текст:\n{text[:500]}{'...' if len(text) > 500 else ''}\n"
        
        if has_media:
            preview_text += f"\n📎 С медиафайлом\n"
        
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
            await callback.answer("✅ Сообщение одобрено", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n✅ ОДОБРЕНО (отправляется подписчикам)",
                reply_markup=None
            )
            
            text = broadcast_info.get('text', '')
            has_media = broadcast_info.get('has_media', False)
            media_type = broadcast_info.get('media_type')
            media_file_id = broadcast_info.get('media_file_id')
            
            users_list = get_active_users()
            
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
                    else:
                        if text:
                            await bot.send_message(chat_id=chat_id, text=text)
                    
                    sent_count += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    logger.error(f"Ошибка отправки {chat_id}: {e}")
                    failed_count += 1
                    remove_temp_user(str(chat_id))
            
            if CHANNEL_ID:
                try:
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
                    else:
                        if text:
                            await bot.send_message(chat_id=CHANNEL_ID, text=text)
                    logger.info(f"✅ Отправлено в канал")
                except Exception as e:
                    logger.error(f"Ошибка канала: {e}")
            
            user_id = broadcast_info.get('user_id')
            if user_id:
                remove_temp_user(str(user_id))
            
            del pending_broadcasts[broadcast_id]
            
            try:
                if user_id:
                    await bot.send_message(
                        chat_id=user_id,
                        text=f"✅ Ваше сообщение опубликовано!\n📨 Отправлено: {sent_count} подписчикам"
                    )
            except Exception as e:
                logger.error(f"Ошибка уведомления: {e}")
                
        else:
            await callback.answer("❌ Сообщение отклонено", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n❌ ОТКЛОНЕНО",
                reply_markup=None
            )
            user_id = broadcast_info.get('user_id')
            if user_id:
                remove_temp_user(str(user_id))
            
            if broadcast_id in pending_broadcasts:
                del pending_broadcasts[broadcast_id]
    except Exception as e:
        logger.error(f"Ошибка модерации: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

# ===== КОМАНДЫ ВЛАДЕЛЬЦА =====
@dp.message(Command("price"))
async def set_price_rub(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Доступ запрещён.")
        return
    args = message.text.replace("/price", "").strip()
    if not args:
        await message.answer(f"💰 Текущая цена: {broadcast_prices.get('rub', 100)} RUB")
        return
    try:
        price = int(args)
        if price < 1:
            await message.answer("❌ Цена должна быть больше 0.")
            return
        broadcast_prices['rub'] = price
        save_broadcast_price(broadcast_prices)
        await message.answer(f"✅ Цена в рублях: {price} RUB")
    except ValueError:
        await message.answer("❌ Введите число")

@dp.message(Command("price_star"))
async def set_price_stars(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Доступ запрещён.")
        return
    args = message.text.replace("/price_star", "").strip()
    if not args:
        await message.answer(f"⭐ Текущая цена: {broadcast_prices.get('stars', 10)} ⭐")
        return
    try:
        price = int(args)
        if price < 1:
            await message.answer("❌ Цена должна быть больше 0.")
            return
        broadcast_prices['stars'] = price
        save_broadcast_price(broadcast_prices)
        await message.answer(f"✅ Цена в звёздах: {price} ⭐")
    except ValueError:
        await message.answer("❌ Введите число")

@dp.message(Command("users"))
async def list_active_users(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Доступ запрещён.")
        return
    
    temp_users = load_temp_users()
    if not temp_users:
        await message.answer("📊 Нет активных пользователей")
        return
    
    user_list = []
    for user_id, data in temp_users.items():
        added_time = data.get("added_at", 0)
        hours_ago = (time.time() - added_time) / 3600
        remaining = max(0, 24 - hours_ago)
        user_list.append(f"• `{user_id}` (осталось {remaining:.1f} ч)")
    
    await message.answer(
        f"📊 **Активные пользователи**\n\n"
        f"Всего: {len(temp_users)}\n\n"
        f"{chr(10).join(user_list[:20])}",
        parse_mode="Markdown"
    )

@dp.message(Command("cleanup"))
async def cleanup_users(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Доступ запрещён.")
        return
    
    temp_users = load_temp_users()
    current_time = time.time()
    expired = []
    
    for user_id, data in temp_users.items():
        if current_time - data.get("added_at", 0) > 24 * 3600:
            expired.append(user_id)
    
    for user_id in expired:
        remove_temp_user(user_id)
    
    await message.answer(f"🗑️ Удалено: {len(expired)} пользователей")

@dp.message(Command("testfreekassa"))
async def test_freekassa(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Доступ запрещён.")
        return
    
    shop_id = FREEKASSA_SHOP_ID
    if not shop_id:
        await message.answer("❌ FreeKassa не настроен!")
        return
    
    test_amount = 100
    test_order = f"test_{int(time.time())}"
    
    sign_str = f"{shop_id}:{test_amount}:{FREEKASSA_SECRET1}:{FREEKASSA_CURRENCY}:{test_order}"
    signature = hashlib.md5(sign_str.encode()).hexdigest()
    
    link = f"https://pay.fk.money/?m={shop_id}&oa={test_amount}&currency={FREEKASSA_CURRENCY}&o={test_order}&s={signature}"
    
    await message.answer(
        f"🧪 **Тест FreeKassa**\n\n"
        f"📋 Shop ID: `{shop_id}`\n"
        f"💰 Сумма: `{test_amount}`\n\n"
        f"🔗 **Ссылка:**\n`{link}`",
        parse_mode="Markdown"
    )

# ===== WEBHOOK =====
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
            base_order_id = order_id.replace('_rub', '').replace('_stars', '')
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

# ===== ФОНОВАЯ ЗАДАЧА =====
async def cleanup_task():
    while True:
        try:
            temp_users = load_temp_users()
            current_time = time.time()
            expired = []
            
            for user_id, data in temp_users.items():
                if current_time - data.get("added_at", 0) > 24 * 3600:
                    expired.append(user_id)
            
            for user_id in expired:
                remove_temp_user(user_id)
            
            if expired:
                logger.info(f"🗑️ Автоочистка: удалено {len(expired)} пользователей")
            
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"Ошибка очистки: {e}")
            await asyncio.sleep(3600)

# ===== ЗАПУСК =====
async def main():
    try:
        logger.info("=" * 60)
        logger.info("🤖 БОТ ЗАПУЩЕН")
        logger.info(f"💰 Цена: {broadcast_prices.get('rub', 100)} RUB, {broadcast_prices.get('stars', 10)} ⭐")
        logger.info(f"👤 Владелец: {OWNER_ID}")
        logger.info("=" * 60)
        
        asyncio.create_task(cleanup_task())
        
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
        
        await bot.delete_webhook(drop_pending_updates=True)
        
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
            skip_updates=True,
            polling_timeout=30
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен")
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}")
        sys.exit(1)
