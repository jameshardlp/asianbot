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
from aiogram.exceptions import TelegramConflictError

# ===== НАСТРОЙКИ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not BOT_TOKEN:
    print("❌ Ошибка: BOT_TOKEN не задан")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Поисковые запросы для фото
SEARCH_QUERIES = [
    "asian beautiful girl portrait",
    "beautiful japanese woman",
    "korean girl model",
    "chinese woman portrait",
    "east asian beauty",
]

# Хранилище активных чатов
active_chats = {}

# ===== ГЕНЕРАЦИЯ ТЕКСТА ЧЕРЕЗ DeepSeek API =====

def generate_caption_with_deepseek() -> str:
    """
    Генерирует уникальное описание через DeepSeek V4 API
    """
    print(f"🔑 DeepSeek ключ: {'✅ задан' if DEEPSEEK_API_KEY else '❌ НЕ ЗАДАН'}")
    
    if not DEEPSEEK_API_KEY:
        print("⚠️ DEEPSEEK_API_KEY не задан, использую резерв")
        return get_fallback_caption()
    
    try:
        # DeepSeek API endpoint (совместим с OpenAI)
        url = "https://api.deepseek.com/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        prompt = """Напиши описание для фотографии используя шутки и грубый стиль общения.

Примеры стиля:
- "Ничего-ничего, после Городка с Хованским они уже ни на что не в обиде.
Даже на Миротворец тебя в благодарность записали.

Ты кстати случаем в Россию не вернулся? 🤔
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
Вольно, бойцы.

США уже не торт.
Раньше это была самая пиздатая страна на планете.
Но потом они зачем-то отменили рабство...

Сижу вот, думаю, может сделать ларпинг тебя на Ютубе.
Куплю говняный микрофон, создам канал Larpysson, и буду делать обзор на Месть Боксёра...
а потом трахну торт.
Ищу кучерявого напарника, который готов создать канал Юрий Ларпинкий, чтобы сыграть роль Пушкина в моём запланированном видосе Городок.
Пишите.
Ещё хочу заларпить видос "Слава Роду" - родинку на груди уже нарисовал, а вот где такую футболку заказать не могу найти."

Требования:
- 1-2 предложения
- Юмористический грубый стиль
- Упоминание восточной культуры (Япония, Корея, Китай)
- Без кавычек и лишних слов
- КАЖДЫЙ РАЗ НОВОЕ, НЕ ПОВТОРЯЙСЯ

