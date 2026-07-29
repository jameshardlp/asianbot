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
    """Загружает историю отправленных фото"""
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_history(history):
    """Сохраняет историю отправленных фото"""
    try:
        # Оставляем только последние 100 фото
        if len(history) > 100:
            history = history[-100:]
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f)
    except:
        pass

history = load_history()

# ===== КОЛЛЕКЦИЯ ДЛИННЫХ ПОСТОВ В СТИЛЕ @MADDYSONTG =====

def get_maddyson_style_caption() -> str:
    """Длинные посты в стиле @maddysontg про азиатских женщин"""
    captions = [
        # Про внешность и первое впечатление
        "Смотрю на азиатку и думаю: вот это поворот. Я-то думал, что люблю блондинок, а тут такая хуйня. Ладно, буду расширять горизонты. Но, бля, это надо видеть. Она такая маленькая и хрупкая, что кажется, дунь — и она улетит. Но глаза, сука, такие, что в них можно утонуть. Я теперь понимаю, почему мужики сходят с ума по азиаткам. Это не просто внешность, это какой-то другой уровень. Ладно, пошёл искать билеты в Таиланд.",

        "Азиатки — это вообще отдельный вид. С виду нежные, а внутри как терминатор. Я бы такую в разведку отправил, а не на свидание. Она тебе улыбается, а потом через пять минут рассказывает, как в детстве занималась карате и пиздила всех мальчишек. И ты сидишь и думаешь: 'А нахуя я вообще сюда пришёл?' Но уйти уже не можешь — затянуло. Вот так и попадаются.",

        "Встретил азиатку в кафе. Она такая маленькая, что я думал, она школьница. А ей 28 лет. Вот это я попал. Заказали суши, она показывает, как правильно есть палочками. А я сижу, как ёблан, и не могу нормально кусок рыбы подцепить. Она смеётся, а я думаю: 'Господи, как я докатился до такой жизни?' Но смех у неё такой, что хочется ещё раз услышать. Хотя бы ради этого готов позориться дальше.",

        "Азиатки — это как суши: сначала не поймёшь, а потом втягиваешься. Теперь я хочу их каждый день. В смысле суши, а не девушек. Ну, девушек тоже. Но, бля, это не сравнить с тем, что я пробовал раньше. Европейки — это как бургер: быстро, вкусно, но через час уже жалеешь. Азиатки — это как роллы: с виду просто, а внутри столько всего, что до конца не распробуешь.",

        # Про отношения
        "Завел отношения с азиаткой. Думал, будет как в аниме — нежно и романтично. А она меня таскает на тренировки по карате. Пиздец, я просто хотел обниматься. Теперь я знаю три способа, как уронить человека на лопатки, и могу защитить себя в тёмном переулке. Но она не перестаёт меня учить. Говорит, что я слишком слабый. А я думаю: 'Бля, я просто хочу мир и покой, а не быть бойцом ММА'. Но уйти уже не могу — привязался.",

        "Азиатка сказала, что я слишком расслабленный. Теперь я хожу на йогу, медитирую и пью зеленый чай. Я даже не знаю, кто я теперь. Зато стал гибким. Могу достать пальцами до пола без проблем. Но она всё равно говорит, что я слишком медленный. Наверное, мне нужно стать самураем, чтобы её устроить. Ладно, куплю катану и буду ждать её у входа с цветами.",

        "Спорить с азиаткой — это как играть в шахматы с компьютером. Ты думаешь, что выигрываешь, а она уже на 10 ходов вперед просчитала твой проигрыш. И потом, когда ты уже проиграл, она тебе объясняет, почему ты был не прав. И ты сидишь такой весь в мыслях: 'Я просто хотел, чтобы она выбрала, куда пойти вечером, а теперь я выслушиваю лекцию о том, как устроен мир'.",

        "Азиатки — это тест на прочность. Если ты выжил после первой недели, считай, ты прошел боевое крещение. Теперь ты готов к чему угодно. Они не дают расслабиться ни на секунду. Но в этом есть свой кайф. Ты просыпаешься, идёшь на работу, думаешь, что сегодня будет спокойный день. А она уже придумала, как затащить тебя на тренировку по стрельбе из лука.",

        # Про культуру
        "Попробовал настоящую японскую кухню. Теперь я понимаю, почему они такие худые. Это просто есть невозможно, если ты не самурай. Я сижу, пытаюсь съесть что-то склизкое палочками, а она смотрит на меня и улыбается. Я думаю: 'Бля, я бы съел пиццу сейчас, но она бы меня за это убила'. И все равно я втянулся. Теперь дома у меня стоят палочки и рисоварка. Пиздец, я стал другим человеком.",

        "Китаянки удивляют. Такие милые, пока ты не начинаешь спорить с ними про политику. Я лучше буду молчать и кивать. Иначе это превращается в войну нервов. Я однажды попытался пошутить про их президента — она на меня так посмотрела, что я за 5 минут выучил всю историю Китая. Теперь я молчу и просто киваю. Главное — улыбаться.",

        "Кореянки — это отдельный вид. Они выглядят как куклы, но говорят так, что хочется закрыть уши. Но красивые, бля, очень красивые. У них даже походка особая. Как будто они по подиуму идут, а не по улице. Я смотрю на них и думаю: 'Господи, как они это делают?' Потом понимаю, что это генетика. А я всего лишь человек.",

        "Японки — это как фильмы Миядзаки. Вроде сказка, а внутри такая глубина, что мозг кипит. Я уже месяц хожу и думаю. И не могу понять, это я влюбился или просто хочу посмотреть все их фильмы. Но она говорит, что я должен учить японский. Твою мать, я ещё и английский нормально не выучил.",

        # Про жизнь с азиаткой
        "Жизнь с азиаткой — это как сериал: никогда не знаешь, что будет в следующей серии. Но скучно точно не будет. Сегодня она учит меня готовить роллы, а завтра уже объясняет, как правильно держать меч. Я думал, что мы будем смотреть фильмы и обниматься, а я уже прошел курс молодого бойца.",

        "Азиатка научила меня правильно есть палочками. А теперь я не могу есть даже суп без них. Пиздец, куда я качусь. Вчера сидел в ресторане, попросил суп с палочками, официант посмотрел на меня как на сумасшедшего. А я уже не могу по-другому. Это как наркотик.",

        "В азиатской семье главное — уважение к старшим. Пришлось запомнить всех тетушек и дядюшек. Я теперь знаю больше, чем в школе учил. Но они нормальные, правда. Главное — не спорить с бабушкой. Она всё равно победит.",

        # Бытовые с азиатками
        "Азиатка переставила всю мебель в квартире. Теперь я не могу найти даже свою зубную щетку. Но зато выглядит красиво, как в журнале. Я сижу и думаю, где мои носки. А она говорит, что положила их в специальную корзину. Какая, нахуй, корзина? У нас их три теперь.",

        "Азиатки обожают порядок. Я положил носки не в ту корзину — она меня так отчитала, что я до сих пор боюсь подходить к шкафу. Теперь у меня инструкция, куда что класть. Я чувствую себя солдатом в армии. Но зато дома всегда чисто.",

        "У них дома всегда идеально чисто. Я начал замечать пыль на столах. Я, который раньше мог неделю не убираться, теперь знаю, где какая тряпка лежит. Я даже могу отличить средство для стёкол от средства для сантехники. Прогресс.",

        # Про внешность и чувства
        "Азиатки — это не просто красивые, они как произведения искусства. Хочется смотреть и смотреть. Но смотреть долго нельзя — они начинают стесняться. А потом они говорят что-то типа 'Ты чего уставился?'. И ты понимаешь, что это не скромность, а просто они хотят, чтобы ты сказал что-то умное. А я не умею.",

        "У них такие глаза, что можно утонуть. И не говори, что не замечал. Просто признай, ты тоже туда смотришь. Я смотрел в их глаза и забывал, что хотел сказать. А потом она говорит 'Ну и что ты хотел?'. А я уже не помню. И так каждый раз.",

        "Азиатки — это сочетание нежности и стали. Когда она обнимает, кажется, что она тебя сломает. Но это приятно, на самом деле. В ней есть что-то дикое и в то же время родное. Ты чувствуешь себя защищённым, хотя она маленькая.",

        # Дополнительные длинные посты
        "Слушай, я тут подумал, азиатки реально меняют жизнь. Ты думал, что будешь просто смотреть аниме и есть доширак, а теперь ты ходишь на курсы каллиграфии. И это не шутка. Я уже умею писать иероглифы. Зачем? Не знаю, но она сказала, что это красиво. И я, как дурак, учу. Пиздец.",

        "Мне кажется, что азиатки обладают какой-то магией. Ты смотришь на них и не можешь оторваться. Но самое интересное, что они это знают и используют. Ты думаешь, что ты выбираешь, а на самом деле они уже всё решили за тебя. И ты идёшь за ними как привязанный. Я бы сказал, что это прекрасно, но я лучше промолчу."
    ]
    return random.choice(captions)

