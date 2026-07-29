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
from datetime import datetime, timedelta
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

USERS_FILE = "users.json"
HISTORY_FILE = "history.json"

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

def truncate_caption(text: str, max_length: int = 1000) -> str:
    """
    Обрезает текст до максимальной длины, заканчивая на последней точке,
    вопросительном или восклицательном знаке. Если знаков нет — обрезает до
    последнего пробела и ставит точку.
    """
    if len(text) <= max_length:
        return text

    truncated = text[:max_length]

    # Ищем последний знак завершения предложения
    last_punct = -1
    for p in ('.', '!', '?'):
        pos = truncated.rfind(p)
        if pos > last_punct:
            last_punct = pos

    # Если нашли — обрезаем до него включительно
    if last_punct != -1:
        return truncated[:last_punct + 1]

    # Если знаков нет — ищем последний пробел
    last_space = truncated.rfind(' ')
    if last_space != -1:
        return truncated[:last_space] + '.'

    # Если и пробела нет — просто обрезаем
    return truncated

def clean_text(text: str) -> str:
    """Заменяет длинное тире на обычное и убирает упоминания @maddysontg"""
    text = text.replace('—', '-').replace('–', '-')
    text = text.replace('@maddysontg', '').replace('@Maddysontg', '').replace('@MADDYSONTG', '')
    text = text.replace('maddysontg', '').replace('Maddysontg', '').replace('MADDYSONTG', '')
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# ===== РАБОТА С ПОЛЬЗОВАТЕЛЯМИ =====

def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_users(users):
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(users, f)
    except:
        pass

users = load_users()

# ===== РАБОТА С ИСТОРИЕЙ ФОТО =====

def load_history():
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_history(history):
    try:
        if len(history) > 100:
            history = history[-100:]
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f)
    except:
        pass

history = load_history()

# ===== КЭШ ДЛЯ ПОСЛЕДНИХ ПОСТОВ =====
last_posts = []

def add_to_last_posts(text: str):
    global last_posts
    key = text[:100]
    last_posts.append(key)
    if len(last_posts) > 20:
        last_posts.pop(0)

def is_similar(text: str) -> bool:
    global last_posts
    key = text[:100]
    for post in last_posts:
        same_chars = sum(1 for a, b in zip(key, post) if a == b)
        if len(key) > 10 and same_chars / len(key) > 0.7:
            return True
    return False

# ===== ГЕНЕРАЦИЯ ПОСТОВ ЧЕРЕЗ DEEPSEEK API =====

