import asyncio
import os
import sys
import hashlib
import json
import time
import base64
from urllib.parse import urlencode
import logging
import requests
from typing import Optional, Dict, Any, List, Tuple

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===== КОНФИГУРАЦИЯ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_ID = int(os.getenv("OWNER_ID", 0))

FREEKASSA_MERCHANT_ID = os.getenv("FREEKASSA_MERCHANT_ID", "")
FREEKASSA_SECRET_KEY_S1 = os.getenv("FREEKASSA_SECRET_KEY_S1", "")  # S1 - 15 символов
FREEKASSA_SECRET_KEY_S2 = os.getenv("FREEKASSA_SECRET_KEY_S2", "")  # S2 - 15 символов
FREEKASSA_API_KEY = os.getenv("FREEKASSA_API_KEY", "")
FREEKASSA_CURRENCY = os.getenv("FREEKASSA_CURRENCY", "RUB")
FREEKASSA_WEBHOOK_URL = os.getenv("FREEKASSA_WEBHOOK_URL", "")

if not BOT_TOKEN:
    logger.error("BOT_TOKEN не задан")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===== ХРАНИЛИЩА =====
broadcast_data = {}
pending_broadcasts = {}
BROADCAST_PRICE_FILE = "broadcast_price.json"
USERS_FILE = "users.json"

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

# ===== FREEKASSA =====
def generate_freekassa_signature(merchant_id: str, amount: str, order_id: str) -> str:
    """
    Генерация подписи для FreeKassa
    ПОРЯДОК: merchant_id:amount:S1:order_id
    """
    sign_str = f"{merchant_id}:{amount}:{FREEKASSA_SECRET_KEY_S1}:{order_id}"
    logger.info(f"🔑 Строка для подписи: {sign_str}")
    signature = hashlib.md5(sign_str.encode()).hexdigest()
    logger.info(f"🔑 Подпись (MD5): {signature}")
    return signature

def verify_freekassa_webhook_signature(data: dict) -> bool:
    """
    Проверка подписи от FreeKassa для webhook
    Использует S2
    """
    required_fields = ['MERCHANT_ID', 'AMOUNT', 'MERCHANT_ORDER_ID', 'SIGN']
    for field in required_fields:
        if field not in data:
            logger.warning(f"Отсутствует поле: {field}")
            return False
    
    merchant_id = str(data.get('MERCHANT_ID'))
    amount = str(data.get('AMOUNT'))
    order_id = str(data.get('MERCHANT_ORDER_ID'))
    sign = str(data.get('SIGN'))
    
    sign_str = f"{merchant_id}:{amount}:{FREEKASSA_SECRET_KEY_S2}:{order_id}"
    expected_sign = hashlib.md5(sign_str.encode()).hexdigest()
    
    logger.info(f"🔑 Проверка webhook: {sign} == {expected_sign}")
    return sign == expected_sign

def create_freekassa_payment_link(amount: float, order_id: str, description: str = "") -> str:
    """
    Создание ссылки для оплаты через FreeKassa
    """
    if not FREEKASSA_MERCHANT_ID or not FREEKASSA_SECRET_KEY_S1:
        logger.error("❌ FreeKassa не настроен")
        return ""
    
    merchant_id = str(FREEKASSA_MERCHANT_ID)
    amount_int = int(amount)
    amount_str = str(amount_int)
    order_id_str = str(order_id)
    
    signature = generate_freekassa_signature(
        merchant_id,
        amount_str,
        order_id_str
    )
    
    params = {
        "m": merchant_id,
        "oa": amount_str,
        "currency": FREEKASSA_CURRENCY,
        "o": order_id_str,
        "s": signature,
    }
    
    if description:
        params["description"] = description[:255]
    
    query_string = urlencode(params)
    link = f"https://pay.fk.money/?{query_string}"
    
    logger.info("=" * 60)
    logger.info("🔗 ССЫЛКА ДЛЯ ОПЛАТЫ:")
    logger.info(link)
    logger.info("📋 ПРОВЕРКА ПОДПИСИ:")
    logger.info(f"Merchant ID: {merchant_id}")
    logger.info(f"Сумма: {amount_str}")
    logger.info(f"S1: {FREEKASSA_SECRET_KEY_S1} ({len(FREEKASSA_SECRET_KEY_S1)} символов)")
    logger.info(f"Order ID: {order_id_str}")
    logger.info(f"Подпись: {signature}")
    logger.info("=" * 60)
    
    return link