# ===== ГЕНЕРАЦИЯ ОПИСАНИЙ =====

def generate_caption() -> str:
    """Возвращает длинный пост в стиле @maddysontg про азиаток"""
    print("📝 Генерирую длинный пост в стиле Maddyson...")
    return get_maddyson_style_caption()

# ===== ПОИСК ФОТО С ИСТОРИЕЙ =====

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
    """Получает случайное фото, которого нет в истории"""
    global history
    
    queries = SEARCH_QUERIES.copy()
    random.shuffle(queries)
    
    # Пробуем найти фото, которого нет в истории
    for _ in range(20):  # Максимум 20 попыток
        for query in queries:
            photo = search_bing(query)
            if photo and photo not in history:
                # Добавляем фото в историю
                history.append(photo)
                save_history(history)
                print(f"✅ Найдено новое фото: {photo[:50]}...")
                return photo
            time.sleep(0.3)
        
        for query in queries:
            photo = search_google_direct(query)
            if photo and photo not in history:
                history.append(photo)
                save_history(history)
                print(f"✅ Найдено новое фото: {photo[:50]}...")
                return photo
            time.sleep(0.3)
        
        for query in queries:
            photo = search_pexels(query)
            if photo and photo not in history:
                history.append(photo)
                save_history(history)
                print(f"✅ Найдено новое фото: {photo[:50]}...")
                return photo
            time.sleep(0.3)
    
    # Если не удалось найти новое фото — берём любое
    for query in queries:
        photo = search_bing(query)
        if photo:
            history.append(photo)
            save_history(history)
            print(f"⚠️ Использую повторное фото: {photo[:50]}...")
            return photo
    
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
        await asyncio.sleep(3)