Напиши ТОЛЬКО описание."""

        data = {
            "model": "deepseek-v4-flash",  # Экономичная и быстрая модель
            "messages": [
                {"role": "system", "content": "Ты поэт, пишущий красивые описания для фотографий."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.9,
            "max_tokens": 80
        }
        
        print("🔄 Генерация уникального описания через DeepSeek V4...")
        
        # Повторные попытки при ошибках
        for attempt in range(3):
            response = requests.post(url, headers=headers, json=data, timeout=20)
            
            # Если ошибка 429 (Too Many Requests) - ждём
            if response.status_code == 429:
                wait_time = (attempt + 1) * 10
                print(f"⚠️ Ошибка 429 (лимит). Ждём {wait_time} сек...")
                time.sleep(wait_time)
                continue
            
            # Если ошибка 401 (неверный ключ)
            if response.status_code == 401:
                print("❌ Ошибка 401: неверный DeepSeek API ключ")
                return get_fallback_caption()
            
            break
        
        # Проверяем статус ответа
        if response.status_code != 200:
            print(f"❌ DeepSeek ошибка: {response.status_code}")
            print(f"📄 Текст ответа: {response.text[:200]}")
            return get_fallback_caption()
        
        # Парсим JSON
        try:
            result = response.json()
        except json.JSONDecodeError as e:
            print(f"❌ Ошибка парсинга JSON: {e}")
            return get_fallback_caption()
        
        # Извлекаем текст из ответа (формат как у OpenAI)
        if "choices" in result and len(result["choices"]) > 0:
            caption = result["choices"][0]["message"]["content"].strip()
            caption = caption.strip('"').strip("'")
            
            # Добавляем случайный флаг
            tags = ["🇯🇵 Япония", "🇰🇷 Корея", "🇨🇳 Китай", "🇹🇭 Таиланд"]
            tag = random.choice(tags)
            
            print(f"✅ Уникальное описание сгенерировано: {caption[:50]}...")
            return f"{caption}\n\n{tag} 📸"
        else:
            print("❌ Нет 'choices' в ответе DeepSeek")
            print(f"📦 Ответ: {json.dumps(result, indent=2)[:300]}")
            return get_fallback_caption()
            
    except requests.exceptions.Timeout:
        print("⏰ Таймаут DeepSeek")
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
    """Отправляет фото с описанием от DeepSeek"""
    try:
        photo_url = get_random_photo()
        
        if photo_url:
            # Генерируем описание через DeepSeek
            caption = generate_caption_with_deepseek()
            
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
    """Отправляет фото во все активные чаты"""
    if not active_chats:
        print("⚠️ Нет активных чатов")
        return
    
    print(f"📤 Отправка в {len(active_chats)} чатов...")
    
    for chat_id in list(active_chats.keys()):
        await send_photo(chat_id)
        await asyncio.sleep(5)

async def scheduler():
    """Отправляет каждые 3 часа"""
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
    
    ai_status = "✅ DeepSeek V4" if DEEPSEEK_API_KEY else "❌ Резервные описания"
    
    await msg.answer(
        f"✅ Бот активирован!\n"
        f"📌 Тип: {chat_type}\n"
        f"🧠 Нейросеть: {ai_status}\n"
        f"📸 Уникальные AI-описания к КАЖДОМУ фото\n"
        f"📸 Фото азиаток каждые 3 часа\n"
        f"🔄 /photo - получить фото сейчас\n"
        f"📊 /status - статус бота\n"
        f"🛑 /stop - отключить бота\n"
        f"🧪 /test_ai - проверить AI (только владелец)"
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
    
    ai_status = "✅ DeepSeek V4" if DEEPSEEK_API_KEY else "❌ Резервные описания"
    
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
        await msg.answer("⛔ Доступ запрещён. Только для владельца.")
        return
    
    await msg.answer("🧠 Генерирую уникальное описание через DeepSeek V4...")
    
    caption = generate_caption_with_deepseek()
    await msg.answer(f"📝 Результат:\n\n{caption}")

# ===== ЗАПУСК С ЗАЩИТОЙ ОТ КОНФЛИКТОВ =====

async def safe_start_polling():
    """Запускает бота с автоматическим восстановлением при конфликте"""
    max_retries = 5
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            print(f"🚀 Попытка запуска {attempt + 1}/{max_retries}...")
            
            # Принудительно удаляем webhook
            await bot.delete_webhook(drop_pending_updates=True)
            await asyncio.sleep(2)
            
            # Проверяем, что webhook действительно удалён
            webhook_info = await bot.get_webhook_info()
            if webhook_info.url:
                print(f"⚠️ Webhook всё ещё активен: {webhook_info.url}")
                await bot.delete_webhook(drop_pending_updates=True)
                await asyncio.sleep(2)
            
            print("✅ Webhook удалён, запускаем polling...")
            
            await dp.start_polling(
                bot,
                allowed_updates=["message", "callback_query"],
                skip_updates=True
            )
            return True
            
        except TelegramConflictError as e:
            print(f"⚠️ Конфликт: {e}")
            print(f"⏳ Ждём {retry_delay} секунд и пробуем снова...")
            await asyncio.sleep(retry_delay)
            retry_delay += 5
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return False
    
    print("❌ Не удалось запустить бота после всех попыток")
    return False

async def main():
    print("=" * 60)
    print("🤖 Бот запущен")
    print("🔍 Поиск в: Bing → Google → Pexels")
    print("🌏 Только азиатки: японки, китаянки, кореянки")
    
    if DEEPSEEK_API_KEY:
        print("🧠 Нейросеть: DeepSeek V4 ✅")
        print("📝 Уникальные описания к КАЖДОМУ фото")
        print("💰 Экономичная модель (до 10x дешевле конкурентов)")
    else:
        print("📝 Резервные описания (AI не настроен)")
        print("ℹ️ Получите ключ: platform.deepseek.com")
    
    print("🔒 Команды только для администраторов")
    print("=" * 60)
    
    owner_id = os.getenv("CHAT_ID", "не задан")
    print(f"👤 ID владельца: {owner_id}")
    print("=" * 60)
    
    # Запускаем планировщик
    asyncio.create_task(scheduler())
    
    # Запускаем бота с защитой
    await safe_start_polling()

if __name__ == "__main__":
    asyncio.run(main())
