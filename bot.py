import asyncio
import os
import random
import sys
import re
import requests
import json
import time
from urllib.parse import quote
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

# ===== НАСТРОЙКИ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    print("Ошибка: BOT_TOKEN не задан")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Поисковые запросы (только азиатки)
SEARCH_QUERIES = [
    "asian beautiful girl portrait",
    "beautiful japanese woman",
    "korean girl model",
    "chinese woman portrait",
    "east asian beauty",
    "asian model photography",
]

# Хранилище активных чатов
active_chats = {}

def search_bing(query):
    """
    Ищет фото через Bing Images
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        
        encoded_query = quote(query)
        url = f"https://www.bing.com/images/search?q={encoded_query}&form=HDRSC3&first=1&count=35"
        
        response = requests.get(url, headers=headers, timeout=15)
        
        pattern = r'"murl":"([^"]+)"'
        images = re.findall(pattern, response.text)
        
        pattern2 = r'"mediaurl":"([^"]+)"'
        images.extend(re.findall(pattern2, response.text))
        
        clean_images = []
        for img in images:
            img = img.replace('\\u0026', '&')
            img = img.replace('\\/', '/')
            
            if any(ext in img.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                if not any(x in img.lower() for x in ['gstatic', 'google', 'favicon', 'logo', 'bing']):
                    clean_images.append(img)
        
        clean_images = list(dict.fromkeys(clean_images))
        
        if clean_images:
            return random.choice(clean_images)
        
        return None
        
    except Exception as e:
        print(f"Ошибка Bing: {e}")
        return None

def search_google_direct(query):
    """
    Ищет фото через Google Images
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        
        encoded_query = quote(query)
        url = f"https://www.google.com/search?q={encoded_query}&tbm=isch&safe=active&tbs=isz:l"
        
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
                        clean_images.append(img)
        
        clean_images = list(dict.fromkeys(clean_images))
        
        if clean_images:
            return random.choice(clean_images)
        
        return None
        
    except Exception as e:
        print(f"Ошибка Google: {e}")
        return None

def search_pexels(query):
    """
    Ищет фото через Pexels API
    """
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
                photo = random.choice(photos)
                return photo["src"]["large"]
        
        return None
        
    except Exception as e:
        print(f"Ошибка Pexels: {e}")
        return None

def get_random_photo():
    """
    Получает случайное фото азиатки из интернета
    """
    queries = SEARCH_QUERIES.copy()
    random.shuffle(queries)
    
    # 1. Пробуем Bing
    print("🔍 Поиск в Bing...")
    for query in queries:
        photo = search_bing(query)
        if photo:
            print(f"✅ Найдено в Bing: {query}")
            return photo
        time.sleep(0.3)
    
    # 2. Пробуем Google
    print("🔍 Поиск в Google...")
    for query in queries:
        photo = search_google_direct(query)
        if photo:
            print(f"✅ Найдено в Google: {query}")
            return photo
        time.sleep(0.3)
    
    # 3. Пробуем Pexels
    print("🔍 Поиск в Pexels...")
    for query in queries:
        photo = search_pexels(query)
        if photo:
            print(f"✅ Найдено в Pexels: {query}")
            return photo
        time.sleep(0.3)
    
    print("❌ Не найдено ни одного фото")
    return None

async def send_photo(chat_id):
    """
    Отправляет фото или ошибку
    """
    try:
        photo_url = get_random_photo()
        
        if photo_url:
            await bot.send_photo(chat_id=chat_id, photo=photo_url)
            print(f"✅ Фото отправлено в чат {chat_id}")
            return True
        else:
            error_msg = (
                "❌ Не удалось найти фото азиатской девушки.\n\n"
                "💡 Попробуйте позже или используйте /photo снова."
            )
            await bot.send_message(chat_id=chat_id, text=error_msg)
            print(f"❌ Фото не найдено для чата {chat_id}")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка отправки в чат {chat_id}: {e}")
        return False

async def send_to_all():
    """
    Отправляет фото во все активные чаты
    """
    if not active_chats:
        print("⚠️ Нет активных чатов")
        return
    
    print(f"📤 Отправка в {len(active_chats)} чатов...")
    
    for chat_id in list(active_chats.keys()):
        await send_photo(chat_id)
        await asyncio.sleep(2)

async def scheduler():
    """
    Отправляет каждые 3 часа во все чаты
    """
    await asyncio.sleep(5)
    await send_to_all()
    
    while True:
        await asyncio.sleep(3 * 3600)  # 3 часа
        await send_to_all()

@dp.message(Command("start"))
async def start(msg: Message):
    chat_id = msg.chat.id
    chat_type = msg.chat.type
    user = msg.from_user
    
    # Проверяем, является ли чат группой или супергруппой
    if chat_type in ["group", "supergroup"]:
        # Проверяем, админ ли бот в группе
        try:
            chat_member = await bot.get_chat_member(chat_id, bot.id)
            is_admin = chat_member.status in ["administrator", "creator"]
        except:
            is_admin = False
        
        if not is_admin:
            await msg.answer(
                "❌ Я должен быть администратором группы!\n\n"
                "Чтобы активировать бота:\n"
                "1. Назначьте меня администратором\n"
                "2. Дайте права на отправку сообщений\n"
                "3. Напишите /start снова"
            )
            return
    
    # Добавляем чат в список активных
    active_chats[chat_id] = {
        "type": chat_type,
        "added_by": user.id,
        "added_at": datetime.now().isoformat(),
        "name": msg.chat.title or msg.chat.first_name or str(chat_id)
    }
    
    await msg.answer(
        f"✅ Бот активирован!\n"
        f"📌 Тип: {chat_type}\n"
        f"🆔 ID: {chat_id}\n"
        f"📸 Фото азиаток каждые 3 часа\n"
        f"🔄 /photo - получить фото сейчас\n"
        f"📊 /status - статус бота\n"
        f"🛑 /stop - отключить бота"
    )
    
    # Отправляем приветственное фото
    await asyncio.sleep(1)
    await send_photo(chat_id)
    
    print(f"✅ Активирован чат: {chat_id} ({chat_type})")

