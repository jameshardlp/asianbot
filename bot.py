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

# ===== ДЛИННЫЕ ПРОВОКАЦИОННЫЕ ПОСТЫ =====

def get_maddyson_style_caption() -> str:
    """Длинные провокационные посты в стиле @maddysontg про азиатских женщин"""
    captions = [
        # Провокация про внешность
        "Смотрю на азиатку и думаю: вот это поворот, бля. Я-то думал, что люблю блондинок с большими сиськами, а тут такая хуйня — на тебе, маленькая и худая, как палка. Но глаза, сука, такие, что я забыл, как дышать. И улыбка, от которой у меня встал не только член, но и желание жить. Я сидел и думал: 'Господи, какого хера я тратил время на всех этих ебаных моделей из Инстаграма?' А тут такое сокровище. И она, бля, смеётся надо мной, потому что я смотрю на неё как мудак. И я понимаю, что это конец. Теперь я хочу учить японский, есть палочками и смотреть аниме. Пиздец, куда качусь. Раньше я был нормальным пацаном, а теперь я готов уебать в Токио только ради того, чтобы она продолжала на меня так смотреть.",

        "Азиатки — это вообще отдельный вид, сука. С виду нежные, как лепестки сакуры, а внутри — терминатор. Я бы такую в разведку отправил, а не на свидание. Она тебе улыбается, такая вся милая, а потом через пять минут рассказывает, как в детстве пиздила всех мальчишек на карате. И ты сидишь и думаешь: 'Нахуя я вообще сюда пришёл?' И она говорит: 'Ты слабый, но мы это исправим'. И ты понимаешь, что твоя жопа больше тебе не принадлежит. Через месяц ты уже сам просишься на тренировки. Говорят, что за это можно полюбить. Я пока не уверен, но она заставляет меня чувствовать себя живым.",

        "Встретил азиатку в кафе, бля. Она такая маленькая, что я думал, это школьница сбежала с уроков. А ей, сука, 28 лет. Вот это я попал. Заказали суши, она показывает, как правильно есть палочками. А я сижу, как ёблан, и не могу нормально кусок рыбы подцепить. Она смеётся, а я думаю: 'Господи, как я докатился до такой жизни?' Но потом она говорит: 'Ты милый, когда пытаешься'. И я понимаю, что это комплимент. Но бля, я не хочу быть милым, я хочу быть крутым. Она щипает меня за щеку, и я таю. Что за нахуй? Я же мужик, а веду себя как сопливый подросток. Теперь я каждый день хожу в это кафе, только чтобы увидеть её. Она уже знает мой заказ. Я влип, пиздец.",

        "Азиатки — это как суши, бля. Сначала не поймёшь, а потом втягиваешься. Теперь я хочу их каждый день. И суши, и девушек, если честно. Европейки — это как бургер: быстро, вкусно, но через час уже жалеешь. Азиатки — это как роллы: с виду просто, а внутри столько всего, что до конца не распробуешь. И они тебя никогда не отпустят. Ты думаешь, что это просто секс, а потом ты уже сидишь и учишь иероглифы. И она говорит: 'Ты такой смешной, когда пытаешься'. И ты понимаешь, что это уже не просто трап. Это любовь, сука. А я хотел просто трахнуть. Пиздец, как я докатился до такого.",

        # Про отношения с пошлостью
        "Завел отношения с азиаткой. Думал, будет как в аниме — нежно и романтично, она будет кормить меня с ложечки и называть семпаем. А она меня таскает на тренировки по карате. Пиздец, я просто хотел обниматься. Теперь я знаю три способа, как уронить человека на лопатки. Я стал гибким, могу достать пальцами до пола. Она говорит: 'Теперь ты готов защищать меня'. А я думаю: 'Бля, я просто хочу, чтобы ты надела короткую юбку и села сверху'. Но вместо этого я занимаюсь растяжкой. Надеюсь, она оценит мои старания. Но она не перестаёт меня учить. Она хочет сделать из меня мужчину. А я просто хочу хорошего секса.",

        "Азиатка сказала, что я слишком расслабленный. Теперь я хожу на йогу, медитирую и пью зеленый чай. Я даже не знаю, кто я теперь — мужик или просветлённый монах. Она говорит, что я должен быть сильным не только телом, но и духом. А я думаю: 'Бля, я просто хочу, чтобы ты раздвинула ноги'. Но она так на меня смотрит, что мне становится стыдно за свои мысли. И я продолжаю заниматься йогой. Зато я стал гибким. Теперь я могу её трахать в позе лотоса. Я ей об этом скажу? Не, она убьёт меня.",

        "Спорить с азиаткой — это как играть в шахматы с компьютером, бля. Ты думаешь, что выигрываешь, а она уже на 10 ходов вперед просчитала твой проигрыш. И потом, когда ты уже проиграл, она тебе объясняет, почему ты был не прав. И ты сидишь такой весь в мыслях: 'Я просто хотел, чтобы она выбрала, куда пойти вечером, а теперь я выслушиваю лекцию о том, как устроен мир'. Она говорит: 'Ты должен уважать женщин'. А я отвечаю: 'Я уважаю, когда они делают мне минет'. Она уходит в другую комнату. Через час возвращается и говорит: 'Ты был прав, я тоже хочу'. И я понимаю, что она меня проучила. Я должен просить прощения.",

        "Азиатки — это тест на прочность, сука. Если ты выжил после первой недели, считай, ты прошел боевое крещение. Теперь ты готов к чему угодно. Они не дают расслабиться ни на секунду. Но в этом есть свой кайф. Ты просыпаешься, идёшь на работу, думаешь, что сегодня будет спокойный день. А она уже придумала, как затащить тебя на тренировку по стрельбе из лука. Или на курсы каллиграфии. Или на какой-нибудь ещё хуйню. И ты идёшь, потому что боишься, что она посмотрит на тебя осуждающе. Пиздец, как это работает?",

        # Культура с пошлостью
        "Попробовал настоящую японскую кухню, бля. Теперь я понимаю, почему они такие худые. Это просто есть невозможно, если ты не самурай. Или если ты не хочешь трахать её долго и страстно. Я сижу, пытаюсь съесть что-то склизкое палочками, а она смотрит на меня и улыбается. Я думаю: 'Бля, я бы съел пиццу сейчас, но она бы меня за это убила'. И всё равно я втянулся. Теперь дома у меня стоят палочки и рисоварка. Пиздец, я стал другим человеком. Но она сказала, что я стал для неё гораздо привлекательнее. А я думаю: 'Мне не нужно быть привлекательным, мне нужен хороший секс'. Но я молчу и улыбаюсь.",

        "Китаянки удивляют, сука. Такие милые, пока ты не начинаешь спорить с ними про политику. Я лучше буду молчать и кивать. Иначе это превращается в войну нервов. Я однажды попытался пошутить про их президента — она на меня так посмотрела, что я за 5 минут выучил всю историю Китая. А потом она говорит: 'Ты такой умный, когда молчишь'. Я понял это так: 'Заткнись и не позорься'. С тех пор я просто киваю и улыбаюсь. Главное — не спорить. Она умеет так посмотреть, что у тебя яйца сжимаются до размера горошин.",

        "Кореянки — это отдельный вид. Они выглядят как куклы, но говорят так, что хочется закрыть уши. Но красивые, бля, очень красивые. У них даже походка особая. Как будто они по подиуму идут, а не по улице. Я смотрю на них и думаю: 'Господи, как они это делают?' Потом понимаю, что это генетика. А я всего лишь человек. Но когда она наклоняется, чтобы завязать шнурки, у меня перестаёт работать мозг. И она это знает. Она делает это специально, чтобы я смотрел. Она улыбается и говорит: 'Ты такой предсказуемый'. А я думаю: 'Ты специально нагибаешься, сука'. Но я люблю это.",

        "Японки — это как фильмы Миядзаки. Вроде сказка, а внутри такая глубина, что мозг кипит. Я уже месяц хожу и думаю. И не могу понять, это я влюбился или просто хочу посмотреть все их фильмы. Но она говорит, что я должен учить японский. Твою мать, я ещё и английский нормально не выучил. Она смеётся и говорит: 'Ты такой милый, когда пытаешься'. Я сказал ей: 'Я хочу выучить не только язык, но и твоё тело'. Она покраснела, но улыбнулась. Думаю, я на верном пути.",

        # Жизнь с азиаткой
        "Жизнь с азиаткой — это как сериал: никогда не знаешь, что будет в следующей серии. Но скучно точно не будет. Сегодня она учит меня готовить роллы, а завтра уже объясняет, как правильно держать меч. Я думал, что мы будем смотреть фильмы и обниматься, а я уже прошел курс молодого бойца. Она говорит: 'Ты должен быть готов защищать меня'. А я думаю: 'Я готов защищать тебя, но сначала дай мне кончить'. Но я молчу, потому что знаю, что она убьёт меня. Зато у меня теперь есть меч.",

        "Азиатка научила меня правильно есть палочками. А теперь я не могу есть даже суп без них. Пиздец, куда я качусь. Вчера сидел в ресторане, попросил суп с палочками, официант посмотрел на меня как на сумасшедшего. А я уже не могу по-другому. Это как наркотик. Она смеялась, когда я ей рассказал. А потом она сказала: 'Ты делаешь успехи, я горжусь тобой'. И я почувствовал себя так, будто сдал экзамен по математике. Нахуй она так на меня влияет?",

        "В азиатской семье главное — уважение к старшим. Пришлось запомнить всех тетушек и дядюшек. Я теперь знаю больше, чем в школе учил. Но они нормальные, правда. Главное — не спорить с бабушкой. Она всё равно победит. Я как-то попытался отказаться от добавки — она на меня так посмотрела, что я съел всё до последней крошки. А потом она погладила меня по голове и сказала: 'Хороший мальчик'. И я понял, что теперь я навсегда останусь здесь.",

        # Бытовые с пошлостью
        "Азиатка переставила всю мебель в квартире. Теперь я не могу найти даже свою зубную щетку. Но зато выглядит красиво, как в журнале. Я сижу и думаю, где мои носки. А она говорит, что положила их в специальную корзину. Какая, нахуй, корзина? У нас их три теперь. Она говорит: 'Ты должен быть организованным'. А я думаю: 'Организованным я буду, когда ты будешь сидеть на моём лице'. Но я молчу, потому что она умеет так посмотреть, что я забываю все свои грязные мысли. На время.",

        "Азиатки обожают порядок. Я положил носки не в ту корзину — она меня так отчитала, что я до сих пор боюсь подходить к шкафу. Теперь у меня инструкция, куда что класть. Я чувствую себя солдатом в армии. Но зато дома всегда чисто. И когда я прихожу с работы, она встречает меня с улыбкой и говорит: 'Ты молодец, что не насорил'. И я чувствую себя псом, которого похвалили. Но я люблю это."

        "У них дома всегда идеально чисто. Я начал замечать пыль на столах. Я, который раньше мог неделю не убираться, теперь знаю, где какая тряпка лежит. Я даже могу отличить средство для стёкол от средства для сантехники. Прогресс. Она сказала: 'Теперь ты настоящий мужчина'. А я думаю: 'Настоящий мужчина не должен знать, как чистить унитаз'. Но я молчу и улыбаюсь. Потому что вечером она это компенсирует. О, да.",

        # Про внешность и чувства
        "Азиатки — это не просто красивые, они как произведения искусства. Хочется смотреть и смотреть. Но смотреть долго нельзя — они начинают стесняться. А потом они говорят что-то типа 'Ты чего уставился?'. И ты понимаешь, что это не скромность, а просто они хотят, чтобы ты сказал что-то умное. А я не умею. Я смотрю на неё и забываю все слова на свете. Она смеётся и говорит: 'Ты такой глупый, но милый'. И я таю, как мороженое на солнце.",

        "У них такие глаза, что можно утонуть. И не говори, что не замечал. Просто признай, ты тоже туда смотришь. Я смотрел в их глаза и забывал, что хотел сказать. А потом она говорит 'Ну и что ты хотел?'. А я уже не помню. И так каждый раз. Она смеётся и говорит: 'Ты такой предсказуемый'. А я думаю: 'Я предсказуемый, когда я хочу тебя. Но я никогда не говорю этого вслух'.",

        "Азиатки — это сочетание нежности и стали. Когда она обнимает, кажется, что она тебя сломает. Но это приятно, на самом деле. В ней есть что-то дикое и в то же время родное. Ты чувствуешь себя защищённым, хотя она маленькая. И когда она шепчет на ухо что-то на своём языке, у тебя мурашки по коже. Я не понимаю ни слова, но мне кажется, что это самое красивое, что я слышал."
    ]
    return random.choice(captions)

# ===== ГЕНЕРАЦИЯ ОПИСАНИЙ =====

def generate_caption() -> str:
    """Возвращает длинный провокационный пост в стиле @maddysontg"""
    print("📝 Генерирую длинный провокационный пост...")
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
    global history
    
    queries = SEARCH_QUERIES.copy()
    random.shuffle(queries)
    
    for _ in range(20):
        for query in queries:
            photo = search_bing(query)
            if photo and photo not in history:
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
    global users
    
    if not users:
        print("⚠️ Нет пользователей для отправки")
        return
    
    print(f"📤 Отправка поста {len(users)} пользователям...")
    
    for chat_id in users:
        await send_photo(chat_id)
        await asyncio.sleep(3)

async def scheduler():
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
        f"📸 Я буду присылать фото азиаток с острым юмором 2 раза в день\n"
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
    
    await msg.answer("🔍 Ищу фото и провокационный пост...")
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
    
    await msg.answer("🧠 Генерирую провокационный пост...")
    
    caption = generate_caption()
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

async def main():
    print("=" * 60)
    print("🤖 Бот запущен (провокационный стиль)")
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
