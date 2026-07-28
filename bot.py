import asyncio
import os
import random
import sys
import re
import requests
import json
import time
import gc
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

SEARCH_QUERIES = [
    "asian beautiful girl portrait",
    "beautiful japanese woman",
    "korean girl model",
    "chinese woman portrait",
]

ACTIVE_CHATS_FILE = "active_chats.json"

def load_chats():
    try:
        with open(ACTIVE_CHATS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_chats():
    try:
        with open(ACTIVE_CHATS_FILE, "w") as f:
            json.dump(active_chats, f)
    except:
        pass

active_chats = load_chats()

# ===== ГЕНЕРАЦИЯ ЮМОРИСТИЧЕСКИХ ОПИСАНИЙ =====

def generate_caption_with_deepseek() -> str:
    """
    Генерирует юмористическое описание через DeepSeek API
    """
    if not DEEPSEEK_API_KEY:
        print("⚠️ Нет ключа DeepSeek")
        return get_fallback_caption()
    
    try:
        url = "https://api.deepseek.com/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        prompt = """Ты должен написать ТОЛЬКО готовый юмористический текст. НЕ пиши "мы должны", "нужно", "я напишу" и т.д.

Напиши короткий смешной текст (2-3 предложения) в стиле мужского разговора. 
Текст должен быть законченным и готовым к публикации.

Примеры правильных ответов:
- "Бля, базаришь, Илья. Я что-то тоже поднабрал на японской лапше. Пиздец, похоже старость приходит."
- "США уже не торт. Раньше это была самая пиздатая страна. Но потом они зачем-то отменили рабство..."
- "Сижу вот, думаю сделать ларпинг на Ютубе. Куплю говняный микрофон и буду делать обзоры."

Твой ответ (ТОЛЬКО текст, без пояснений):"""

        data = {
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": "Ты стендап-комик. Отвечай только готовым текстом. Никаких рассуждений, никаких пояснений. Только юмористический текст."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 1.2,
            "max_tokens": 200,
        }
        
        print("🔄 Запрос к DeepSeek (юмор)...")
        response = requests.post(url, headers=headers, json=data, timeout=30)
        
        print(f"📊 DeepSeek статус: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ Ошибка: {response.status_code}")
            print(f"📄 Ответ: {response.text[:300]}")
            return get_fallback_caption()
        
        result = response.json()
        
        content = result["choices"][0].get("message", {}).get("content", "")
        reasoning = result["choices"][0].get("message", {}).get("reasoning_content", "")
        
        print(f"📝 content: '{content}'")
        
        # Если content пустой — пробуем извлечь из reasoning
        if not content and reasoning:
            print(f"📝 reasoning: '{reasoning[:80]}...'")
            lines = reasoning.split('\n')
            for line in lines:
                line = line.strip()
                if line and len(line) > 20 and not line.lower().startswith(("мы должны", "нужно", "я напишу", "для", "напиши")):
                    content = line
                    break
            if not content:
                content = lines[-1].strip() if lines else reasoning[:150]
        
        if not content or len(content.strip()) < 5:
            print("❌ Пустой ответ")
            return get_fallback_caption()
        
        caption = content.strip().strip('"').strip("'")
        
        # Если ответ начинается с мета-текста — это рассуждение
        if caption.lower().startswith(("мы должны", "нужно", "для поста", "я напишу", "напиши", "тебе нужно")):
            print("⚠️ DeepSeek выдал рассуждение, использую fallback")
            return get_fallback_caption()
        
        print(f"✅ Юмор: {caption[:50]}...")
        return caption  # ← ТОЛЬКО ТЕКСТ, БЕЗ ФЛАГОВ И ФОТОАППАРАТА
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return get_fallback_caption()

def get_fallback_caption() -> str:
    """Резервные юмористические описания (без флагов)"""
    captions = [
        "Бля, базаришь, Илья. Я что-то тоже в последнее время поднабрал на японской лапше. Пиздец, похоже старость приходит.",
        "США уже не торт. Раньше это была самая пиздатая страна. Но потом они зачем-то отменили рабство...",
        "Сижу вот, думаю, может сделать ларпинг на Ютубе. Куплю говняный микрофон, создам канал Larpysson.",
        "Ищу кучерявого напарника для канала Юрий Ларпинкий. Сыграем Пушкина в видосе Городок.",
        "Хочу заларпить видос 'Слава Роду'. Родинку на груди уже нарисовал, а вот футболку найти не могу.",
        "Пиздец, похоже старость приходит. Хорошо, что хотя бы лысина стороной обошла (тьфу-тьфу-тьфу).",
        "Вроде у бати и у деда нет лысины, поэтому шансы кажется в мою пользу.",
        "Скуфяры в чате - присоединяйтесь. Завтра все встаём с утра и начинаем считать калории.",
        "Едим овощи, варим гречку, и побольше мяса - лучше куриную грудку. Держимся минимум 2 месяца.",
        "Вольно, бойцы. Всё взвешиваем, скидываем в ChatGPT, чтобы подсчитал калории.",
        "Бля, базаришь, Илья. Я что-то тоже поднабрал на японской лапше в наваристом свином бульоне.",
        "Сижу вот, думаю сделать ларпинг на Ютубе. Куплю говняный микрофон, создам канал Larpysson, и буду делать обзор на Месть Боксёра...",
        "Раньше это была самая пиздатая страна на планете. Но потом они зачем-то отменили рабство..."
    ]
    return random.choice(captions)

# ===== ОСТАЛЬНОЙ КОД (БЕЗ ИЗМЕНЕНИЙ) =====

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
    
    for query in queries:
        photo = search_bing(query)
        if photo:
            return photo
        time.sleep(0.3)
    
    for query in queries:
        photo = search_google_direct(query)
        if photo:
            return photo
        time.sleep(0.3)
    
    for query in queries:
        photo = search_pexels(query)
        if photo:
            return photo
        time.sleep(0.3)
    
    return None

async def send_photo(chat_id):
    try:
        photo_url = get_random_photo()
        
        if photo_url:
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
        print(f"❌ Ошибка: {e}")
        return False

async def send_to_all():
    if not active_chats:
        return
    
    for chat_id in list(active_chats.keys()):
        await send_photo(chat_id)
        await asyncio.sleep(5)

async def scheduler():
    await asyncio.sleep(5)
    await send_to_all()
    
    while True:
        await asyncio.sleep(3 * 3600)
        await send_to_all()

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
            await msg.answer("❌ Я должен быть администратором группы!")
            return
    
    active_chats[chat_id] = {
        "type": chat_type,
        "added_by": user_id,
        "added_at": datetime.now().isoformat(),
        "name": msg.chat.title or msg.chat.first_name or str(chat_id)
    }
    save_chats()
    
    await msg.answer(
        f"✅ Бот активирован!\n"
        f"📌 Тип: {chat_type}\n"
        f"🧠 Нейросеть: {'✅ DeepSeek V4 (юмор)' if DEEPSEEK_API_KEY else '❌ Резервные описания'}\n"
        f"📸 Фото азиаток с юмором каждые 3 часа\n"
        f"🔄 /photo - получить фото сейчас\n"
        f"🛑 /stop - отключить бота"
    )
    
    await asyncio.sleep(1)
    await send_photo(chat_id)

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
        await msg.answer("⚠️ Бот не активирован. Напишите /start")
        return
    
    await msg.answer("🔍 Ищу фото и придумываю шутку...")
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
        save_chats()
        await msg.answer("🛑 Бот отключён в этом чате")

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
    
    status_text = (
        f"📊 Статус бота:\n"
        f"• В этом чате: {'✅ Активен' if is_active else '❌ Неактивен'}\n"
        f"• Всего чатов: {len(active_chats)}\n"
        f"• Нейросеть: {'✅ DeepSeek V4 (юмор)' if DEEPSEEK_API_KEY else '❌ Резервные описания'}\n"
        f"• Поиск: Bing + Google + Pexels"
    )
    
    await msg.answer(status_text)

@dp.message(Command("test_ai"))
async def test_ai(msg: Message):
    OWNER_ID = int(os.getenv("CHAT_ID", 0))
    
    if msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён.")
        return
    
    await msg.answer("🧠 Генерирую юмористическое описание через DeepSeek V4...")
    
    caption = generate_caption_with_deepseek()
    await msg.answer(f"📝 Результат:\n\n{caption}")

async def main():
    print("=" * 60)
    print("🤖 Бот запущен (юмористический режим)")
    print("🔍 Поиск в: Bing → Google → Pexels")
    print("🌏 Только азиатки: японки, китаянки, кореянки")
    
    if DEEPSEEK_API_KEY:
        print("🧠 Нейросеть: DeepSeek V4 ✅")
        print("📝 Режим: юмористические описания (без флагов)")
    else:
        print("📝 Резервные описания (AI не настроен)")
    
    print("=" * 60)
    
    gc.collect()
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook удалён")
    except Exception as e:
        print(f"⚠️ Ошибка webhook: {e}")
    
    asyncio.create_task(scheduler())
    
    try:
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
            skip_updates=True
        )
    except TelegramConflictError as e:
        print(f"⚠️ Конфликт: {e}")
        await asyncio.sleep(5)
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