@dp.message(Command("photo"))
async def photo(msg: Message):
    chat_id = msg.chat.id
    
    if chat_id not in active_chats:
        await msg.answer("⚠️ Бот не активирован в этом чате. Напишите /start")
        return
    
    await send_photo(chat_id)

@dp.message(Command("stop"))
async def stop(msg: Message):
    chat_id = msg.chat.id
    
    if chat_id in active_chats:
        del active_chats[chat_id]
        await msg.answer("🛑 Бот отключён в этом чате")
        print(f"🛑 Отключен чат: {chat_id}")
    else:
        await msg.answer("ℹ️ Бот и так не активен в этом чате")

@dp.message(Command("status"))
async def status(msg: Message):
    chat_id = msg.chat.id
    is_active = chat_id in active_chats
    
    # Информация о текущем чате
    status_text = (
        f"📊 Статус бота:\n"
        f"• В этом чате: {'✅ Активен' if is_active else '❌ Неактивен'}\n"
        f"• Всего чатов: {len(active_chats)}\n"
        f"• Поиск: Bing + Google + Pexels\n"
        f"• Фото: только азиатки\n"
    )
    
    # Если чат активен, показываем дополнительную информацию
    if is_active and chat_id in active_chats:
        info = active_chats[chat_id]
        status_text += f"\n📌 Тип: {info.get('type', 'unknown')}"
        if info.get('name'):
            status_text += f"\n📝 Название: {info.get('name')}"
    
    await msg.answer(status_text)

@dp.message(Command("chats"))
async def list_chats(msg: Message):
    """
    Показывает все активные чаты (только для владельца)
    """
    # Проверяем владельца по ID из .env
    OWNER_ID = int(os.getenv("CHAT_ID", 0))
    
    if msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён. Только для владельца.")
        return
    
    if not active_chats:
        await msg.answer("📭 Нет активных чатов")
        return
    
    text = f"📋 Активные чаты ({len(active_chats)}):\n\n"
    
    for i, (chat_id, info) in enumerate(active_chats.items(), 1):
        name = info.get('name', 'Без названия')[:30]
        chat_type = info.get('type', 'unknown')
        added_at = info.get('added_at', '')[:16] if info.get('added_at') else ''
        
        text += f"{i}. {name}\n"
        text += f"   ID: {chat_id}\n"
        text += f"   Тип: {chat_type}\n"
        text += f"   Добавлен: {added_at}\n\n"
        
        # Ограничиваем длину сообщения
        if len(text) > 3500:
            text += "... (показаны не все)"
            break
    
    await msg.answer(text)

@dp.message(Command("stop_all"))
async def stop_all(msg: Message):
    """
    Отключает бота во всех чатах (только для владельца)
    """
    OWNER_ID = int(os.getenv("CHAT_ID", 0))
    
    if msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён. Только для владельца.")
        return
    
    count = len(active_chats)
    active_chats.clear()
    
    await msg.answer(f"🛑 Бот отключён во всех {count} чатах")

@dp.message(Command("broadcast"))
async def broadcast(msg: Message):
    """
    Отправляет сообщение во все чаты (только для владельца)
    """
    OWNER_ID = int(os.getenv("CHAT_ID", 0))
    
    if msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён. Только для владельца.")
        return
    
    # Получаем текст после команды
    text = msg.text.replace("/broadcast", "").strip()
    
    if not text:
        await msg.answer("ℹ️ Укажите текст для рассылки.\nПример: /broadcast Привет всем!")
        return
    
    if not active_chats:
        await msg.answer("📭 Нет активных чатов")
        return
    
    await msg.answer(f"📤 Отправка '{text[:30]}...' в {len(active_chats)} чатов")
    
    sent = 0
    for chat_id in list(active_chats.keys()):
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            sent += 1
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Ошибка отправки в {chat_id}: {e}")
            # Если бот заблокирован - удаляем чат
            if "forbidden" in str(e).lower():
                del active_chats[chat_id]
    
    await msg.answer(f"✅ Отправлено в {sent} чатов")

async def main():
    print("=" * 60)
    print("🤖 Бот запущен")
    print("🔍 Поиск в: Bing → Google → Pexels")
    print("🌏 Только азиатки: японки, китаянки, кореянки")
    print("📌 Работает во ВСЕХ чатах, где является админом")
    print("=" * 60)
    
    # Проверяем Pexels ключ
    pexels_key = os.getenv("PEXELS_KEY")
    if pexels_key:
        print("✅ Pexels API: доступен")
    else:
        print("ℹ️ Pexels API: не настроен (можно получить на pexels.com)")
    
    # Проверяем ID владельца
    owner_id = os.getenv("CHAT_ID", "не задан")
    print(f"👤 ID владельца: {owner_id}")
    print("=" * 60)
    
    asyncio.create_task(scheduler())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())