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
from aiogram.types import Message, ChatMember

# ===== НАСТРОЙКИ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")

if not BOT_TOKEN:
    print("❌ Ошибка: BOT_TOKEN не задан")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

SEARCH_QUERIES = [
    "asian beautiful girl portrait",
    "beautiful japanese woman",
    "korean girl model",
    "chinese woman portrait",
    "east asian beauty",
]

active_chats = {}

# ===== ГЕНЕРАЦИЯ ТЕКСТА ЧЕРЕЗ GOOGLE GEMINI (БЕЗ КЭША) =====

def generate_caption_with_gemini() -> str:
    """Генерирует уникальное описание для каждого фото"""
    print(f"🔑 Ключ Gemini: {'✅ задан' if GEMINI_KEY else '❌ НЕ ЗАДАН'}")
    
    if not GEMINI_KEY:
        print("⚠️ GEMINI_KEY не задан, использую резерв")
        return get_fallback_caption()
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}"
        
        prompt = """Напиши короткое, романтичное и красивое описание (на русском языке) для фотографии азиатской девушки.

Примеры стиля:
- "🌸 Японская весна. Нежность и изящество сакуры в каждом взгляде."
- "💫 K-Beauty. Сияние, которое невозможно не заметить."
- "🏮 Шанхай. Огонь и элегантность в каждом движении."

Требования:
- 1-2 предложения
- Романтичный и поэтичный стиль
- Упоминание восточной культуры (Япония, Корея, Китай)
- Без кавычек и лишних слов
- КАЖДЫЙ РАЗ НОВОЕ, НЕ ПОВТОРЯЙСЯ

Напиши ТОЛЬКО описание."""

        data = {"contents": [{"parts": [{"text": prompt}]}]}
        headers = {"Content-Type": "application/json"}
        
        print("🔄 Генерация уникального описания через Gemini 2.0 Flash...")
        
        # Повторные попытки при ошибке 429
        for attempt in range(3):
            response = requests.post(url, headers=headers, json=data, timeout=20)
            
            if response.status_code == 429:
                wait_time = (attempt + 1) * 10
                print(f"⚠️ Ошибка 429 (лимит). Ждём {wait_time} сек...")
                time.sleep(wait_time)
                continue
            
            break
        
        if response.status_code != 200:
            print(f"❌ Gemini ошибка: {response.status_code}")
            return get_fallback_caption()
        
        result = response.json()
        
        if "candidates" in result and len(result["candidates"]) > 0:
            caption = result["candidates"][0]["content"]["parts"][0]["text"].strip()
            caption = caption.strip('"').strip("'")
            
            tags = ["🇯🇵 Япония", "🇰🇷 Корея", "🇨🇳 Китай", "🇹🇭 Таиланд"]
            tag = random.choice(tags)
            
            print(f"✅ Уникальное описание сгенерировано: {caption[:50]}...")
            return f"{caption}\n\n{tag} 📸"
        else:
            print("❌ Нет candidates в ответе")
            return get_fallback_caption()
            
    except Exception as e:
        print(f"❌ Ошибка генерации: {e}")
        return get_fallback_caption()

def get_fallback_caption() -> str:
    """Резервные описания (если AI не работает)"""
    captions = [
        "🌸 Японская весна. Нежность и изящество сакуры в каждом взгляде.",
        "💫 K-Beauty. Сияние, которое невозможно не заметить.",
        "🏮 Шанхай. Огонь и элегантность в каждом движении.",
        "🌏 Восточная красота. Утончённость и гармония.",
        "✨ Азиатский шарм — в каждой детали.",
        "🌺 Красота, которая вдохновляет.",
        "🌸 Симфония восточной красоты.",
        "💕 Азия в кадре — искренность и свет.",
        "🌟 Восточная эстетика. Минимализм и изящество.",
        "🌺 Цветущая сакура и нежный взгляд."
    ]
    caption = random.choice(captions)
    tags = ["🇯🇵 Япония", "🇰🇷 Корея", "🇨🇳 Китай"]
    tag = random.choice(tags)
    return f"{caption}\n\n{tag} 📸"

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