async def scheduler():
    """
    Отправляет посты 2 раза в сутки
    В 9:00 и в 21:00
    """
    while True:
        now = datetime.now()
        
        target_times = [9, 21]
        next_hour = None
        
        for hour in target_times:
            if now.hour < hour or (now.hour == hour and now.minute < 5):
                next_hour = hour
                break
        
        if next_hour is None:
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
        f"📸 Я буду присылать фото азиаток с юмором 2 раза в день\n"
        f"⏰ В 9:00 и в 21:00 по вашему времени\n"
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
    
    await msg.answer("🔍 Ищу фото и шутку в стиле Maddyson...")
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
        f"• Расписание: 9:00 и 21:00"
    )
    
    await msg.answer(status_text)

@dp.message(Command("test"))
async def test(msg: Message):
    OWNER_ID = int(os.getenv("CHAT_ID", 0))
    
    if msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён.")
        return
    
    await msg.answer("🧠 Генерирую длинный пост в стиле Maddyson про азиаток...")
    
    caption = generate_caption()
    await msg.answer(f"📝 Результат:\n\n{caption}")

@dp.message(Command("clear_history"))
async def clear_history(msg: Message):
    """Очищает историю фото (только для владельца)"""
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

async def main():
    print("=" * 60)
    print("🤖 Бот запущен (стиль @maddysontg + азиатки)")
    print("🔍 Поиск в: Bing → Google → Pexels")
    print(f"📊 Подписчиков: {len(users)}")
    print(f"📸 Фото в истории: {len(history)}")
    print("⏰ Расписание: 9:00 и 21:00")
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
