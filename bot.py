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
    print("Ошибка: BOT_TOKEN не задан")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Поисковые запросы
SEARCH_QUERIES = [
    "asian beautiful girl portrait",
    "beautiful japanese woman",
    "korean girl model",
    "chinese woman portrait",
    "east asian beauty",
]

# Хранилище активных чатов
active_chats = {}

# ===== ГЕНЕРАЦИЯ ТЕКСТА ЧЕРЕЗ GOOGLE GEMINI =====

def generate_caption_with_gemini() -> str:
    """
    Генерирует описание для фото через Google Gemini API (БЕСПЛАТНО!)
    """
    try:
        if not GEMINI_KEY:
            print("⚠️ GEMINI_KEY не задан")
            return get_fallback_caption()
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}"
        
        prompt = """Напиши случайную идею, новость или актуальное события, юмористическим стилем.

Примеры стиля:
- "Ты кстати случаем в Россию не вернулся?
А то что-то последние посты начал всё чаще в адекватное для малюток время писать, а не в 4-5 утра, как раньше.
Если так, то надеюсь это не Росов тебя через Новосибирский аэропорт убедил прилететь..."
- "Бля, базаришь, Илья.
Я что-то тоже в последнее время поднабрал на японской лапше в наваристом свином бульоне.
Всегда был тонкий как спица, и вот впервые в жизни заметил у себя признаки скуфского пузика.
Пиздец, похоже старость приходит.
Хорошо, что хотя бы лысина меня стороной обошла (тьфу-тьфу-тьфу)
Вроде у бати и у деда нет лысины, поэтому шансы кажется в мою пользу.
Тогда тоже с завтрашнего дня сажусь на диету.
Скуфяры в чате - присоединяйтесь.
Завтра все встаём с утра и начинаем считать калории.
Едим овощи, варим гречку, и побольше мяса - лучше куриную грудку.
Всё взвешиваем, скидываем в ChatGPT, чтобы подсчитал калории.
Держимся минимум 2 месяца, потом все отчитываемся об успехах.
Вольно, бойцы."

Требования:
- 1-2 предложения
- Грубый и юмористический стиль
- Упоминание восточной культуры (Япония, Корея, Китай)
- Без кавычек и лишних слов
- Разные описания каждый раз

Напиши ТОЛЬКО описание."""

        data = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }
        
        headers = {"Content-Type": "application/json"}
        
        print("🔄 Генерация описания через Gemini...")
        response = requests.post(url, headers=headers, json=data, timeout=20)
        
        # Проверяем статус ответа
        if response.status_code != 200:
            print(f"❌ Gemini ошибка: {response.status_code}")
            print(f"📄 Ответ: {response.text[:200]}")
            return get_fallback_caption()
        
        # Парсим JSON
        try:
            result = response.json()
        except json.JSONDecodeError:
            print("❌ Ошибка парсинга JSON")
            return get_fallback_caption()
        
        # Извлекаем текст
        if "candidates" in result and len(result["candidates"]) > 0:
            caption = result["candidates"][0]["content"]["parts"][0]["text"].strip()
            # Очищаем от кавычек
            caption = caption.strip('"').strip("'")
            
            # Добавляем случайный флаг
            tags = ["🇯🇵 Япония", "🇰🇷 Корея", "🇨🇳 Китай", "🇹🇭 Таиланд"]
            tag = random.choice(tags)
            
            print(f"✅ Сгенерировано: {caption[:50]}...")
            return f"{caption}\n\n{tag} 📸"
        else:
            print("❌ Неожиданный ответ от Gemini")
            return get_fallback_caption()
            
    except requests.exceptions.Timeout:
        print("⏰ Таймаут Gemini")
        return get_fallback_caption()
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка запроса: {e}")
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
    """Проверяет, является ли пользователь администратором чата"""
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ["administrator", "creator"]
    except:
        return False