async def is_user_admin(chat_id: int, user_id: int) -> bool:
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ["administrator", "creator"]
    except:
        return False

def search_bing(query):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
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
    queries = SEARCH_QUERIES.copy()
    random.shuffle(queries)
    
    print("🔍 Поиск в Bing...")
    for query in queries:
        photo = search_bing(query)
        if photo:
            print(f"✅ Найдено в Bing: {query}")
            return photo
        time.sleep(0.3)
    
    print("🔍 Поиск в Google...")
    for query in queries:
        photo = search_google_direct(query)
        if photo:
            print(f"✅ Найдено в Google: {query}")
            return photo
        time.sleep(0.3)
    
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
    try:
        photo_url = get_random_photo()
        
        if photo_url:
            # ===== КАЖДЫЙ РАЗ НОВОЕ ОПИСАНИЕ (БЕЗ КЭША) =====
            caption = generate_caption_with_gemini()
            
            await bot.send_photo(
                chat_id=chat_id, 
                photo=photo_url,
                caption=caption
            )
            print(f"✅ Фото отправлено в чат {chat_id}")
            return True
        else:
            await bot.send_message(
                chat_id=chat_id, 
                text="❌ Не удалось найти фото. Попробуйте позже."
            )
            return False
            
    except Exception as e:
        print(f"❌ Ошибка отправки в чат {chat_id}: {e}")
        return False

async def send_to_all():
    if not active_chats:
        print("⚠️ Нет активных чатов")
        return
    
    print(f"📤 Отправка в {len(active_chats)} чатов...")
    
    for chat_id in list(active_chats.keys()):
        await send_photo(chat_id)
        await asyncio.sleep(5)  # 5 секунд между чатами

async def scheduler():
    await asyncio.sleep(5)
    await send_to_all()
    
    while True:
        await asyncio.sleep(3 * 3600)  # 3 часа
        await send_to_all()

# ===== КОМАНДЫ БОТА =====

@dp.message(Command("start"))
async def start(msg: Message):
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    chat_type = msg.chat.type
    
    if chat_type in ["group", "supergroup"]:
        if not await is_user_admin(chat_id, user_id):
            await msg.reply("⛔ Эта команда только для администраторов группы.")
            return
        
        try:
            chat_member = await bot.get_chat_member(chat_id, bot.id)
            is_admin = chat_member.status in ["administrator", "creator"]
        except:
            is_admin = False
        
        if not is_admin:
            await msg.answer("❌ Я должен быть администратором группы!\nНазначьте меня админом и попробуйте снова.")
            return
    
    active_chats[chat_id] = {
        "type": chat_type,
        "added_by": user_id,
        "added_at": datetime.now().isoformat(),
        "name": msg.chat.title or msg.chat.first_name or str(chat_id)
    }
    
    ai_status = "✅ Gemini 2.0 Flash (уникальные описания)" if GEMINI_KEY else "❌ Резервные описания"
    
    await msg.answer(
        f"✅ Бот активирован!\n"
        f"📌 Тип: {chat_type}\n"
        f"🧠 Нейросеть: {ai_status}\n"
        f"📸 Уникальные AI-описания к КАЖДОМУ фото\n"
        f"📸 Фото азиаток каждые 3 часа\n"
        f"🔄 /photo - получить фото сейчас\n"
        f"📊 /status - статус бота\n"
        f"🛑 /stop - отключить бота"
    )
    
    await asyncio.sleep(1)
    await send_photo(chat_id)
    
    print(f"✅ Активирован чат: {chat_id} ({chat_type})")

@dp.message(Command("photo"))
async def photo(msg: Message):
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    chat_type = msg.chat.type
    
    if chat_type in ["group", "supergroup"]:
        if not await is_user_admin(chat_id, user_id):
            await msg.reply("⛔ Только администраторы могут запрашивать фото.")
            return
    
    if chat_id not in active_chats:
        await msg.answer("⚠️ Бот не активирован. Напишите /start (только для админов)")
        return
    
    await msg.answer("🔍 Ищу фото и генерирую уникальное описание...")
    await send_photo(chat_id)

