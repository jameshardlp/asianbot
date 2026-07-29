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
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_ID = int(os.getenv("OWNER_ID", 0))

if not BOT_TOKEN:
    print("❌ Ошибка: BOT_TOKEN не задан")
    sys.exit(1)

if not OWNER_ID:
    print("⚠️ ВНИМАНИЕ: OWNER_ID не задан. Команды для владельца НЕ РАБОТАЮТ.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===== ФАЙЛЫ ДЛЯ ХРАНЕНИЯ ДАННЫХ =====
USERS_FILE = "users.json"
HISTORY_FILE = "history.json"
SCHEDULE_FILE = "schedule.json"

# ===== ОБНОВЛЁННЫЕ ПОИСКОВЫЕ ЗАПРОСЫ (18-30 ЛЕТ, ФИТНЕС) =====
SEARCH_QUERIES = [
    "asian girl 20 years old portrait",
    "young japanese woman 20s portrait",
    "korean girl 18 30 portrait",
    "chinese woman 20 years portrait",
    "asian fitness model 20s",
    "asian gym girl workout",
    "asian sport girl fitness",
    "asian fitness model portrait",
    "korean fitness girl gym",
    "japanese sport girl fitness",
    "asian athletic woman 20s",
    "asian fit girl workout",
    "asian girl casual 20s",
    "young asian woman everyday life",
    "asian girl summer style 20",
    "asian woman 20 years casual",
]

# ===== КЛЮЧЕВЫЕ СЛОВА ДЛЯ ФИЛЬТРАЦИИ =====
ASIAN_KEYWORDS = [
    'asian', 'japanese', 'korean', 'chinese', 'east asian',
    'japan', 'korea', 'china', 'tokyo', 'seoul', 'beijing',
    'sakura', 'kim', 'lee', 'park', 'chan'
]

FITNESS_KEYWORDS = [
    'gym', 'fitness', 'workout', 'sport', 'athletic',
    'fit', 'muscle', 'training', 'exercise', 'yoga',
    'pilates', 'crossfit', 'running', 'jogging'
]

AGE_POSITIVE_KEYWORDS = [
    '18', '19', '20', '21', '22', '23', '24', '25',
    '26', '27', '28', '29', '30', '20s',
    'young', 'teen', 'college', 'university'
]

EXCLUDE_KEYWORDS = [
    'african', 'black', 'white', 'caucasian', 'european', 'american',
    'latina', 'mexican', 'brazilian', 'indian', 'middle eastern',
    'arab', 'persian', 'turkish',
    'mature', 'old', 'age 40', 'age 50', 'age 60', 'senior',
    'grandma', 'elderly', 'wrinkles'
]

TRADITIONAL_EXCLUDE = [
    'kimono', 'hanbok', 'cheongsam', 'qi pao', 'sari', 'ao dai',
    'traditional', 'folk costume', 'national dress'
]

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

def clean_punctuation(text: str) -> str:
    if not text:
        return ''
    text = re.sub(r'[.!?]{2,}', '.', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.replace('«', '"').replace('»', '"')
    text = text.replace('„', '"').replace('“', '"')
    text = text.replace('`', "'").replace('´', "'")
    text = re.sub(r'[()\[\]{}<>]', '', text)
    text = re.sub(r',\s*\.', '.', text)
    return text.strip()

def ensure_ends_with_dot(text: str) -> str:
    if not text:
        return ''
    text = text.strip()
    if text[-1] not in ('.', '!', '?'):
        return text + '.'
    return text

def truncate_by_sentences(text: str, max_length: int = 900) -> str:
    if not text:
        return ''
    
    text = text.strip()
    if len(text) <= max_length:
        return ensure_ends_with_dot(text)
    
    last_punct = -1
    for p in ('.', '!', '?'):
        pos = text.rfind(p, 0, max_length)
        if pos > last_punct:
            last_punct = pos
    
    if last_punct != -1:
        result = text[:last_punct + 1]
        result = re.sub(r'\s*,+\s*\.', '.', result)
        result = re.sub(r',\s*\.', '.', result)
        result = result.strip()
        return ensure_ends_with_dot(result)
    
    last_space = text.rfind(' ', 0, max_length)
    if last_space != -1:
        result = text[:last_space] + '.'
        return ensure_ends_with_dot(result)
    
    return ensure_ends_with_dot(text[:max_length])

def clean_text(text: str) -> str:
    if not text:
        return ''
    text = text.replace('—', '-').replace('–', '-')
    text = text.replace('@maddysontg', '').replace('@Maddysontg', '').replace('@MADDYSONTG', '')
    text = text.replace('maddysontg', '').replace('Maddysontg', '').replace('MADDYSONTG', '')
    text = re.sub(r'\s+', ' ', text).strip()
    text = clean_punctuation(text)
    return text

def is_age_appropriate(url: str) -> bool:
    if not url:
        return False
    
    url_lower = url.lower()
    
    for word in AGE_POSITIVE_KEYWORDS:
        if word in url_lower:
            return True
    
    if re.search(r'\b(age|years?|yo|y/o)\b', url_lower, re.IGNORECASE):
        for word in AGE_POSITIVE_KEYWORDS:
            if word in url_lower:
                return True
        return False
    
    return True

def is_fitness_content(url: str) -> bool:
    if not url:
        return False
    
    url_lower = url.lower()
    for word in FITNESS_KEYWORDS:
        if word in url_lower:
            return True
    return False

def is_traditional_clothing(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    for word in TRADITIONAL_EXCLUDE:
        if word in url_lower:
            return True
    return False

def is_definitely_not_asian(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    for word in EXCLUDE_KEYWORDS:
        if word in url_lower:
            return True
    return False

def is_photo_acceptable(url: str) -> bool:
    if not url:
        return False
    
    if is_definitely_not_asian(url):
        return False
    
    if not is_age_appropriate(url):
        return False
    
    if is_traditional_clothing(url):
        return False
    
    return True

# ===== РАБОТА С РАСПИСАНИЕМ =====

def load_schedule():
    try:
        with open(SCHEDULE_FILE, "r") as f:
            data = json.load(f)
            if not data or not data.get("times"):
                return {"times": ["12:00", "21:00"]}
            return data
    except:
        return {"times": ["12:00", "21:00"]}

def save_schedule(schedule_data):
    try:
        with open(SCHEDULE_FILE, "w") as f:
            json.dump(schedule_data, f)
        return True
    except:
        return False

schedule_data = load_schedule()

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
    if not text:
        return
    key = text[:100]
    last_posts.append(key)
    if len(last_posts) > 20:
        last_posts.pop(0)

def is_similar(text: str) -> bool:
    global last_posts
    if not text:
        return False
    key = text[:150]
    for post in last_posts:
        same_chars = sum(1 for a, b in zip(key, post) if a == b)
        if len(key) > 10 and same_chars / len(key) > 0.65:
            return True
    return False

# ===== ГЕНЕРАЦИЯ ПОСТОВ =====

def generate_caption() -> str:
    print("🧠 Генерирую уникальный пост...")
    
    if not DEEPSEEK_API_KEY:
        print("⚠️ Нет ключа DeepSeek, использую резерв")
        return clean_text(get_fallback_caption())
    
    style = random.choice(['everyday', 'funny', 'romantic', 'envy'])
    
    style_prompts = {
        'everyday': """Ты - Анатолий, холостой блогер с ироничным юмором. Пиши ТОЛЬКО готовый пост. Используй МАТ 1-2 раза (бля, сука, пиздец, хуйня - но без оскорблений людей). ОБРАЩАЙСЯ К ЧИТАТЕЛЯМ ВО МНОЖЕСТВЕННОМ ЧИСЛЕ (вы, вам, вас). НЕ УПОМИНАЙ ЖЕНУ.

Напиши пост про молодых азиатских женщин (18-30 лет), особенно фитнес-моделей. Придумай забавную бытовую ситуацию в спортзале или на пляже. Стиль - ироничный, с юмором, простая житейская мудрость. Без оскорблений национальностей.

Требования:
- 500-650 символов
- С матом 1-2 раза
- С юмором
- Завершённая мысль""",

        'funny': """Ты - Анатолий, холостой смешной блогер. Пиши ТОЛЬКО готовый пост. Используй МАТ 1-2 раза (бля, сука, пиздец, хуйня - но без оскорблений людей). ОБРАЩАЙСЯ К ЧИТАТЕЛЯМ ВО МНОЖЕСТВЕННОМ ЧИСЛЕ (вы, вам, вас). НЕ УПОМИНАЙ ЖЕНУ.

Напиши смешной пост про молодых азиатских женщин (18-30 лет), особенно фитнес-моделей. С иронией, без оскорблений. 500-650 символов. Завершённая мысль.""",

        'romantic': """Ты - Анатолий, холостой романтичный блогер. Пиши ТОЛЬКО готовый пост. Используй МАТ 1 раз (бля, сука, пиздец - но без оскорблений). ОБРАЩАЙСЯ К ЧИТАТЕЛЯМ ВО МНОЖЕСТВЕННОМ ЧИСЛЕ (вы, вам, вас). НЕ УПОМИНАЙ ЖЕНУ.

Напиши романтичный пост про молодых азиатских женщин (18-30 лет), особенно фитнес-моделей. С юмором и лёгким матом. 500-650 символов. Завершённая мысль.""",

        'envy': """Ты - Анатолий, холостой успешный блогер. Пиши ТОЛЬКО готовый пост. Используй МАТ 1-2 раза (бля, сука, пиздец - но без оскорблений). ОБРАЩАЙСЯ К ЧИТАТЕЛЯМ ВО МНОЖЕСТВЕННОМ ЧИСЛЕ (вы, вам, вас). НЕ УПОМИНАЙ ЖЕНУ.

Напиши пост, вызывающий лёгкую зависть, про молодых азиатских женщин (18-30 лет), особенно фитнес-моделей. С юмором и матом. 500-650 символов. Завершённая мысль.""",
    }
    
    alternative_prompts = [
        "Напиши смешной пост о молодых азиатских женщинах в спортзале. С матом 1-2 раза. Без упоминаний жены. 500-650 символов.",
        "Напиши ироничный пост про молодых азиатских женщин в возрасте 18-30 лет. С матом 1-2 раза. Без оскорблений. Без упоминаний жены. 500-650 символов.",
        "Напиши забавный пост про молодых азиатских женщин. С юмором и матом. Без оскорблений. Без упоминаний жены. 500-650 символов.",
    ]
    
    prompt = style_prompts.get(style, style_prompts['funny'])
    prompt += "\n\nТвой ответ (ТОЛЬКО ПОСТ, БЕЗ РАССУЖДЕНИЙ):"
    
    for attempt in range(5):
        try:
            url = "https://api.deepseek.com/chat/completions"
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            current_prompt = prompt
            if attempt > 0:
                current_prompt = random.choice(alternative_prompts) + "\n\nТвой ответ (ТОЛЬКО ПОСТ, БЕЗ РАССУЖДЕНИЙ):"
                print(f"🔄 Пробую альтернативный промпт (попытка {attempt+1})...")
            
            data = {
                "model": "deepseek-v4-flash",
                "messages": [
                    {"role": "system", "content": "Ты стендап-комик Анатолий. Отвечай ТОЛЬКО готовым постом. НИКАКИХ РАССУЖДЕНИЙ. Только текст поста. Используй мат 1-2 раза (бля, сука, пиздец, хуйня). НЕ ОСКОРБЛЯЙ НАЦИОНАЛЬНОСТИ. НЕ УПОМИНАЙ ЖЕНУ. С юмором и иронией."},
                    {"role": "user", "content": current_prompt}
                ],
                "temperature": 1.3,
                "max_tokens": 500,
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 400:
                error_text = response.text.lower()
                if "извините" in error_text or "не могу" in error_text or "не разрешено" in error_text:
                    print(f"⚠️ Контент заблокирован, пробую другой промпт (попытка {attempt+1})...")
                    continue
            
            if response.status_code != 200:
                print(f"❌ DeepSeek ошибка: {response.status_code}")
                continue
            
            result = response.json()
            content = result["choices"][0].get("message", {}).get("content", "")
            
            if not content or len(content.strip()) < 20:
                print("❌ Пустой или короткий ответ")
                continue
            
            caption = content.strip().strip('"').strip("'")
            
            if caption.lower().startswith(("мы должны", "нужно", "я должен", "напиши", "вот", "давайте", "попробуем", "извините")):
                print("⚠️ DeepSeek выдал рассуждение или отказ, пробуем другой промпт...")
                continue
            
            if is_similar(caption):
                print("⚠️ Пост похож на недавний, пробуем ещё...")
                continue
            
            caption = clean_text(caption)
            caption = truncate_by_sentences(caption, 900)
            
            if len(caption) < 30:
                print("⚠️ Пост слишком короткий, пробуем ещё...")
                continue
            
            if re.search(r'\b(жена|жены|жене|моя жена|своя жена)\b', caption, re.IGNORECASE):
                print("⚠️ Пост содержит упоминание жены, пробуем другой промпт...")
                continue
            
            add_to_last_posts(caption)
            print(f"✅ Сгенерирован пост ({len(caption)} символов)")
            return caption
            
        except Exception as e:
            print(f"❌ Ошибка генерации (попытка {attempt+1}): {e}")
            continue
    
    print("⚠️ Не удалось сгенерировать уникальный пост, использую резерв")
    return clean_text(get_fallback_caption())

def get_fallback_caption() -> str:
    fallbacks = [
        "Вот вы сидите тут, паритесь, копите на квартиры, на тачки. А я смотрю на молодую азиатку в спортзале и думаю: блядь, как же они умеют работать над собой. Из обычной девушки сделать фитнес-модель, которая будет вас мотивировать неделю. И при этом без лишних слов.",
        
        "Слушайте, я влюбился в молодую азиатку. Она занимается фитнесом, и у меня сердце замирает. Маленькая, подтянутая, говорит на языке, которого я не понимаю. Но мне и не нужно понимать. Я просто счастлив, блядь.",
        
        "Сижу, ем доширак, смотрю на азиатку в спортзале. Она в купальнике, а я в трусах. И мне хорошо. Потому что я знаю: она всё равно улыбнётся мне. Потому что я Анатолий. А вы так не умеете, сука.",
        
        "Пиздец, я только что понял, что жизнь удалась. Я в спортзале, рядом молодая азиатка в фитнес-образе. Вы там работаете, а я тут качаюсь. Мечтайте дальше, бля.",
        
        "Знаете, что я понял? Молодые азиатки - это лучшее, что случалось со мной. Они не такие, как все. Они особенные. И я готов за это бороться, сука.",
        
        "Раньше я думал, что знаю, что такое красота. А потом увидел азиатку в спортзале. И понял, что всё, что было до этого - хуйня. Они двигаются по-другому, говорят по-другому, даже тренируются по-другому.",
    ]
    return random.choice(fallbacks)

# ===== ПОИСК ФОТО =====

async def is_user_admin(chat_id: int, user_id: int) -> bool:
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ["administrator", "creator"]
    except:
        return False

async def get_channel_id() -> str:
    if CHANNEL_ID and CHANNEL_ID.strip():
        return CHANNEL_ID.strip()
    
    try:
        me = await bot.get_me()
        print(f"🤖 Бот: @{me.username}")
        
        try:
            async with asyncio.timeout(10):
                updates = await bot.get_updates(offset=-1, limit=10)
                for update in updates:
                    if update.channel_post:
                        chat_id = update.channel_post.chat.id
                        try:
                            chat_member = await bot.get_chat_member(chat_id, bot.id)
                            if chat_member.status in ["administrator", "creator"]:
                                print(f"✅ Найден канал: {chat_id}")
                                return str(chat_id)
                        except:
                            pass
        except asyncio.TimeoutError:
            print("⚠️ Таймаут получения обновлений")
        except Exception as e:
            print(f"⚠️ Ошибка получения обновлений: {e}")
            
    except Exception as e:
        print(f"⚠️ Ошибка поиска канала: {e}")
    
    return None

def search_bing(query):
    if not query:
        return None
    
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
                    if is_photo_acceptable(img):
                        clean_images.append(img)
        
        clean_images = list(dict.fromkeys(clean_images))
        
        if clean_images:
            return random.choice(clean_images)
        
        return None
        
    except Exception as e:
        print(f"Ошибка Bing: {e}")
        return None

def search_google_direct(query):
    if not query:
        return None
    
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
                        if is_photo_acceptable(img):
                            clean_images.append(img)
        
        clean_images = list(dict.fromkeys(clean_images))
        
        if clean_images:
            return random.choice(clean_images)
        
        return None
        
    except Exception as e:
        print(f"Ошибка Google: {e}")
        return None

def search_yandex(query):
    if not query:
        return None
    
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
                        if is_photo_acceptable(img):
                            clean_images.append(img)
        
        clean_images = list(dict.fromkeys(clean_images))
        
        if clean_images:
            return random.choice(clean_images)
        
        return None
        
    except Exception as e:
        print(f"Ошибка Yandex: {e}")
        return None

def search_pexels(query):
    if not query:
        return None
    
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
                if is_photo_acceptable(url):
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
                if photo and photo not in history and is_photo_acceptable(photo):
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
                if photo and is_photo_acceptable(photo):
                    history.append(photo)
                    save_history(history)
                    print(f"✅ Найдено фото после очистки: {photo[:60]}...")
                    return photo
            except:
                continue
    
    return None

async def send_post(chat_id, photo_url=None, caption=None):
    try:
        if not photo_url:
            photo_url = get_random_photo()
        
        if not photo_url:
            return False
        
        if not caption:
            caption = generate_caption()
            caption = clean_text(caption)
            caption = truncate_by_sentences(caption, 900)
            
            if not caption or len(caption) < 10:
                caption = truncate_by_sentences(get_fallback_caption(), 900)
        
        if not caption:
            await bot.send_photo(chat_id=chat_id, photo=photo_url)
            print(f"✅ Фото (без подписи) отправлено в чат {chat_id}")
            return True
        
        await bot.send_photo(
            chat_id=chat_id,
            photo=photo_url,
            caption=caption
        )
        print(f"✅ Пост отправлен в чат {chat_id}")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка отправки в {chat_id}: {e}")
        if "forbidden" in str(e).lower() or "chat not found" in str(e).lower():
            if chat_id in users:
                users.remove(chat_id)
                save_users(users)
                print(f"🗑️ Пользователь {chat_id} удалён из-за ошибки")
        return False

async def send_to_all_users():
    global users
    
    users = load_users()
    
    if not users:
        print("⚠️ Нет пользователей для отправки")
        return
    
    print(f"📤 Отправка поста {len(users)} пользователям...")
    
    photo_url = get_random_photo()
    if not photo_url:
        print("❌ Не удалось найти фото")
        return
    
    caption = generate_caption()
    caption = clean_text(caption)
    caption = truncate_by_sentences(caption, 900)
    
    if not caption or len(caption) < 10:
        caption = truncate_by_sentences(get_fallback_caption(), 900)
    
    for chat_id in users:
        try:
            await send_post(chat_id, photo_url, caption)
            await asyncio.sleep(3)
        except Exception as e:
            print(f"❌ Ошибка отправки в {chat_id}: {e}")
    
    channel_id = CHANNEL_ID
    if not channel_id or not channel_id.strip():
        channel_id = await get_channel_id()
    
    if channel_id:
        try:
            print(f"📤 Отправка в канал {channel_id}...")
            await send_post(channel_id, photo_url, caption)
        except Exception as e:
            print(f"❌ Ошибка отправки в канал: {e}")

# ===== РАСПИСАНИЕ =====

is_sending = False

async def scheduler():
    global is_sending
    
    await asyncio.sleep(10)
    print("✅ Планировщик запущен")
    
    while True:
        now = datetime.now()
        current_schedule = load_schedule()
        times = current_schedule.get("times", ["12:00", "21:00"])
        
        target_times = []
        for time_str in times:
            try:
                hour, minute = map(int, time_str.split(':'))
                target = datetime(now.year, now.month, now.day, hour, minute, 0)
                if target <= now:
                    target += timedelta(days=1)
                target_times.append(target)
            except:
                continue
        
        if not target_times:
            target_times = [
                datetime(now.year, now.month, now.day, 12, 0, 0),
                datetime(now.year, now.month, now.day, 21, 0, 0)
            ]
            if target_times[0] <= now:
                target_times[0] += timedelta(days=1)
            if target_times[1] <= now:
                target_times[1] += timedelta(days=1)
        
        target_times.sort()
        
        for target_time in target_times:
            wait_seconds = (target_time - now).total_seconds()
            if wait_seconds > 0:
                print(f"⏳ Следующая отправка в {target_time.strftime('%H:%M')} (через {wait_seconds/3600:.1f} часов)")
                await asyncio.sleep(wait_seconds)
            
            if not is_sending:
                is_sending = True
                try:
                    await send_to_all_users()
                except Exception as e:
                    print(f"❌ Ошибка отправки: {e}")
                finally:
                    is_sending = False
            else:
                print("⚠️ Отправка уже идёт, пропускаем")
            
            now = datetime.now()

# ===== КОМАНДЫ =====

@dp.message(Command("start"))
async def start(msg: Message):
    global users
    
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    chat_type = msg.chat.type
    
    if chat_type == "channel":
        await msg.answer("ℹ️ Я работаю в канале автоматически, команды не требуются.")
        return
    
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
    
    channel_status = f"\n📢 Канал: {'✅ подключён' if CHANNEL_ID and CHANNEL_ID.strip() else '🔄 авто-поиск'}"
    current_schedule = load_schedule()
    times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
    
    await msg.answer(
        f"✅ Вы подписаны на рассылку!\n"
        f"📸 Уникальные посты про молодых азиаток (18-30 лет) с острым юмором\n"
        f"⏰ Расписание: {times}\n"
        f"📢 Авто-канал: {'найден' if await get_channel_id() else 'не найден'}\n"
        f"{channel_status}\n"
        f"🔄 /photo - получить фото сейчас\n"
        f"⏰ /schedule - изменить расписание\n"
        f"🛑 /stop - отписаться"
    )
    
    await asyncio.sleep(1)
    await send_post(chat_id)

@dp.message(Command("photo"))
async def photo(msg: Message):
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    chat_type = msg.chat.type
    
    if chat_type == "channel":
        await msg.answer("ℹ️ В канале отправка по команде не требуется.")
        return
    
    if chat_type in ["group", "supergroup"]:
        if not await is_user_admin(chat_id, user_id):
            await msg.reply("⛔ Только администраторы могут запрашивать фото.")
            return
    
    await msg.answer("🔥 Ждём выпадение кишки...")
    await send_post(chat_id)

@dp.message(Command("stop"))
async def stop(msg: Message):
    global users
    
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    chat_type = msg.chat.type
    
    if chat_type == "channel":
        await msg.answer("ℹ️ В канале отписка не требуется.")
        return
    
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
    
    if chat_type == "channel":
        channel_info = f"📊 Статус канала:\n"
        channel_info += f"• ID: {chat_id}\n"
        channel_info += f"• Бот: {'✅ админ' if await is_user_admin(chat_id, bot.id) else '❌ не админ'}"
        await msg.answer(channel_info)
        return
    
    if chat_type in ["group", "supergroup"]:
        if not await is_user_admin(chat_id, user_id):
            await msg.reply("⛔ Только администраторы могут смотреть статус.")
            return
    
    is_subscribed = chat_id in users
    channel_id = CHANNEL_ID or await get_channel_id()
    current_schedule = load_schedule()
    times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
    
    status_text = (
        f"📊 Статус бота:\n"
        f"• Подписка: {'✅ Активна' if is_subscribed else '❌ Неактивна'}\n"
        f"• Всего подписчиков: {len(users)}\n"
        f"• Фото в истории: {len(history)}\n"
        f"• Расписание: {times}\n"
        f"• Канал: {'✅ ' + channel_id if channel_id else '❌ не найден'}"
    )
    
    await msg.answer(status_text)

@dp.message(Command("schedule"))
async def schedule(msg: Message):
    global OWNER_ID
    global schedule_data
    
    if not OWNER_ID or msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён. Только для владельца.")
        return
    
    args = msg.text.replace("/schedule", "").strip()
    
    if not args:
        current_schedule = load_schedule()
        times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
        await msg.answer(
            f"📅 Текущее расписание: {times}\n\n"
            f"Чтобы изменить, напишите:\n"
            f"/schedule 10:00, 15:00, 22:00\n\n"
            f"Укажите от 1 до 4 времен в формате ЧЧ:ММ через запятую."
        )
        return
    
    new_times = []
    for time_str in args.split(','):
        time_str = time_str.strip()
        try:
            hour, minute = map(int, time_str.split(':'))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                new_times.append(f"{hour:02d}:{minute:02d}")
        except:
            continue
    
    if not new_times:
        await msg.answer("❌ Неверный формат. Используйте: /schedule 12:00, 21:00")
        return
    
    if len(new_times) > 4:
        await msg.answer("❌ Максимум 4 времени.")
        return
    
    schedule_data["times"] = new_times
    save_schedule(schedule_data)
    
    times = ", ".join(new_times)
    await msg.answer(f"✅ Расписание обновлено: {times}")

@dp.message(Command("test"))
async def test(msg: Message):
    global OWNER_ID
    
    if not OWNER_ID or msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён.")
        return
    
    await msg.answer("🧠 Тестирую генерацию...")
    
    caption = generate_caption()
    caption = clean_text(caption)
    caption = truncate_by_sentences(caption, 900)
    await msg.answer(f"📝 Результат:\n\n{caption}\n\n📊 Длина: {len(caption)} символов")

@dp.message(Command("clear_history"))
async def clear_history(msg: Message):
    global history, OWNER_ID
    
    if not OWNER_ID or msg.from_user.id != OWNER_ID:
        await msg.answer("⛔ Доступ запрещён.")
        return
    
    history = []
    save_history(history)
    await msg.answer("🗑️ История фото очищена")

@dp.message(Command("broadcast"))
async def broadcast(msg: Message):
    global OWNER_ID
    
    if not OWNER_ID or msg.from_user.id != OWNER_ID:
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
    
    channel_id = CHANNEL_ID or await get_channel_id()
    if channel_id:
        try:
            await bot.send_message(chat_id=channel_id, text=text)
            sent += 1
            print(f"✅ Отправлено в канал {channel_id}")
        except Exception as e:
            print(f"❌ Ошибка отправки в канал: {e}")
    
    await msg.answer(f"✅ Отправлено {sent} получателям")

# ===== ЗАПУСК =====

async def main():
    print("=" * 60)
    print("🤖 Бот запущен (только азиатки 18-30 лет)")
    print("🔍 Приоритет: Bing → Google → Yandex → Pexels")
    print(f"📊 Подписчиков: {len(users)}")
    print(f"📸 Фото в истории: {len(history)}")
    
    current_schedule = load_schedule()
    times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
    print(f"⏰ Расписание: {times}")
    
    print(f"📢 Канал: {CHANNEL_ID if CHANNEL_ID else 'авто-поиск'}")
    print(f"👤 Владелец: {OWNER_ID if OWNER_ID else '❌ не задан'}")
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