async def check_freekassa_payment_status(order_id: str) -> Optional[dict]:
    """Проверка статуса платежа через API FreeKassa"""
    if not FREEKASSA_API_KEY:
        logger.error("❌ FREEKASSA_API_KEY не задан")
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
        logger.error(f"Ошибка проверки статуса: {e}")
        return None

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

# ===== КОМАНДА /BROADCAST =====
@dp.message(Command("broadcast"))
async def broadcast_command(message: Message):
    try:
        if message.chat.type != "private":
            await message.answer("ℹ️ Эта команда работает только в личных сообщениях.")
            return
        
        user_id = message.from_user.id
        
        if not FREEKASSA_MERCHANT_ID or not FREEKASSA_SECRET_KEY_S1:
            await message.answer(
                "❌ FreeKassa не настроен.\n"
                "Установите переменные:\n"
                "FREEKASSA_MERCHANT_ID\n"
                "FREEKASSA_SECRET_KEY_S1 (S1)"
            )
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
            await message.answer(
                f"📢 Использование: /broadcast Ваше сообщение\n\n"
                f"💰 Стоимость: {load_broadcast_price()} {FREEKASSA_CURRENCY}\n"
                f"💳 Оплата через FreeKassa\n\n"
                f"📌 Можно прикрепить фото, видео, GIF или документ"
            )
            return
        
        current_price = load_broadcast_price()
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
            'price': current_price
        }
        
        payment_url = create_freekassa_payment_link(
            current_price, 
            order_id,
            f"Рассылка в Telegram"
        )
        
        if not payment_url:
            await message.answer("❌ Ошибка генерации ссылки.")
            return
        
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
            f"📢 Для отправки рассылки оплатите {current_price} {FREEKASSA_CURRENCY}.\n\n"
            f"📝 Текст: {text[:100]}{'...' if len(text) > 100 else ''}\n"
            f"{'📎 С медиафайлом' if has_media else ''}\n\n"
            f"💳 Нажмите кнопку ниже для оплаты.",
            reply_markup=keyboard
        )
        
        logger.info(f"💳 Счёт создан для пользователя {user_id}, заказ {order_id}")
        
    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка: {str(e)[:100]}")

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
                    "Оплатите счёт и нажмите 'Проверить оплату' снова."
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
            f"⏳ Ожидайте подтверждения от администратора."
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
        
        preview_text = f"📋 Новая рассылка на модерацию #{broadcast_id}\n\n"
        preview_text += f"👤 Заказчик ID: {user_id}\n"
        preview_text += f"💰 Оплачено: {broadcast_info.get('price', broadcast_price)} {FREEKASSA_CURRENCY}\n"
        
        if text:
            preview_text += f"\n📝 Текст:\n{text[:300]}{'...' if len(text) > 300 else ''}\n"
        
        if has_media:
            preview_text += f"\n📎 С медиафайлом\n"
        
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
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.error(f"Ошибка отправки в {chat_id}: {e}")
                    failed_count += 1
            
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
                    else:
                        if text:
                            await bot.send_message(chat_id=channel_id, text=text)
                    logger.info(f"✅ Отправлено в канал {channel_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки в канал: {e}")
            
            del pending_broadcasts[broadcast_id]
            
            try:
                user_id = broadcast_info.get('user_id')
                if user_id:
                    await bot.send_message(
                        chat_id=user_id,
                        text=f"✅ Ваше сообщение опубликовано!\n📨 Отправлено: {sent_count} подписчикам"
                    )
            except Exception as e:
                logger.error(f"Ошибка уведомления заказчика: {e}")
                
        else:
            await callback.answer("❌ Сообщение отклонено", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n❌ ОТКЛОНЕНО",
                reply_markup=None
            )
            if broadcast_id in pending_broadcasts:
                del pending_broadcasts[broadcast_id]
    except Exception as e:
        logger.error(f"Ошибка в broadcast модерации: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

# ===== ТЕСТОВАЯ КОМАНДА =====
@dp.message(Command("testfreekassa"))
async def test_freekassa(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Доступ запрещен")
        return
    
    merchant = FREEKASSA_MERCHANT_ID
    s1 = FREEKASSA_SECRET_KEY_S1
    s2 = FREEKASSA_SECRET_KEY_S2
    
    if not merchant or not s1:
        await message.answer("❌ FreeKassa не настроен!")
        return
    
    test_amount = 100
    test_order = f"test_{int(time.time())}"
    
    # Генерируем подпись с S1
    sign_str = f"{merchant}:{test_amount}:{s1}:{test_order}"
    signature = hashlib.md5(sign_str.encode()).hexdigest()
    
    # Формируем ссылку
    link = f"https://pay.fk.money/?m={merchant}&oa={test_amount}&currency={FREEKASSA_CURRENCY}&o={test_order}&s={signature}"
    
    await message.answer(
        f"🧪 **ТЕСТ FREEKASSA**\n\n"
        f"📋 Merchant ID: `{merchant}`\n"
        f"🔑 S1: `{s1}` ({len(s1)} символов)\n"
        f"🔑 S2: `{s2}` ({len(s2)} символов)\n"
        f"💰 Сумма: `{test_amount}`\n"
        f"🆔 Order: `{test_order}`\n\n"
        f"🔑 Строка подписи:\n`{sign_str}`\n"
        f"🔑 MD5: `{signature}`\n\n"
        f"🔗 **Ссылка для проверки:**\n`{link}`\n\n"
        f"📌 Откройте ссылку в браузере",
        parse_mode="Markdown"
    )

@dp.message(Command("start"))
async def start_command(message: Message):
    await message.answer(
        "🤖 **Бот для платных рассылок**\n\n"
        "📢 **Команды:**\n"
        "• `/broadcast` — создать платную рассылку\n"
        "• `/price` — установить цену (только владелец)\n"
        "• `/testfreekassa` — тест FreeKassa\n"
        "• `/start` — это сообщение",
        parse_mode="Markdown"
    )

# ===== WEBHOOK =====
async def freekassa_webhook(request):
    try:
        data = await request.post()
        data = dict(data)
        
        logger.info(f"📩 Получен webhook: {data}")
        
        if not verify_freekassa_webhook_signature(data):
            logger.warning("❌ Неверная подпись в webhook")
            return web.Response(text="Invalid signature", status=400)
        
        order_id = data.get('MERCHANT_ORDER_ID')
        status = data.get('STATUS')
        
        if status == 'SUCCESS':
            for uid, info in broadcast_data.items():
                if info.get('order_id') == order_id:
                    logger.info(f"✅ Платёж {order_id} подтверждён")
                    try:
                        await bot.send_message(
                            chat_id=uid,
                            text="✅ Оплата подтверждена!"
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
        logger.info(f"💰 Цена: {load_broadcast_price()} {FREEKASSA_CURRENCY}")
        logger.info(f"💳 Merchant ID: {FREEKASSA_MERCHANT_ID}")
        logger.info(f"🔑 S1: {FREEKASSA_SECRET_KEY_S1} ({len(FREEKASSA_SECRET_KEY_S1)} символов)")
        logger.info(f"🔑 S2: {FREEKASSA_SECRET_KEY_S2} ({len(FREEKASSA_SECRET_KEY_S2)} символов)")
        logger.info("=" * 60)
        
        await bot.delete_webhook(drop_pending_updates=True)
        
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
            skip_updates=True,
            polling_timeout=30
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