def generate_caption() -> str:
    print("🧠 Генерирую уникальный пост...")
    
    if not DEEPSEEK_API_KEY:
        print("⚠️ Нет ключа DeepSeek, использую резерв")
        return clean_text(get_fallback_caption())
    
    prompt_templates = [
        """Ты - Анатолий, известный блогер. Твой стиль - провокационный, пошлый, с черным юмором. Пиши ТОЛЬКО готовый пост, без рассуждений. ИСПОЛЬЗУЙ ТОЛЬКО ОБЫЧНОЕ ТИРЕ "-". НЕ УПОМИНАЙ @maddysontg.

Напиши пост про азиатских женщин. Будь оригинален. Пост должен быть:
- 700-900 символов
- Провокационным, с острым юмором
- С матом
- С неожиданной концовкой
- Без упоминаний других блогеров

Твой ответ (ТОЛЬКО пост):""",

        """Ты - Анатолий, блогер-провокатор. Твой стиль - эпатаж, пошлость и черный юмор. Пиши только готовый пост. Только обычное тире "-". НЕ УПОМИНАЙ @maddysontg.

Напиши пост про азиатских женщин. Придумай что-то новое. Требования:
- 700-900 символов
- Острый юмор, провокация
- Мат для эмоций
- Завершённая мысль
- Без упоминаний других блогеров

Твой ответ (ТОЛЬКО пост):""",

        """Ты - Анатолий. Пиши в своём стиле - провокационно, с самоиронией и матом. Только готовый пост, без пояснений. Используй только обычное тире "-". НЕ УПОМИНАЙ @maddysontg.

Сгенерируй пост про азиатских женщин. Сделай его уникальным. Пост:
- 700-900 символов
- С острым юмором и пошлостью
- С матом
- С неожиданной мыслью в конце
- Без упоминаний других блогеров

Твой ответ (ТОЛЬКО пост):"""
    ]
    
    for attempt in range(3):
        try:
            url = "https://api.deepseek.com/chat/completions"
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            prompt = random.choice(prompt_templates)
            
            data = {
                "model": "deepseek-v4-flash",
                "messages": [
                    {"role": "system", "content": "Ты стендап-комик Анатолий. Отвечай только готовым постом. Никаких рассуждений. Только текст поста. Используй только обычное тире '-'. НЕ УПОМИНАЙ ДРУГИХ БЛОГЕРОВ."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 1.3,
                "max_tokens": 600,
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code != 200:
                print(f"❌ DeepSeek ошибка: {response.status_code}")
                continue
            
            result = response.json()
            content = result["choices"][0].get("message", {}).get("content", "")
            
            if not content:
                content = result["choices"][0].get("message", {}).get("reasoning_content", "")
            
            if not content or len(content.strip()) < 20:
                print("❌ Пустой или короткий ответ")
                continue
            
            caption = content.strip().strip('"').strip("'")
            
            if caption.lower().startswith(("мы должны", "нужно", "я должен", "напиши", "вот")):
                print("⚠️ DeepSeek выдал рассуждение, пробуем другой промпт...")
                continue
            
            if is_similar(caption):
                print("⚠️ Пост похож на недавний, пробуем ещё...")
                continue
            
            caption = clean_text(caption)
            add_to_last_posts(caption)
            print(f"✅ Сгенерирован уникальный пост: {caption[:50]}...")
            return caption
            
        except Exception as e:
            print(f"❌ Ошибка генерации (попытка {attempt+1}): {e}")
            continue
    
    print("⚠️ Не удалось сгенерировать уникальный пост, использую резерв")
    return clean_text(get_fallback_caption())

def get_fallback_caption() -> str:
    fallbacks = [
        "Бля, смотрю на азиатку и думаю: вот это поворот. Я-то думал, что люблю блондинок, а тут такая хуйня. Глаза, сука, такие, что забываешь, как дышать. И улыбка от которой у меня встал не только член, но и желание жить. Сижу и думаю: нахуя я тратил время на всех этих ебаных моделей? Теперь я хочу учить японский, есть палочками и смотреть аниме. Пиздец, куда качусь.",
        
        "Слушай, я тут подумал, азиатки реально меняют жизнь. Ты думал, что будешь просто смотреть аниме и есть доширак, а теперь ты ходишь на курсы каллиграфии. И это не шутка. Я уже умею писать иероглифы. Зачем? Не знаю, но она сказала, что это красиво. И я, как дурак, учу. Пиздец. Теперь я мечтаю о том, чтобы она надела кимоно и села сверху. А она говорит: 'Ты такой смешной, когда пытаешься'. И я таю, сука.",
        
        "Пиздец, я влюбился в азиатку. Раньше я смеялся над друзьями, которые ездили в Таиланд. Теперь я сам готов купить билет и уехать нахуй. Она маленькая, смешная, и говорит на языке, которого я не понимаю. Но когда она смеётся, у меня сердце замирает. Я готов для неё учить всё. И даже есть палочками. Хотя это пиздец как сложно.",
        
        "Бля, встретил азиатку в кафе. Она такая маленькая, что я думал, это школьница сбежала с уроков. А ей 28 лет. Вот это я попал. Она смеётся, а я думаю: 'Господи, как я докатился до такой жизни?' Но потом она говорит: 'Ты милый, когда пытаешься'. И я понимаю, что это комплимент. Но бля, я не хочу быть милым, я хочу быть крутым. А она щипает меня за щеку, и я таю. Что за нахуй?"
    ]
    fallback = random.choice(fallbacks)
    endings = [" Вот так вот.", " И всё такое.", " Ну и хуй с ним.", " А вы как думаете?"]
    if not fallback.endswith((".", "!", "?")):
        fallback += random.choice(endings)
    return fallback

# ===== ПОИСК ФОТО =====

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
    global history
    
    if len(history) > 80:
        print("📊 История переполнена, очищаю...")
        history = []
        save_history(history)
    
    queries = SEARCH_QUERIES.copy()
    random.shuffle(queries)
    
    for attempt in range(3):
        for query in queries:
            photo = search_bing(query)
            if photo and photo not in history:
                history.append(photo)
                save_history(history)
                print(f"✅ Найдено новое фото: {photo[:60]}...")
                return photo
            
            photo = search_google_direct(query)
            if photo and photo not in history:
                history.append(photo)
                save_history(history)
                print(f"✅ Найдено новое фото: {photo[:60]}...")
                return photo
            
            photo = search_pexels(query)
            if photo and photo not in history:
                history.append(photo)
                save_history(history)
                print(f"✅ Найдено новое фото: {photo[:60]}...")
                return photo
            
            time.sleep(0.2)
    
    print("⚠️ Не удалось найти новое фото, очищаю историю...")
    history = []
    save_history(history)
    
    for query in queries:
        photo = search_bing(query)
        if photo:
            history.append(photo)
            save_history(history)
            print(f"✅ Найдено фото после очистки: {photo[:60]}...")
            return photo
        
        photo = search_google_direct(query)
        if photo:
            history.append(photo)
            save_history(history)
            print(f"✅ Найдено фото после очистки: {photo[:60]}...")
            return photo
    
    return None

async def send_photo(chat_id):
    try:
        photo_url = get_random_photo()
        
        if photo_url:
            caption = generate_caption()
            caption = truncate_caption(caption, 1000)
            
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

async def send_to_all_users():
    global users
    
    if not users:
        print("⚠️ Нет пользователей для отправки")
        return
    
    print(f"📤 Отправка поста {len(users)} пользователям...")
    
    for chat_id in users:
        await send_photo(chat_id)
        await asyncio.sleep(3)

# ===== РАСПИСАНИЕ =====

async def scheduler():
    while True:
        now = datetime.now()
        
        hour1 = random.randint(12, 14)
        minute1 = random.randint(0, 59)
        
        hour2 = random.randint(17, 21)
        minute2 = random.randint(0, 59)
        
        times = [(hour1, minute1), (hour2, minute2)]
        times.sort()
        
        target_times = []
        for hour, minute in times:
            target = datetime(now.year, now.month, now.day, hour, minute, 0)
            if target <= now:
                target += timedelta(days=1)
            target_times.append(target)
        
        wait_seconds = (target_times[0] - now).total_seconds()
        print(f"⏳ Первая отправка в {target_times[0].strftime('%H:%M')} (через {wait_seconds/3600:.1f} часов)")
        await asyncio.sleep(wait_seconds)
        await send_to_all_users()
        
        wait_seconds = (target_times[1] - target_times[0]).total_seconds()
        print(f"⏳ Вторая отправка в {target_times[1].strftime('%H:%M')} (через {wait_seconds/3600:.1f} часов)")
        await asyncio.sleep(wait_seconds)
        await send_to_all_users()

# ===== КОМАНДЫ =====

@dp.message(Command("start"))
async def start(msg: Message):
    global users
    
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
    
    if chat_id not in users:
        users.append(chat_id)
        save_users(users)
        print(f"✅ Добавлен пользователь: {chat_id}")
    
    await msg.answer(
        f"✅ Вы подписаны на рассылку!\n"
        f"📸 Уникальные посты про азиаток с острым юмором 2 раза в день\n"
        f"⏰ Первый пост: 12:00-15:00\n"
        f"⏰ Второй пост: 17:00-22:00\n"
        f"🔄 /photo - получить фото сейчас\n"
        f"🛑 /stop - отписаться"
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
    
    await msg.answer("🔥 Ждём выпадение кишки...")
    await send_photo(chat_id)

@dp.message(Command("stop"))
async def stop(msg: Message):
    global users
    
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    chat_type = msg.chat.type
    
    if chat_type in ["group", "supergroup"]:
        if not await is_user_admin(chat_id, user_id):
            await msg.reply("⛔ Только администраторы могут отключить бота.")
            return
    
    if chat_id in users:
        users.remove(chat_id)
        save_users(users)
        await msg.answer("🛑 Вы отписаны от рассылки")
        print(f"🛑 Удалён пользователь: {chat_id}")
    else:
        await msg.answer("ℹ️ Вы и так не подписаны")

@dp.message(Command("status"))
async def status(msg: Message):
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    chat_type = msg.chat.type
    
    if chat_type in ["group", "supergroup"]:
        if not await is_user_admin(chat_id, user_id):
            await msg.reply("⛔ Только администраторы могут смотреть статус.")
            return
    
    is_subscribed = chat_id in users
    
    status_text = (
        f"📊 Статус бота:\n"
        f"• Подписка: {'✅ Активна' if is_subscribed else '❌ Неактивна'}\n"
        f"• Всего подписчиков: {len(users)}\n"
        f"• Фото в истории: {len(history)}\n"
        f"• Расписание: 12:00-15:00 и 17:00-22:00"
    )
    
    await msg.answer(status_text)

@dp.message(Command("test"))
async def test(msg: Message):
    OWNER_ID = int(os.getenv("CHAT_ID", 0))
    
    if msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён.")
        return
    
    await msg.answer("🧠 Генерирую уникальный пост...")
    
    caption = generate_caption()
    caption = truncate_caption(caption, 1000)
    await msg.answer(f"📝 Результат:\n\n{caption}")

@dp.message(Command("clear_history"))
async def clear_history(msg: Message):
    global history
    
    OWNER_ID = int(os.getenv("CHAT_ID", 0))
    
    if msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён.")
        return
    
    history = []
    save_history(history)
    await msg.answer("🗑️ История фото очищена")

@dp.message(Command("broadcast"))
async def broadcast(msg: Message):
    OWNER_ID = int(os.getenv("CHAT_ID", 0))
    
    if msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён.")
        return
    
    text = msg.text.replace("/broadcast", "").strip()
    
    if not text:
        await msg.answer("ℹ️ Укажите текст для рассылки.\nПример: /broadcast Привет всем!")
        return
    
    if not users:
        await msg.answer("📭 Нет подписчиков")
        return
    
    await msg.answer(f"📤 Отправка '{text[:30]}...' {len(users)} подписчикам")
    
    sent = 0
    for chat_id in users:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            sent += 1
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Ошибка отправки в {chat_id}: {e}")
            if "forbidden" in str(e).lower():
                users.remove(chat_id)
                save_users(users)
    
    await msg.answer(f"✅ Отправлено {sent} подписчикам")

# ===== ЗАПУСК =====

async def main():
    print("=" * 60)
    print("🤖 Бот запущен (генерация уникальных постов)")
    print("🔍 Поиск в: Bing → Google → Pexels")
    print(f"📊 Подписчиков: {len(users)}")
    print(f"📸 Фото в истории: {len(history)}")
    print("⏰ Расписание: 12:00-15:00 и 17:00-22:00")
    print("📝 Уникальные посты, завершённые предложения")
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