def search_bing(query):
    """Ищет фото через Bing Images"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        
        encoded_query = quote(query)
        url = f"https://www.bing.com/images/search?q={encoded_query}&form=HDRSC3&first=1&count=35"
        
        response = requests.get(url, headers=headers, timeout=15)
        
        # Ищем ссылки на изображения
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
    """Ищет фото через Google Images"""
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
    """Ищет фото через Pexels API"""
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
    """Получает случайное фото азиатки из интернета"""
    queries = SEARCH_QUERIES.copy()
    random.shuffle(queries)
    
    # 1. Bing
    print("🔍 Поиск в Bing...")
    for query in queries:
        photo = search_bing(query)
        if photo:
            print(f"✅ Найдено в Bing: {query}")
            return photo
        time.sleep(0.3)
    
    # 2. Google
    print("🔍 Поиск в Google...")
    for query in queries:
        photo = search_google_direct(query)
        if photo:
            print(f"✅ Найдено в Google: {query}")
            return photo
        time.sleep(0.3)
    
    # 3. Pexels
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
    """Отправляет фото с AI-описанием"""
    try:
        photo_url = get_random_photo()
        
        if photo_url:
            # Генерируем описание через Gemini
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
        await bot.send_message(
            chat_id=chat_id, 
            text=f"❌ Ошибка: {str(e)[:100]}"
        )
        return False

async def send_to_all():
    """Отправляет фото во все активные чаты"""
    if not active_chats:
        print("⚠️ Нет активных чатов")
        return
    
    print(f"📤 Отправка в {len(active_chats)} чатов...")
    
    for chat_id in list(active_chats.keys()):
        await send_photo(chat_id)
        await asyncio.sleep(2)

async def scheduler():
    """Отправляет каждые 3 часа во все чаты"""
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
    
    # Проверяем админа (для групп)
    if chat_type in ["group", "supergroup"]:
        if not await is_user_admin(chat_id, user_id):
            await msg.reply("⛔ Эта команда только для администраторов группы.")
            return
        
        # Проверяем, админ ли бот в группе
        try:
            chat_member = await bot.get_chat_member(chat_id, bot.id)
            is_admin = chat_member.status in ["administrator", "creator"]
        except:
            is_admin = False
        
        if not is_admin:
            await msg.answer("❌ Я должен быть администратором группы!\nНазначьте меня админом и попробуйте снова.")
            return
    
    # Добавляем чат в список активных
    active_chats[chat_id] = {
        "type": chat_type,
        "added_by": user_id,
        "added_at": datetime.now().isoformat(),
        "name": msg.chat.title or msg.chat.first_name or str(chat_id)
    }
    
    ai_status = "✅ Google Gemini" if GEMINI_KEY else "❌ Резервные описания"
    
    await msg.answer(
        f"✅ Бот активирован!\n"
        f"📌 Тип: {chat_type}\n"
        f"🧠 Нейросеть: {ai_status}\n"
        f"📸 Фото азиаток с AI-описаниями каждые 3 часа\n"
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
    
    # Только админы могут запрашивать фото в группах
    if chat_type in ["group", "supergroup"]:
        if not await is_user_admin(chat_id, user_id):
            await msg.reply("⛔ Только администраторы могут запрашивать фото.")
            return
    
    if chat_id not in active_chats:
        await msg.answer("⚠️ Бот не активирован. Напишите /start (только для админов)")
        return
    
    await msg.answer("🔍 Ищу фото и генерирую описание...")
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
    
    ai_status = "✅ Google Gemini" if GEMINI_KEY else "❌ Резервные описания"
    
    status_text = (
        f"📊 Статус бота:\n"
        f"• В этом чате: {'✅ Активен' if is_active else '❌ Неактивен'}\n"
        f"• Всего чатов: {len(active_chats)}\n"
        f"• Нейросеть: {ai_status}\n"
        f"• Поиск: Bing + Google + Pexels\n"
        f"• Фото: только азиатки с AI-описаниями"
    )
    
    if is_active and chat_id in active_chats:
        info = active_chats[chat_id]
        status_text += f"\n📌 Тип: {info.get('type', 'unknown')}"
    
    await msg.answer(status_text)

@dp.message(Command("chats"))
async def list_chats(msg: Message):
    """Список всех чатов (только для владельца)"""
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
    """Тестирует генерацию описания (только для владельца)"""
    OWNER_ID = int(os.getenv("CHAT_ID", 0))
    
    if msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён.")
        return
    
    await msg.answer("🧠 Генерирую описание через Google Gemini...")
    
    caption = generate_caption_with_gemini()
    await msg.answer(f"📝 Результат:\n\n{caption}")

# ===== ЗАПУСК =====

async def main():
    print("=" * 60)
    print("🤖 Бот запущен")
    print("🔍 Поиск в: Bing → Google → Pexels")
    print("🌏 Только азиатки: японки, китаянки, кореянки")
    
    if GEMINI_KEY:
        print("🧠 Нейросеть: Google Gemini ✅ (БЕСПЛАТНО!)")
        print("📝 Генерация уникальных описаний")
    else:
        print("📝 Резервные описания (AI не настроен)")
        print("ℹ️ Получите ключ: makersuite.google.com/app/apikey")
    
    print("🔒 Команды только для администраторов")
    print("=" * 60)
    
    owner_id = os.getenv("CHAT_ID", "не задан")
    print(f"👤 ID владельца: {owner_id}")
    print("=" * 60)
    
    asyncio.create_task(scheduler())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
