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
from datetime import datetime, time as dt_time
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

# ===== РАБОТА С ПОЛЬЗОВАТЕЛЯМИ =====

def load_users():
    """Загружает список пользователей из JSON"""
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_users(users):
    """Сохраняет список пользователей в JSON"""
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(users, f)
    except:
        pass

# Загружаем пользователей
users = load_users()

# ===== КОЛЛЕКЦИЯ ПОСТОВ В СТИЛЕ @MADDYSONTG (ПРО АЗИАТОК) =====

def get_maddyson_style_caption() -> str:
    """Посты в стиле @maddysontg про азиатских женщин"""
    captions = [
        # Про внешность
        "Смотрю на азиатку и думаю: вот это поворот. Я-то думал, что люблю блондинок, а тут такая хуйня. Ладно, буду расширять горизонты.",
        "Азиатки — это вообще отдельный вид. С виду нежные, а внутри как терминатор. Я бы такую в разведку отправил, а не на свидание.",
        "Встретил азиатку в кафе. Она такая маленькая, что я думал, она школьница. А ей 28 лет. Вот это я попал.",
        "Азиатки — это как суши: сначала не поймёшь, а потом втягиваешься. Теперь я хочу их каждый день. В смысле суши, а не девушек. Ну, девушек тоже.",
        
        # Про отношения
        "Завел отношения с азиаткой. Думал, будет как в аниме — нежно и романтично. А она меня таскает на тренировки по карате. Пиздец, я просто хотел обниматься.",
        "Азиатка сказала, что я слишком расслабленный. Теперь я хожу на йогу, медитирую и пью зеленый чай. Я даже не знаю, кто я теперь.",
        "Спорить с азиаткой — это как играть в шахматы с компьютером. Ты думаешь, что выигрываешь, а она уже на 10 ходов вперед просчитала твой проигрыш.",
        "Азиатки — это тест на прочность. Если ты выжил после первой недели, считай, ты прошел боевое крещение. Теперь ты готов к чему угодно.",
        
        # Про культуру
        "Попробовал настоящую японскую кухню. Теперь я понимаю, почему они такие худые. Это просто есть невозможно, если ты не самурай.",
        "Китаянки удивляют. Такие милые, пока ты не начинаешь спорить с ними про политику. Я лучше буду молчать и кивать.",
        "Кореянки — это отдельный вид. Они выглядят как куклы, но говорят так, что хочется закрыть уши. Но красивые, бля, очень красивые.",
        "Японки — это как фильмы Миядзаки. Вроде сказка, а внутри такая глубина, что мозг кипит. Я уже месяц хожу и думаю.",
        
        # Про жизнь с азиаткой
        "Жизнь с азиаткой — это как сериал: никогда не знаешь, что будет в следующей серии. Но скучно точно не будет.",
        "Азиатка научила меня правильно есть палочками. А теперь я не могу есть даже суп без них. Пиздец, куда я качусь.",
        "В азиатской семье главное — уважение к старшим. Пришлось запомнить всех тетушек и дядюшек. Я теперь знаю больше, чем в школе учил.",
        
        # Бытовые с азиатками
        "Азиатка переставила всю мебель в квартире. Теперь я не могу найти даже свою зубную щетку. Но зато выглядит красиво, как в журнале.",
        "Азиатки обожают порядок. Я положил носки не в ту корзину — она меня так отчитала, что я до сих пор боюсь подходить к шкафу.",
        "У них дома всегда идеально чисто. Я начал замечать пыль на столах. Я, который раньше мог неделю не убираться, теперь знаю, где какая тряпка лежит.",
        
        # Про внешность
        "Азиатки — это не просто красивые, они как произведения искусства. Хочется смотреть и смотреть. Но смотреть долго нельзя — они начинают стесняться.",
        "У них такие глаза, что можно утонуть. И не говори, что не замечал. Просто признай, ты тоже туда смотришь.",
        "Азиатки — это сочетание нежности и стали. Когда она обнимает, кажется, что она тебя сломает. Но это приятно, на самом деле.",
    ]
    return random.choice(captions)

# ===== ГЕНЕРАЦИЯ ОПИСАНИЙ =====

def generate_caption() -> str:
    """Возвращает пост в стиле @maddysontg про азиаток"""
    print("📝 Генерирую пост в стиле Maddyson...")
    return get_maddyson_style_caption()

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
            caption = generate_caption()
            
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
    """Отправляет пост всем пользователям"""
    global users
    
    if not users:
        print("⚠️ Нет пользователей для отправки")
        return
    
    print(f"📤 Отправка поста {len(users)} пользователям...")
    
    for chat_id in users:
        await send_photo(chat_id)
        await asyncio.sleep(3)  # Задержка между пользователями

