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

# ===== ПОИСКОВЫЕ ЗАПРОСЫ =====
SEARCH_QUERIES = [
    "asian girl casual portrait",
    "japanese woman casual",
    "korean girl everyday life",
    "chinese woman casual photo",
    "asian girl summer outfit",
    "asian woman swimming pool",
    "korean girl beach",
    "japanese woman casual style",
    "asian girl in bikini",
    "asian woman summer dress",
]

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

def clean_punctuation(text: str) -> str:
    text = re.sub(r'[.!?]{2,}', '.', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.replace('«', '"').replace('»', '"')
    text = text.replace('„', '"').replace('“', '"')
    text = text.replace('`', "'").replace('´', "'")
    text = re.sub(r'[()\[\]{}<>]', '', text)
    return text.strip()

def ensure_ends_with_dot(text: str) -> str:
    text = text.strip()
    if text and text[-1] not in ('.', '!', '?'):
        return text + '.'
    return text

def truncate_by_sentences(text: str, max_length: int = 900) -> str:
    """
    Обрезает текст до целых предложений, не превышая max_length.
    Если последнее предложение не влезает целиком - оно добавляется целиком,
    даже если это превышает лимит (но не более чем на длину одного предложения).
    """
    if len(text) <= max_length:
        return ensure_ends_with_dot(text)
    
    # Ищем последний знак завершения предложения в пределах max_length
    last_punct = -1
    for p in ('.', '!', '?'):
        pos = text.rfind(p, 0, max_length)
        if pos > last_punct:
            last_punct = pos
    
    if last_punct != -1:
        result = text[:last_punct + 1]
        if len(result) <= max_length + 300:
            return ensure_ends_with_dot(result)
    
    last_space = text.rfind(' ', 0, max_length)
    if last_space != -1:
        result = text[:last_space] + '.'
        if len(result) <= max_length + 300:
            return ensure_ends_with_dot(result)
    
    result = text[:max_length]
    return ensure_ends_with_dot(result)

def clean_text(text: str) -> str:
    text = text.replace('—', '-').replace('–', '-')
    text = text.replace('@maddysontg', '').replace('@Maddysontg', '').replace('@MADDYSONTG', '')
    text = text.replace('maddysontg', '').replace('Maddysontg', '').replace('MADDYSONTG', '')
    text = re.sub(r'\s+', ' ', text).strip()
    text = clean_punctuation(text)
    return text

def is_definitely_not_asian(url: str) -> bool:
    url_lower = url.lower()
    exclude = ['african', 'black', 'white', 'caucasian', 'european', 'american',
               'latina', 'mexican', 'brazilian', 'indian', 'middle eastern',
               'arab', 'persian', 'turkish']
    for word in exclude:
        if word in url_lower:
            return True
    return False

def is_traditional_clothing(url: str) -> bool:
    url_lower = url.lower()
    traditional = ['kimono', 'hanbok', 'cheongsam', 'qi pao', 'sari', 'ao dai',
                   'traditional', 'folk costume', 'national dress']
    for word in traditional:
        if word in url_lower:
            return True
    return False

# ===== РАБОТА С ПОЛЬЗОВАТЕЛЯМИ =====

USERS_FILE = "users.json"
HISTORY_FILE = "history.json"

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

# ===== КЭШ =====
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

# ===== ГЕНЕРАЦИЯ ПОСТОВ =====

def generate_caption() -> str:
    print("🧠 Генерирую уникальный пост...")
    
    if not DEEPSEEK_API_KEY:
        print("⚠️ Нет ключа DeepSeek, использую резерв")
        return clean_text(get_fallback_caption())
    
    style = random.choice([
        'aggressive', 'romantic', 'vulgar', 'everyday', 'envy', 'funny'
    ])
    
    style_prompts = {
        'aggressive': """Ты - Анатолий, агрессивный и дерзкий блогер в стиле @maddysontg. Пиши ТОЛЬКО готовый пост. ИСПОЛЬЗУЙ МАТ. Твоя задача - выплеснуть ненависть и агрессию, но с юмором. ОБРАЩАЙСЯ К ЧИТАТЕЛЯМ ВО МНОЖЕСТВЕННОМ ЧИСЛЕ (вы, вам, вас).

Пример стиля:
"Бля, ну как же они бесят эти азиатки. Такие красивые, что просто пиздец. Сидите, смотрите на них и понимаете, что жизнь прошла мимо. Сука, почему вы не родились в Азии."

Напиши агрессивный пост про азиатских женщин. Требования:
- 500-650 символов
- Агрессивный, дерзкий, с ненавистью
- Мат 2-3 раза
- Юмор через злость
- Обращение к читателям во множественном числе
- Завершённая мысль""",

        'romantic': """Ты - Анатолий, романтичный и чувствительный блогер в стиле @maddysontg. Пиши ТОЛЬКО готовый пост. ИСПОЛЬЗУЙ МАТ 1 РАЗ. ОБРАЩАЙСЯ К ЧИТАТЕЛЯМ ВО МНОЖЕСТВЕННОМ ЧИСЛЕ (вы, вам, вас).

Пример стиля:
"Слушайте, я влюбился в азиатку. Она смеётся, и у меня сердце замирает. Маленькая, смешная, говорит на языке, которого я не понимаю. Но мне и не нужно понимать. Я просто счастлив."

Напиши романтичный пост про азиатских женщин. Требования:
- 500-650 символов
- Романтичный, нежный, чувственный
- Мат 1 раз для остроты
- С юмором
- Обращение к читателям во множественном числе
- Завершённая мысль""",

        'vulgar': """Ты - Анатолий, пошлый и развязный блогер в стиле @maddysontg. Пиши ТОЛЬКО готовый пост. ИСПОЛЬЗУЙ МАТ 2-3 РАЗА. ОБРАЩАЙСЯ К ЧИТАТЕЛЯМ ВО МНОЖЕСТВЕННОМ ЧИСЛЕ (вы, вам, вас).

Пример стиля:
"Сижу, ем доширак, смотрю на азиатку. Она в купальнике, а я в трусах. И мне хорошо. Потому что я знаю: она всё равно улыбнётся мне. Потому что я Анатолий. А вы так не умеете."

Напиши пошлый пост про азиатских женщин. Требования:
- 500-650 символов
- Пошлый, грязный, с двойным смыслом
- Мат 2-3 раза
- С юмором
- Обращение к читателям во множественном числе
- Завершённая мысль""",

        'everyday': """Ты - Анатолий, обычный парень с бытовым юмором в стиле @maddysontg. Пиши ТОЛЬКО готовый пост. ИСПОЛЬЗУЙ МАТ 1-2 РАЗА. ОБРАЩАЙСЯ К ЧИТАТЕЛЯМ ВО МНОЖЕСТВЕННОМ ЧИСЛЕ (вы, вам, вас).

Пример стиля:
"Сижу, думаю: а зачем вам всё это? Работа, деньги, проблемы. А есть она, азиатка, которая смеётся над моими шутками. И мне больше ничего не нужно."

Напиши бытовой пост про азиатских женщин. Требования:
- 500-650 символов
- Жизненный, бытовой, простой
- Мат 1-2 раза
- С юмором
- Обращение к читателям во множественном числе
- Завершённая мысль""",

        'envy': """Ты - Анатолий, успешный и уверенный блогер в стиле @maddysontg. Пиши ТОЛЬКО готовый пост. ИСПОЛЬЗУЙ МАТ 1-2 РАЗА. ОБРАЩАЙСЯ К ЧИТАТЕЛЯМ ВО МНОЖЕСТВЕННОМ ЧИСЛЕ (вы, вам, вас).

Пример стиля:
"Пиздец, я только что понял, что жизнь удалась. Я на море, рядом азиатка в купальнике. Вы там работаете, а я тут отдыхаю. Мечтайте дальше."

Напиши пост, вызывающий зависть у читателей. Требования:
- 500-650 символов
- Гордый, самоуверенный
- Мат 1-2 раза
- Вызывающий зависть
- С юмором
- Обращение к читателям во множественном числе
- Завершённая мысль""",

        'funny': """Ты - Анатолий, смешной и ироничный блогер в стиле @maddysontg. Пиши ТОЛЬКО готовый пост. ИСПОЛЬЗУЙ МАТ 1-2 РАЗА. ОБРАЩАЙСЯ К ЧИТАТЕЛЯМ ВО МНОЖЕСТВЕННОМ ЧИСЛЕ (вы, вам, вас).

Пример стиля:
"Бля, она такая смешная. Говорит что-то на своём, жестикулирует, а я ничего не понимаю. Но мне нравится. Потому что я чувствую себя живым. А вы так можете?"

Напиши смешной пост про азиатских женщин. Требования:
- 500-650 символов
- Максимально смешной, ироничный
- Мат 1-2 раза
- Шутки, сарказм
- Обращение к читателям во множественном числе
- Завершённая мысль""",
    }
    
    prompt = style_prompts.get(style, style_prompts['funny'])
    prompt += "\n\nТвой ответ (ТОЛЬКО пост):"
    
    for attempt in range(3):
        try:
            url = "https://api.deepseek.com/chat/completions"
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": "deepseek-v4-flash",
                "messages": [
                    {"role": "system", "content": f"Ты стендап-комик Анатолий в стиле @maddysontg. Отвечай только готовым постом. Никаких рассуждений. Только текст поста. Используй только обычное тире '-'. НЕ УПОМИНАЙ ДРУГИХ БЛОГЕРОВ. Используй обычные кавычки \" вместо «». ОБЯЗАТЕЛЬНО используй мат. ОБРАЩАЙСЯ К ЧИТАТЕЛЯМ ВО МНОЖЕСТВЕННОМ ЧИСЛЕ (вы, вам, вас). Стиль поста: {style}. Пост должен быть смешным."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 1.3,
                "max_tokens": 500,
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
            caption = truncate_by_sentences(caption, 900)
            
            if len(caption) < 30:
                print("⚠️ Пост слишком короткий, пробуем ещё...")
                continue
            
            add_to_last_posts(caption)
            print(f"✅ Сгенерирован пост (стиль: {style}, {len(caption)} символов)")
            return caption
            
        except Exception as e:
            print(f"❌ Ошибка генерации (попытка {attempt+1}): {e}")
            continue
    
    print("⚠️ Не удалось сгенерировать уникальный пост, использую резерв")
    return clean_text(get_fallback_caption())

def get_fallback_caption() -> str:
    fallbacks = [
        "Бля, сижу на пляже, смотрю на азиатку в купальнике и думаю: жизнь удалась. Глаза, сука, такие, что забываешь, как дышать. А вы там в офисе сидите. Пиздец, как же это круто.",
        
        "Слушайте, я влюбился в азиатку. Она смеётся, и у меня сердце замирает. Маленькая, смешная, говорит на языке, которого я не понимаю. Но мне и не нужно понимать. Я просто счастлив.",
        
        "Бля, ну как же они бесят эти азиатки. Такие красивые, что просто пиздец. Сидите, смотрите на них и понимаете, что жизнь прошла мимо. Сука, почему вы не родились в Азии.",
        
        "Сижу, ем доширак, смотрю на азиатку. Она в купальнике, а я в трусах. И мне хорошо. Потому что я знаю: она всё равно улыбнётся мне. Потому что я Анатолий. А вы так не умеете.",
        
        "Пиздец, я только что понял, что жизнь удалась. Я на море, рядом азиатка в купальнике. Вы там работаете, а я тут отдыхаю. Мечтайте дальше.",
        
        "Бля, она такая смешная. Говорит что-то на своём, жестикулирует, а я ничего не понимаю. Но мне нравится. Потому что я чувствую себя живым. А вы так можете?",
        
        "Знаете, что я понял? Азиатки - это лучшее, что случилось со мной. Они не такие, как все. Они особенные. И я готов за это бороться.",
        
        "Сижу, думаю: а зачем вам всё это? Работа, деньги, проблемы. А есть она, азиатка, которая смеётся над моими шутками. И мне больше ничего не нужно."
    ]
    return random.choice(fallbacks)

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
        url = f"https://www.bing.com/images/search?q={encoded_query}&form=HDRSC3&first=1&count=35&safeSearch=moderate"
        
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
                if not any(x in img.lower() for x in ['gstatic', 'google', 'favicon', 'logo', 'bing', 'avatar']):
                    if not is_definitely_not_asian(img):
                        if not is_traditional_clothing(img):
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
        url = f"https://www.google.com/search?q={encoded_query}&tbm=isch&safe=active&tbs=isz:l,itp:photo"
        
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
                        if not is_definitely_not_asian(img):
                            if not is_traditional_clothing(img):
                                clean_images.append(img)
        
        clean_images = list(dict.fromkeys(clean_images))
        
        if clean_images:
            return random.choice(clean_images)
        
        return None
        
    except Exception as e:
        print(f"Ошибка Google: {e}")
        return None

def search_yandex(query):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        
        encoded_query = quote(query)
        url = f"https://yandex.ru/images/search?text={encoded_query}&rdrnd=1&rpt=imageview&noreask=1"
        
        response = requests.get(url, headers=headers, timeout=15)
        
        patterns = [
            r'"img_url":"([^"]+)"',
            r'"url":"([^"]+\.(jpg|jpeg|png|webp))"',
            r'<img[^>]+src="([^"]+\.(jpg|jpeg|png|webp))"',
        ]
        
        images = []
        for pattern in patterns:
            found = re.findall(pattern, response.text)
            for item in found:
                if isinstance(item, tuple):
                    item = item[0]
                if item and not any(x in item.lower() for x in ['logo', 'favicon', 'gif']):
                    images.append(item.replace('\\u0026', '&').replace('\\/', '/'))
        
        clean_images = []
        for img in images:
            if any(ext in img.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                if not any(x in img.lower() for x in ['gstatic', 'google', 'favicon', 'logo']):
                    if not img.startswith('data:'):
                        if not is_definitely_not_asian(img):
                            if not is_traditional_clothing(img):
                                clean_images.append(img)
        
        clean_images = list(dict.fromkeys(clean_images))
        
        if clean_images:
            return random.choice(clean_images)
        
        return None
        
    except Exception as e:
        print(f"Ошибка Yandex: {e}")
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
                url = photo["src"]["large"]
                return url
        
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
    
    search_functions = [
        ('Bing', search_bing),
        ('Google', search_google_direct),
        ('Yandex', search_yandex),
        ('Pexels', search_pexels),
    ]
    
    for query in queries:
        for source_name, search_func in search_functions:
            try:
                print(f"🔍 Поиск в {source_name}: {query}")
                photo = search_func(query)
                if photo and photo not in history:
                    history.append(photo)
                    save_history(history)
                    print(f"✅ Найдено фото в {source_name}: {photo[:60]}...")
                    return photo
            except Exception as e:
                print(f"⚠️ Ошибка в {source_name}: {e}")
                continue
            
            time.sleep(0.3)
    
    print("⚠️ Не удалось найти новое фото, очищаю историю...")
    history = []
    save_history(history)
    
    for query in queries:
        for source_name, search_func in search_functions:
            try:
                photo = search_func(query)
                if photo:
                    history.append(photo)
                    save_history(history)
                    print(f"✅ Найдено фото после очистки: {photo[:60]}...")
                    return photo
            except:
                continue
    
    return None

async def send_photo(chat_id):
    try:
        photo_url = get_random_photo()
        
        if photo_url:
            full_caption = generate_caption()
            full_caption = clean_text(full_caption)
            full_caption = truncate_by_sentences(full_caption, 900)
            
            if not full_caption or len(full_caption) < 10:
                full_caption = truncate_by_sentences(get_fallback_caption(), 900)
            
            await bot.send_photo(
                chat_id=chat_id, 
                photo=photo_url,
                caption=full_caption
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

is_sending = False

async def scheduler():
    global is_sending
    
    while True:
        now = datetime.now()
        
        minute1 = random.randint(0, 59)
        minute2 = random.randint(0, 59)
        
        hour1 = random.randint(12, 14)
        hour2 = random.randint(17, 21)
        
        times = [(hour1, minute1), (hour2, minute2)]
        times.sort()
        
        target_times = []
        for hour, minute in times:
            target = datetime(now.year, now.month, now.day, hour, minute, 0)
            if target <= now:
                target += timedelta(days=1)
            target_times.append(target)
        
        wait_seconds = (target_times[0] - now).total_seconds()
        if wait_seconds > 0:
            print(f"⏳ Первая отправка в {target_times[0].strftime('%H:%M')} (через {wait_seconds/3600:.1f} часов)")
            await asyncio.sleep(wait_seconds)
        
        if not is_sending:
            is_sending = True
            try:
                await send_to_all_users()
            finally:
                is_sending = False
        else:
            print("⚠️ Отправка уже идёт, пропускаем")
        
        wait_seconds = (target_times[1] - target_times[0]).total_seconds()
        if wait_seconds > 0:
            print(f"⏳ Вторая отправка в {target_times[1].strftime('%H:%M')} (через {wait_seconds/3600:.1f} часов)")
            await asyncio.sleep(wait_seconds)
        
        if not is_sending:
            is_sending = True
            try:
                await send_to_all_users()
            finally:
                is_sending = False
        else:
            print("⚠️ Отправка уже идёт, пропускаем")

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
    
    await msg.answer("🧠 Тестирую генерацию...")
    
    caption = generate_caption()
    caption = clean_text(caption)
    caption = truncate_by_sentences(caption, 900)
    await msg.answer(f"📝 Результат:\n\n{caption}\n\n📊 Длина: {len(caption)} символов")

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
    print("🤖 Бот запущен (стиль @maddysontg, мн. число)")
    print("🔍 Приоритет: Bing → Google → Yandex → Pexels")
    print(f"📊 Подписчиков: {len(users)}")
    print(f"📸 Фото в истории: {len(history)}")
    print("⏰ Расписание: 12:00-15:00 и 17:00-22:00")
    print("📝 Максимальная длина текста: 900 символов")
    print("📝 Одно фото за запрос")
    print("📝 Обращение к читателям во множественном числе")
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