@dp.message(Command("stop"))
async def stop(msg: Message):
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    chat_type = msg.chat.type
    
    if chat_type in ["group", "supergroup"]:
        if not await is_user_admin(chat_id, user_id):
            await msg.reply("⛔ Только администраторы могут отключить бота.")
            return
    
    if chat_id in active_chats:
        del active_chats[chat_id]
        await msg.answer("🛑 Бот отключён в этом чате")
        print(f"🛑 Отключен чат: {chat_id}")
    else:
        await msg.answer("ℹ️ Бот и так не активен в этом чате")

@dp.message(Command("status"))
async def status(msg: Message):
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    chat_type = msg.chat.type
    
    if chat_type in ["group", "supergroup"]:
        if not await is_user_admin(chat_id, user_id):
            await msg.reply("⛔ Только администраторы могут смотреть статус.")
            return
    
    is_active = chat_id in active_chats
    
    ai_status = "✅ Gemini 2.0 Flash (уникальные описания)" if GEMINI_KEY else "❌ Резервные описания"
    
    status_text = (
        f"📊 Статус бота:\n"
        f"• В этом чате: {'✅ Активен' if is_active else '❌ Неактивен'}\n"
        f"• Всего чатов: {len(active_chats)}\n"
        f"• Нейросеть: {ai_status}\n"
        f"• Поиск: Bing + Google + Pexels\n"
        f"• Фото: только азиатки с AI-описаниями"
    )
    
    await msg.answer(status_text)

@dp.message(Command("chats"))
async def list_chats(msg: Message):
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
        
        text += f"{i}. {name}\n   ID: {chat_id}\n   Тип: {chat_type}\n   Добавлен: {added_at}\n\n"
        
        if len(text) > 3500:
            text += "... (показаны не все)"
            break
    
    await msg.answer(text)

@dp.message(Command("test_ai"))
async def test_ai(msg: Message):
    OWNER_ID = int(os.getenv("CHAT_ID", 0))
    
    if msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён.")
        return
    
    await msg.answer("🧠 Генерирую уникальное описание через Gemini 2.0 Flash...")
    
    caption = generate_caption_with_gemini()
    await msg.answer(f"📝 Результат:\n\n{caption}")

# ===== ЗАПУСК (С ЗАЩИТОЙ ОТ КОНФЛИКТОВ) =====

async def main():
    print("=" * 60)
    print("🤖 Бот запущен")
    print("🔍 Поиск в: Bing → Google → Pexels")
    print("🌏 Только азиатки: японки, китаянки, кореянки")
    
    if GEMINI_KEY:
        print("🧠 Нейросеть: Gemini 2.0 Flash ✅")
        print("📝 Уникальные описания к КАЖДОМУ фото (без кэша)")
    else:
        print("📝 Резервные описания (AI не настроен)")
        print("ℹ️ Получите ключ: makersuite.google.com/app/apikey")
    
    print("🔒 Команды только для администраторов")
    print("=" * 60)
    
    owner_id = os.getenv("CHAT_ID", "не задан")
    print(f"👤 ID владельца: {owner_id}")
    print("=" * 60)
    
    # ===== УДАЛЯЕМ СТАРЫЕ WEBHOOK'И (чтобы избежать конфликтов) =====
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("✅ Старые webhook'и удалены, конфликтов не будет")
    except Exception as e:
        print(f"⚠️ Ошибка удаления webhook: {e}")
    
    # Запускаем планировщик
    asyncio.create_task(scheduler())
    
    # Запускаем бота
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ Ошибка запуска: {e}")
    finally:
        await bot.session.close()
        print("👋 Бот остановлен")

if __name__ == "__main__":
    asyncio.run(main())