async def scheduler():
    """
    Отправляет посты 2 раза в сутки
    В 9:00 и в 21:00
    """
    while True:
        now = datetime.now()
        
        # Вычисляем время до следующей отправки
        target_times = [9, 21]  # 9:00 и 21:00
        next_hour = None
        
        for hour in target_times:
            if now.hour < hour or (now.hour == hour and now.minute < 5):
                next_hour = hour
                break
        
        if next_hour is None:
            # Если все отправки на сегодня прошли — ждём завтра 9:00
            next_hour = 9
            tomorrow = now + timedelta(days=1)
            target_time = datetime(tomorrow.year, tomorrow.month, tomorrow.day, next_hour, 0, 0)
        else:
            target_time = datetime(now.year, now.month, now.day, next_hour, 0, 0)
        
        wait_seconds = (target_time - now).total_seconds()
        
        if wait_seconds < 0:
            wait_seconds += 24 * 3600
        
        print(f"⏳ Следующая отправка в {target_time.strftime('%H:%M')} (через {wait_seconds/3600:.1f} часов)")
        
        await asyncio.sleep(wait_seconds)
        await send_to_all_users()

# ===== КОМАНДЫ БОТА =====

@dp.message(Command("start"))
async def start(msg: Message):
    """Добавляет пользователя в список"""
    global users
    
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    chat_type = msg.chat.type
    
    # Проверяем админа (для групп)
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
    
    # Добавляем пользователя в список, если его ещё нет
    if chat_id not in users:
        users.append(chat_id)
        save_users(users)
        print(f"✅ Добавлен пользователь: {chat_id}")
    
    await msg.answer(
        f"✅ Вы подписаны на рассылку!\n"
        f"📸 Я буду присылать фото азиаток с юмором 2 раза в день\n"
        f"⏰ В 9:00 и в 21:00 по вашему времени\n"
        f"🔄 /photo - получить фото сейчас\n"
        f"🛑 /stop - отписаться"
    )
    
    await asyncio.sleep(1)
    await send_photo(chat_id)

@dp.message(Command("photo"))
async def photo(msg: Message):
    """Отправляет фото сейчас"""
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    chat_type = msg.chat.type
    
    if chat_type in ["group", "supergroup"]:
        if not await is_user_admin(chat_id, user_id):
            await msg.reply("⛔ Только администраторы могут запрашивать фото.")
            return
    
    await msg.answer("🔍 Ищу фото и шутку в стиле Maddyson...")
    await send_photo(chat_id)

@dp.message(Command("stop"))
async def stop(msg: Message):
    """Удаляет пользователя из списка"""
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
    """Показывает статус бота"""
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
        f"• Расписание: 9:00 и 21:00\n"
        f"• Поиск: Bing + Google + Pexels"
    )
    
    await msg.answer(status_text)

@dp.message(Command("test"))
async def test(msg: Message):
    """Тестовая команда для проверки стиля"""
    OWNER_ID = int(os.getenv("CHAT_ID", 0))
    
    if msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён.")
        return
    
    await msg.answer("🧠 Генерирую пост в стиле Maddyson про азиаток...")
    
    caption = generate_caption()
    await msg.answer(f"📝 Результат:\n\n{caption}")

@dp.message(Command("broadcast"))
async def broadcast(msg: Message):
    """Отправляет сообщение всем подписчикам (только для владельца)"""
    OWNER_ID = int(os.getenv("CHAT_ID", 0))
    
    if msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён.")
        return
    
    # Получаем текст после команды
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
            # Если бот заблокирован — удаляем пользователя
            if "forbidden" in str(e).lower():
                users.remove(chat_id)
                save_users(users)
    
    await msg.answer(f"✅ Отправлено {sent} подписчикам")

async def main():
    print("=" * 60)
    print("🤖 Бот запущен (стиль @maddysontg + азиатки)")
    print("🔍 Поиск в: Bing → Google → Pexels")
    print("🌏 Только азиатки: японки, китаянки, кореянки")
    print(f"📊 Подписчиков: {len(users)}")
    print("⏰ Расписание: 9:00 и 21:00")
    print("=" * 60)
    
    gc.collect()
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook удалён")
    except Exception as e:
        print(f"⚠️ Ошибка webhook: {e}")
    
    # Запускаем планировщик
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
