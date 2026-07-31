import asyncio
import os
import random
import sys
import re
import requests
import json
import time
import gc
import hashlib
from urllib.parse import quote
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass
from enum import Enum
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Для Redis (опционально)
REDIS_AVAILABLE = False
try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    pass

# Для Telegram
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    Message, ChatMember, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, PreCheckoutQuery, LabeledPrice
)
from aiogram.exceptions import TelegramConflictError, TelegramAPIError

# ===== КОНФИГУРАЦИЯ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_ID = int(os.getenv("OWNER_ID", 0))

# Разрешённые пользователи для команды /photo в ЛС
ALLOWED_PHOTO_USERS = [OWNER_ID, 1361723521]

# Настройки для Stars
STARS_CHANNEL_ID = -1003893727881
BROADCAST_PRICE_FILE = "broadcast_price.json"

# Redis настройки
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_URL = os.getenv("REDIS_URL", None)

# Очередь задач
QUEUE_NAME = "post_queue"
MODERATION_QUEUE = "moderation_queue"

if not BOT_TOKEN:
    logger.error("BOT_TOKEN не задан")
    sys.exit(1)

if not OWNER_ID:
    logger.warning("OWNER_ID не задан. Команды для владельца НЕ РАБОТАЮТ.")

if not DEEPSEEK_API_KEY:
    logger.warning("DEEPSEEK_API_KEY не задан. Генерация текста будет использовать резервные варианты.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===== ФАЙЛЫ ДЛЯ ХРАНЕНИЯ ДАННЫХ =====
USERS_FILE = "users.json"
HISTORY_FILE = "history.json"
SCHEDULE_FILE = "schedule.json"
MEMORY_FILE = "memory.json"

# ===== РАБОТА С ЦЕНОЙ =====

def load_broadcast_price() -> int:
    try:
        with open(BROADCAST_PRICE_FILE, "r") as f:
            data = json.load(f)
            return data.get("price", 100)
    except:
        return 100

def save_broadcast_price(price: int):
    try:
        with open(BROADCAST_PRICE_FILE, "w") as f:
            json.dump({"price": price}, f)
        return True
    except:
        return False

broadcast_price = load_broadcast_price()

# ===== РАСШИРЕННЫЕ СПИСКИ КЛЮЧЕВЫХ СЛОВ =====

ASIAN_KEYWORDS = [
    'asian', 'japanese', 'korean', 'chinese', 'thai', 'vietnamese',
    'filipino', 'indonesian', 'malaysian', 'singaporean', 'taiwanese',
    'mongolian', 'burmese', 'cambodian', 'laotian', 'east asian',
    'south east asian', 'oriental', 'asia woman', 'asia model',
    'japan', 'korea', 'china', 'thailand', 'vietnam', 'philippines',
    'indonesia', 'malaysia', 'singapore', 'taiwan', 'mongolia',
    'myanmar', 'cambodia', 'laos', 'hong kong', 'macau',
    'kpop', 'k-pop', 'kdrama', 'k-drama',
]

NON_ASIAN_KEYWORDS = [
    'african', 'black', 'white', 'caucasian', 'european', 'american',
    'latina', 'mexican', 'brazilian', 'indian', 'middle eastern',
    'arab', 'persian', 'turkish', 'russian', 'ukrainian', 'polish',
    'german', 'french', 'italian', 'spanish', 'british', 'swedish',
    'norwegian', 'danish', 'dutch', 'belgian', 'swiss', 'austrian',
    'australian', 'canadian', 'colombian', 'peruvian', 'chilean',
    'argentinian', 'venezuelan', 'ecuadorian', 'bolivian', 'paraguayan',
    'uruguayan', 'guyanese', 'surinamese', 'egyptian', 'moroccan',
    'algerian', 'tunisian', 'libyan', 'nigerian', 'kenyan',
    'south african', 'ethiopian', 'ghanaian', 'senegalese', 'ugandan',
    'rwandan', 'somali', 'sudanese',
]

ASIAN_NAMES = [
    'yuki', 'haruka', 'sakura', 'ai', 'miyu', 'rina', 'mika', 'kaori',
    'hana', 'momoko', 'chihiro', 'nanami', 'hinata', 'yui', 'mizuki',
    'yeon', 'jiwoo', 'eunji', 'yuna', 'hyejin', 'sooyoung', 'jisoo',
    'minji', 'nayeon', 'jeongyeon', 'momo', 'sana', 'mina', 'dahyun',
    'chaeyoung', 'tzuyu', 'jungkook', 'taehyung', 'jimin', 'namjoon',
    'seokjin', 'yoongi', 'hoseok', 'jennie', 'lisa', 'rosé', 'jisoo',
    'xiao', 'mei', 'ling', 'fang', 'li', 'hua', 'xia', 'wei', 'ting',
    'chen', 'wang', 'zhang', 'liu', 'yang', 'zhao', 'huang', 'wu',
    'somchai', 'somsak', 'somporn', 'nong', 'lek', 'noi', 'kaew',
    'mai', 'ploy', 'fah', 'mild', 'baitoey', 'gift', 'new', 'oil',
    'aom', 'joong', 'ki', 'hoon', 'jin', 'soo', 'young', 'sun',
]

# ТОЛЬКО КЛЮЧЕВЫЕ СЛОВА ДЛЯ ДЕТЕЙ (БЕЗ ЦИФР)
CHILD_EXCLUDE_WORDS = [
    'child', 'children', 'kid', 'kids', 'baby', 'babies', 'toddler',
    'infant', 'preschool', 'kindergarten', 'schoolgirl', 'schoolboy',
    'girl scout', 'boy scout', 'cub scout', 'teen', 'teenager',
    'minor', 'underage', 'little girl', 'little boy', 'young girl',
    'young boy', 'daughter', 'son', 'family', 'family photo',
    'childhood', 'baby girl', 'baby boy', 'newborn', 'cute baby',
    'child model', 'kid model', 'baby model', 'toddler girl', 'toddler boy',
    'pigtails', 'braces', 'childhood friend', 'young teen',
    'preteen', 'tween', 'grade school', 'primary school',
    'secondary school', 'kindergarten', 'nursery', 'playground',
    'childrens', 'kids', 'childish', 'infantile',
    'schoolgirl', 'schoolboy',
]

# ИСКЛЮЧАЕМ СТУДЕНТОВ И УЧЕБНЫЕ ЗАВЕДЕНИЯ
STUDENT_EXCLUDE_WORDS = [
    'college', 'university', 'student', 'freshman', 'sophomore',
    'junior', 'senior', 'graduate', 'campus', 'dormitory',
    'school uniform', 'college student', 'university student',
    'high school', 'middle school', 'elementary school',
    'academy', 'institute', 'classroom', 'lecture',
]

TRADITIONAL_EXCLUDE = [
    'kimono', 'hanbok', 'cheongsam', 'qi pao', 'sari', 'ao dai',
    'traditional', 'folk costume', 'national dress', 'hanfu',
    'mongolian traditional', 'tibetan traditional', 'uyghur traditional',
]

MEN_EXCLUDE_WORDS = [
    'man', 'men', 'male', 'guy', 'dude', 'brother',
    'father', 'husband', 'boyfriend', 'gentleman', 'sir',
    'bloke', 'chap', 'fellow', 'lad', 'young man',
    'guy friend', 'male friend', 'with man', 'with guy',
]

OLD_EXCLUDE_WORDS = [
    'old', 'elderly', 'senior', 'aged', 'aging',
    'grandma', 'grandmother', 'grandpa', 'grandfather',
    'mature adult', 'older woman', 'aging woman',
    'senior citizen', 'retired', 'elder',
]

# ===== ПОИСКОВЫЕ ЗАПРОСЫ (ТОЛЬКО WOMAN/FEMALE, БЕЗ STUDENT/COLLEGE) =====

# KPOP МОДЕЛИ (ВЫШЕ В СПИСКЕ - ЧАЩЕ ВСЕГО)
KPOP_QUERIES = [
    "kpop idol woman portrait casual",
    "kpop female idol everyday photo",
    "korean pop star woman casual",
    "kpop woman idol street style",
    "kpop female artist portrait",
    "kpop woman singer casual outfit",
    "kpop idol woman modern portrait",
    "kpop female celebrity everyday",
    "korean pop star woman fashion",
    "kpop woman idol natural photo",
    "kpop female idol casual selfie",
    "kpop woman singer street fashion",
    "kpop idol woman beautiful portrait",
    "kpop female star everyday life",
    "kpop woman artist casual style",
]

# ОСНОВНЫЕ ЗАПРОСЫ
SEARCH_QUERIES = [
    "kpop idol woman portrait casual",
    "kpop female idol everyday photo",
    "kpop woman singer casual portrait",
    "kpop idol woman street style",
    "asian woman blogger portrait casual",
    "asian woman model everyday photo",
    "korean woman influencer portrait",
    "japanese woman model street style",
    "asian woman fashion blogger casual",
    "thai woman model everyday style",
    "asian woman instagram model portrait",
    "korean woman influencer lifestyle photo",
    "asian woman content creator portrait",
    "japanese woman fashion blogger style",
    "asian woman portrait casual style",
    "asian woman everyday life photo",
    "korean woman street style casual",
    "japanese woman modern portrait",
    "asian woman coffee shop portrait",
    "asian woman outdoor lifestyle photo",
    "asian woman friend casual photo",
    "asian woman laughing happy portrait",
    "asian woman natural smile photo",
    "asian woman casual outfit style",
    "asian woman daily life portrait",
    "asian woman city street style",
    "asian model portrait casual",
    "asian actress everyday photo",
    "korean model street style casual",
    "japanese actress modern portrait",
    "asian professional model casual",
    "asian woman beach portrait casual",
    "asian woman summer vacation photo",
    "korean woman beach style portrait",
    "japanese woman beach day casual",
    "asian woman swimming pool portrait",
    "asian woman beach walk casual",
    "thai woman beach resort style",
    "asian woman summer dress portrait",
    "asian woman sea view casual",
]

# ПЛЯЖНЫЕ ЗАПРОСЫ
BEACH_QUERIES = [
    "asian woman beach portrait casual",
    "asian woman summer vacation style",
    "korean woman beach day casual",
    "japanese woman beach outfit portrait",
    "asian woman swimming pool casual",
    "asian woman beach walk summer",
    "thai woman beach resort portrait",
    "asian woman tropical vacation style",
    "asian woman beach dress casual",
    "korean woman summer holiday portrait",
    "japanese woman sea view casual",
    "asian woman ocean beach portrait",
]

# БЛОГЕРЫ (ДОПОЛНИТЕЛЬНО)
BLOGGER_QUERIES = [
    "asian woman blogger portrait casual",
    "asian woman influencer everyday style",
    "korean woman fashion blogger portrait",
    "japanese woman lifestyle blogger photo",
    "thai woman model casual portrait",
    "asian woman content creator style",
    "filipina woman blogger portrait",
    "vietnamese woman fashion blogger",
    "asian woman beauty blogger casual",
    "korean woman instagram model portrait",
]

# ===== ФУНКЦИИ ФИЛЬТРАЦИИ (УПРОЩЁННАЯ) =====

def has_man_in_photo(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    for word in MEN_EXCLUDE_WORDS:
        if word in url_lower:
            return True
    return False

def is_old_person(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    for word in OLD_EXCLUDE_WORDS:
        if word in url_lower:
            return True
    return False

def is_student_photo(url: str) -> bool:
    """Проверка на студентов и учебные заведения"""
    if not url:
        return False
    url_lower = url.lower()
    for word in STUDENT_EXCLUDE_WORDS:
        if word in url_lower:
            return True
    return False

def is_child_photo(url: str) -> bool:
    """Проверка на детей - ТОЛЬКО ПО КЛЮЧЕВЫМ СЛОВАМ"""
    if not url:
        return False
    url_lower = url.lower()
    
    # Блокируем все детские слова
    for word in CHILD_EXCLUDE_WORDS:
        if word in url_lower:
            logger.warning(f"⚠️ Блокировка: детское слово '{word}'")
            return True
    
    # Проверяем возраст 0-17 (только когда это явно возраст)
    age_patterns = [
        r'\b(0|1|2|3|4|5|6|7|8|9|10|11|12|13|14|15|16|17)\s*(years?|yo|y/o)\b',
        r'\b(age|years?|yo|y/o)\s*(0|1|2|3|4|5|6|7|8|9|10|11|12|13|14|15|16|17)\b',
        r'\b(infant|toddler|child|kid|teen|teenager|preteen|tween|minor|underage)\b',
    ]
    for pattern in age_patterns:
        if re.search(pattern, url_lower, re.IGNORECASE):
            logger.warning(f"⚠️ Блокировка: возраст 0-17")
            return True
    
    # Блокируем школьные слова
    school_patterns = [
        r'school\s*uniform',
        r'kindergarten',
        r'nursery',
        r'playground',
        r'elementary\s*school',
        r'primary\s*school',
        r'middle\s*school',
        r'high\s*school',
        r'grade\s*school',
        r'high\s*school\s+student',
    ]
    for pattern in school_patterns:
        if re.search(pattern, url_lower, re.IGNORECASE):
            logger.warning(f"⚠️ Блокировка: школа/учебное заведение")
            return True
    
    return False

def is_asian_photo(url: str, additional_context: str = "") -> bool:
    if not url:
        return False
    text_to_check = url.lower()
    if additional_context:
        text_to_check += " " + additional_context.lower()
    
    for keyword in ASIAN_KEYWORDS:
        if keyword in text_to_check:
            return True
    for keyword in NON_ASIAN_KEYWORDS:
        if keyword in text_to_check:
            return False
    for name in ASIAN_NAMES:
        if name in text_to_check:
            return True
    
    asian_features = [
        'slender', 'petite', 'olive skin', 'dark hair', 'black hair',
        'straight hair', 'bangs', 'double eyelid', 'monolid',
        'slender figure', 'small face', 'fair skin',
        'east asian', 'southeast asian',
    ]
    for feature in asian_features:
        if feature in text_to_check:
            return True
    
    asian_domains = ['.jp', '.kr', '.cn', '.tw', '.hk', '.mo', '.sg', '.th', '.vn', '.ph', '.my', '.id']
    for domain in asian_domains:
        if domain in url.lower():
            return True
    return False

def is_age_appropriate(url: str) -> bool:
    """Проверка что это не ребёнок и не студент"""
    if not url:
        return False
    
    if is_child_photo(url):
        return False
    if is_old_person(url):
        return False
    if is_student_photo(url):
        return False
    
    # Проверяем что есть слова woman или female (не girl без woman/female)
    url_lower = url.lower()
    if 'girl' in url_lower and 'woman' not in url_lower and 'female' not in url_lower:
        # Проверяем есть ли возраст 18+ (только в этом случае пропускаем)
        if not re.search(r'\b(18|19|20|21|22|23|24|25)\b', url_lower):
            logger.warning(f"⚠️ 'girl' без 'woman'/'female' и без возраста 18+")
            return False
    
    return True

def is_traditional_clothing(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    for word in TRADITIONAL_EXCLUDE:
        if word in url_lower:
            return True
    if 'traditional dress' in url_lower or 'folk costume' in url_lower:
        return True
    return False

def is_erotic_content(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    erotic_words = [
        'naked', 'nude', 'nudity', 'porn', 'porno', 'xxx', 
        'sex', 'sexual', 'erotic', 'erotica', 'explicit',
        'bdsm', 'fetish', 'lingerie', 'playboy', 'penthouse',
        'onlyfans', 'adult content',
    ]
    for word in erotic_words:
        if word in url_lower:
            return True
    return False

def is_photo_valid(url: str) -> bool:
    """Проверяет фото по всем критериям"""
    if not url:
        return False
    
    if is_child_photo(url):
        logger.warning(f"❌ ОТКЛОНЕНО: ребёнок")
        return False
    
    if has_man_in_photo(url):
        logger.warning(f"❌ ОТКЛОНЕНО: мужчина")
        return False
    
    if is_old_person(url):
        logger.warning(f"❌ ОТКЛОНЕНО: пожилой")
        return False
    
    if is_student_photo(url):
        logger.warning(f"❌ ОТКЛОНЕНО: студент/учебное заведение")
        return False
    
    if not is_asian_photo(url):
        logger.warning(f"❌ ОТКЛОНЕНО: не азиатка")
        return False
    
    if not is_age_appropriate(url):
        logger.warning(f"❌ ОТКЛОНЕНО: возраст не подходит")
        return False
    
    if is_traditional_clothing(url):
        logger.warning(f"❌ ОТКЛОНЕНО: традиционная одежда")
        return False
    
    if is_erotic_content(url):
        logger.warning(f"❌ ОТКЛОНЕНО: эротика")
        return False
    
    return True

# ===== ФУНКЦИИ ДЛЯ ПАМЯТИ =====

def load_memory():
    try:
        with open(MEMORY_FILE, "r") as f:
            data = json.load(f)
            return data.get("last_posts", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    except Exception as e:
        logger.error(f"Ошибка загрузки памяти: {e}")
        return []

def save_memory(last_posts_list):
    try:
        to_save = last_posts_list[-50:] if len(last_posts_list) > 50 else last_posts_list
        with open(MEMORY_FILE, "w") as f:
            json.dump({"last_posts": to_save}, f)
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения памяти: {e}")
        return False

# ===== КЭШ И ПАМЯТЬ =====
last_posts = load_memory()
used_fallbacks = []

def add_to_last_posts(text: str):
    global last_posts, used_fallbacks
    if not text or len(text) < 10:
        return
    key = text[:100]
    if key in last_posts:
        return
    last_posts.append(key)
    if len(last_posts) > 50:
        last_posts.pop(0)
    save_memory(last_posts)

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

def format_text_with_paragraphs(text: str, style: str) -> str:
    if not text:
        return text
    
    if style == 'short_joke':
        return text.strip()
    
    if '\n\n' in text:
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        if len(paragraphs) > 3:
            if style == 'long':
                text = '\n\n'.join(paragraphs[:3])
            else:
                text = '\n\n'.join(paragraphs[:2])
        return text
    
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    if not sentences:
        return text
    
    if style == 'long' and len(sentences) >= 6:
        third = len(sentences) // 3
        p1 = ' '.join(sentences[:third])
        p2 = ' '.join(sentences[third:third*2])
        p3 = ' '.join(sentences[third*2:])
        return '\n\n'.join([p1, p2, p3])
    else:
        half = len(sentences) // 2
        if half == 0:
            return text
        p1 = ' '.join(sentences[:half])
        p2 = ' '.join(sentences[half:])
        return '\n\n'.join([p1, p2])

def get_fallback_caption() -> str:
    global used_fallbacks
    
    all_fallbacks = [
        "Вчера на рынке в Бангкоке продавщица назвала меня 'красивым мужчиной'. Я сразу расправил плечи, уже приготовился торговаться с чувством собственного достоинства. А она оказалась просто вежливая - так она всех мужиков называет, чтобы цену набить.\n\nНо осадочек остался, приятный такой. Домой пришёл, в зеркало посмотрел - ну вроде ничего, харизма есть. Наверное, я всё-таки красавчик, просто в этом городе слишком много настоящих красавчиков. А может, это просто тайский маркетинг. В любом случае, я купил арбуз за двойную цену и довольный ушёл. Вот так мы, мужчины, и живём - ведёмся на комплименты, даже если они просто для продажи.",
        
        "Сижу в кафе в Чиангмае, пью латте, смотрю на прохожих. Вдруг подходит местная девушка и говорит: 'Вы тот самый блогер?' Я сразу напрягся, думаю - неужели узнали? А она показывает на мою футболку с логотипом какой-то группы и говорит, что ей нравится их музыка.\n\nОказалось, она думала, что я участник группы. Я даже не стал её разочаровывать - улыбнулся, сфоткался с ней и пошёл дальше. Теперь я официально музыкант. Хотя на гитаре играю только в голове. Но знаете, приятно, когда тебя замечают, даже если по ошибке. Главное - выглядеть убедительно, а там и до настоящей славы недалеко. Или до позора. Но мы не выбираем, мы просто живём.",
        
        "Вчера решил попробовать местную уличную еду в Бангкоке. Продавец говорит: 'Очень острый!' Я такой - да ладно, я русский, меня не напугаешь. Через минуту я сидел с красным лицом, пил воду и молился всем богам.\n\nПродавец смеётся и говорит: 'Ты теперь настоящий таец!' А я думаю - ну нафиг такую национальность, я лучше буду русским с нормальным желудком. Но знаете, это был лучший том-ям в моей жизни. И самое смешное, что на следующий день я снова туда пришёл. Видимо, я мазохист. Или просто люблю острые ощущения. Или у меня проблемы с памятью. Вариантов много.",
    ]
    
    available_fallbacks = []
    for fb in all_fallbacks:
        key = fb[:50]
        if key not in [u[:50] for u in used_fallbacks[-10:]]:
            available_fallbacks.append(fb)
    
    if not available_fallbacks:
        available_fallbacks = all_fallbacks
        used_fallbacks.clear()
    
    chosen = random.choice(available_fallbacks)
    used_fallbacks.append(chosen[:50])
    if len(used_fallbacks) > 20:
        used_fallbacks.pop(0)
    
    return chosen

# ===== СТИЛИ ДЛЯ ГЕНЕРАЦИИ =====
style_prompts = {
    'short_joke': """
Ты — Анатолий, холостой блогер средних лет с отличным чувством сарказма.

ВАЖНО:
- Это КОРОТКИЙ пост (200-350 символов)
- БЕЗ АБЗАЦЕВ — сплошной текст
- Острая, саркастичная шутка про жизнь в Азии
- Самоирония — шути в первую очередь над собой
- Можно тонко подколоть Меддисона (Илью), но редко
- Можно обсудить события у стримеров/блогеров, но РЕДКО
- Без длинных историй, без воды
- Одна острая шутка или забавное наблюдение
- Можно спросить у подписчиков: "как у вас там?"

Твой стиль:
- Коротко, ёмко, САРКАСТИЧНО
- Самоирония — ты главный герой шуток
- Как будто написал в статус или твит

Напиши короткий саркастичный пост про жизнь в Азии.

Требования:
- 200-350 символов
- Мат 0-1 раз
- Одна острая шутка
- Обращайся к читателям на "вы"
- БЕЗ АБЗАЦЕВ — сплошной текст
- Пиши только готовый пост
""",

    'medium': """
Ты — Анатолий, холостой блогер средних лет. Ты саркастичный, самоироничный, иногда жестковатый, но честный. Путешествуешь по Азии.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- 2 АБЗАЦА (не больше!)
- Первый абзац: завязка и начало истории
- Второй абзац: развитие, кульминация и вывод
- Сарказм и самоирония — основа поста
- Не переезжаешь чаще раза в неделю
- У тебя НЕТ жены
- ИНОГДА давай саркастичные советы о жизни в Азии
- РЕДКО можно упомянуть Меддисона (Илью) или обсудить стримеров/блогеров

Твой стиль:
- Рассказываешь реальную историю, где ты облажался
- Самоирония и сарказм
- Живой разговорный язык

Структура:
1. Саркастичная зацепка
2. История с деталями
3. Вывод — смешной или саркастичный

Требования:
- 500-700 символов
- Мат 1-2 раза
- Одна острая шутка
- Обращайся к читателям на "вы"
- РОВНО 2 АБЗАЦА (разделяй их пустой строкой)
- Пиши только готовый пост
""",

    'long': """
Ты — Анатолий, холостой блогер средних лет. Ты саркастичный, самоироничный, иногда жёсткий, но честный.

ВАЖНО:
- Это ДЛИННЫЙ пост (850-1023 символов)
- 3 АБЗАЦА (не больше!)
- Первый абзац: завязка
- Второй абзац: развитие истории
- Третий абзац: кульминация и вывод
- Сарказм и самоирония — основа
- Не переезжаешь чаще раза в неделю
- У тебя НЕТ жены
- Можно дать саркастичный совет о жизни в Азии
- РЕДКО можно упомянуть Меддисона (Илью) или обсудить стримеров/блогеров

Твой стиль:
- Детальный рассказ с сарказмом
- Самоирония — ты главный герой
- Живой разговорный язык
- Можно добавить диалоги

Структура:
1. Саркастичная зацепка
2. Развитие истории с деталями
3. Неожиданный поворот или шутка
4. Естественный вывод

Требования:
- 850-1023 символов
- Мат 2-3 раза
- 1-2 острые шутки
- Обращайся к читателям на "вы"
- РОВНО 3 АБЗАЦА (разделяй их пустой строкой)
- Пиши только готовый пост
""",

    'everyday': """
Ты — Анатолий, холостой блогер средних лет. Ты саркастичный, самоироничный, иногда грубоватый, но честный.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- 2 АБЗАЦА (не больше!)
- Одна история из жизни в Азии
- Сарказм и самоирония
- Не переезжаешь чаще раза в неделю
- У тебя НЕТ жены
- Можно дать советы о выгодной жизни в Азии (с сарказмом)
- Чаще спрашивай у подписчиков
- РЕДКО можно обсудить стримеров или блогеров

Твой стиль:
- Рассказываешь реальные истории
- Самоирония
- Саркастичные шутки
- Пишешь живым разговорным языком

Структура:
1. Саркастичная зацепка
2. История с деталями
3. Самоироничные размышления
4. Естественный вывод

Требования:
- 500-700 символов
- Мат 1-2 раза
- Одна острая шутка
- Обращайся к читателям на "вы"
- РОВНО 2 АБЗАЦА (разделяй их пустой строкой)
- Пиши только готовый пост
""",

    'funny': """
Ты — Анатолий, холостой блогер средних лет. Ты саркастичный и самоироничный.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- 2 АБЗАЦА (не больше!)
- Смешная история, где ты облажался
- Сарказм и самоирония
- Не переезжаешь чаще раза в неделю
- У тебя НЕТ жены
- РЕДКО можно упомянуть Меддисона или стримеров

Твой стиль:
- Рассказываешь смешные истории
- Главный объект шуток — ты сам
- Сарказм и самоирония
- Пишешь живым языком

Структура:
1. Необычная ситуация
2. Подробности с диалогами
3. Самоирония
4. Смешной вывод

Требования:
- 500-700 символов
- Мат 1-2 раза
- Одна острая шутка
- Обращайся к читателям на "вы"
- РОВНО 2 АБЗАЦА (разделяй их пустой строкой)
- Пиши только готовый пост
""",

    'romantic': """
Ты — Анатолий, холостой блогер средних лет. Ты саркастичный и самоироничный, даже в романтике.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- 2 АБЗАЦА (не больше!)
- Романтичная история с сарказмом и самоиронией
- Не переезжаешь чаще раза в неделю
- У тебя НЕТ жены

Твой стиль:
- Рассказываешь о своих чувствах с сарказмом
- Немного романтики, но с самоиронией
- Честно говоришь о своих недостатках
- Добавляй одну острую шутку (про себя)

Структура:
1. Неожиданная встреча
2. Твои чувства и сомнения
3. Самоирония над собой
4. Тёплый вывод

Требования:
- 500-700 символов
- Мат 1-2 раза
- Одна острая шутка
- Обращайся к читателям на "вы"
- РОВНО 2 АБЗАЦА (разделяй их пустой строкой)
- Пиши только готовый пост
""",

    'envy': """
Ты — Анатолий, холостой блогер средних лет. Ты саркастичный и самоироничный.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- 2 АБЗАЦА (не больше!)
- Зависть с сарказмом и самоиронией
- Не переезжаешь чаще раза в неделю
- У тебя НЕТ жены
- Можно дать саркастичные советы о жизни в Азии

Твой стиль:
- Рассказываешь о том, чему завидуешь, с сарказмом
- Самоирония
- Добавляй одну острую шутку
- Пишешь живо

Структура:
1. Что тебя поразило
2. Твои размышления
3. Сравнение с собой
4. Ироничный вывод

Требования:
- 500-700 символов
- Мат 1-2 раза
- Одна острая шутка
- Обращайся к читателям на "вы"
- РОВНО 2 АБЗАЦА (разделяй их пустой строкой)
- Пиши только готовый пост
""",

    'joke': """
Ты — Анатолий, холостой блогер средних лет. Ты саркастичный и самоироничный.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- 2 АБЗАЦА (не больше!)
- 70% шуток с сарказмом, 30% наблюдений
- Не переезжаешь чаще раза в неделю
- У тебя НЕТ жены
- Можно спросить у подписчиков
- РЕДКО можно упомянуть Меддисона или стримеров

Твой стиль:
- Острые шутки без оскорблений
- Сарказм и самоирония
- Можно использовать мат
- Пишешь как в баре

Структура:
1. Жизненная ситуация
2. Острая шутка
3. Развитие
4. Ещё одна шутка или вывод

Требования:
- 500-700 символов
- Мат 1-3 раза
- 2-3 шутки, одна острая
- Обращайся к читателям на "вы"
- РОВНО 2 АБЗАЦА (разделяй их пустой строкой)
- Пиши только готовый пост
""",
}

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
    if text[-1] in ('.', '!', '?'):
        return text
    last_end = max(text.rfind('.'), text.rfind('!'), text.rfind('?'))
    if last_end != -1:
        return text[:last_end + 1].strip()
    return text

def get_sentences(text: str) -> list:
    if not text:
        return []
    return re.split(r'(?<=[.!?])\s+', text.strip())

def is_sentence_complete(sentence: str) -> bool:
    if not sentence:
        return False
    clean = re.sub(r'[.!?]$', '', sentence).strip()
    words = clean.split()
    if len(words) < 5:
        return False
    incomplete_words = ['и', 'а', 'но', 'да', 'или', 'либо', 'за', 'перед', 'под', 'над', 'без', 'для', 'про', 'через', 'между', 'среди', 'у', 'о', 'об', 'от', 'до', 'из', 'с', 'к', 'по', 'на', 'в', 'во', 'вот', 'тем', 'того', 'этого', 'того']
    last_word = words[-1].lower()
    if last_word in incomplete_words:
        return False
    incomplete_endings = [
        'в её глазах', 'в моей голове', 'в моих мыслях', 'в моей душе',
        'в моём сердце', 'в моей жизни', 'в моём мире', 'в его глазах',
        'в её голове', 'в моём сознании', 'в моей памяти', 'в моих мечтах',
        'на его лице', 'на её лице', 'в моём воображении',
        'и вы знаете', 'и я понимаю', 'и мне кажется', 'и я думаю',
        'но вы понимаете', 'но я знаю', 'и вы понимаете',
        'и я чувствую', 'и я понимаю, что', 'и я думаю, что',
        'я начинаю', 'я продолжаю', 'я хочу сказать', 'я хочу отметить',
        'я думаю о том', 'я говорю о том', 'я говорю про', 'я думаю про',
        'в общем', 'короче говоря', 'так что', 'поэтому',
        'в темноте', 'в тем', 'на тем', 'в том', 'о том',
        'и я', 'но я', 'а я', 'что я', 'когда я', 'пока я',
        'она берет', 'он берет', 'они берут', 'я беру', 'ты берешь',
        'упа', 'будто', 'как', 'словно', 'точно', 'прямо', 'почти'
    ]
    clean_lower = clean.lower()
    for ending in incomplete_endings:
        if clean_lower.endswith(ending):
            return False
    incomplete_adverbs = ['тогда', 'потом', 'сейчас', 'здесь', 'там', 'тут', 'вчера', 'today', 'завтра', 'всегда', 'никогда', 'иногда', 'уже', 'ещё', 'просто', 'даже', 'почти', 'совсем', 'очень', 'слишком', 'также', 'тоже']
    if last_word in incomplete_adverbs and len(words) < 8:
        return False
    verbs = [
        'быть', 'стать', 'являться', 'иметь', 'делать', 'сказать', 'пойти',
        'знать', 'думать', 'смотреть', 'видеть', 'слышать', 'чувствовать',
        'понимать', 'хотеть', 'мочь', 'бывать', 'начинать', 'продолжать',
        'заканчивать', 'становиться', 'оставаться', 'казаться', 'стоить',
        'говорить', 'идти', 'стоять', 'сидеть', 'лежать', 'бежать',
        'плыть', 'лететь', 'ехать', 'работать', 'учиться', 'читать',
        'писать', 'рисовать', 'петь', 'танцевать', 'играть', 'смотреть',
        'слушать', 'дышать', 'жить', 'умирать', 'родиться', 'расти',
        'помнить', 'забывать', 'любить', 'ненавидеть', 'мечтать',
        'получаться', 'получиться', 'случаться', 'случиться', 'происходить',
        'произойти', 'существовать', 'обладать', 'пользоваться', 'управлять',
        'думаю', 'знаю', 'понимаю', 'вижу', 'слышу', 'чувствую'
    ]
    has_verb = any(verb in clean_lower for verb in verbs)
    has_subject = bool(re.search(r'\b(я|ты|он|она|оно|мы|вы|они|это|тот|всё|все|кто|что|который|которые|которое|эта|этот|эти|сам|себя)\b', clean, re.IGNORECASE))
    if len(clean) > 50:
        return True
    return has_verb and has_subject

def drop_incomplete_tail(text: str) -> str:
    text = text.strip()
    if not text:
        return ''
    if text[-1] in '.!?':
        return text
    last_end = max(text.rfind('.'), text.rfind('!'), text.rfind('?'))
    if last_end != -1:
        return text[:last_end + 1].strip()
    return text

def truncate_by_sentences(text: str, max_length: int = 1023) -> str:
    if not text:
        return ''
    text = text.strip()
    text = drop_incomplete_tail(text)
    if len(text) <= max_length:
        return ensure_ends_with_dot(text)
    sentences = re.split(r'(?<=[.!?])\s+', text)
    result = []
    current_length = 0
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if current_length + len(sentence) + 1 <= max_length:
            result.append(sentence)
            current_length += len(sentence) + 1
        else:
            break
    if not result and sentences:
        first = sentences[0].strip()
        if len(first) <= max_length:
            result.append(first)
    final_text = ' '.join(result).strip()
    if final_text:
        final_text = ensure_ends_with_dot(final_text)
    return final_text

def validate_caption(text: str, min_length: int = 500, max_length: int = 1023) -> Tuple[str, Optional[str]]:
    if not text:
        return '', 'Текст пустой'
    text = clean_text(text)
    if len(text) < 10:
        return '', 'Слишком короткий'
    
    if len(text) > max_length:
        text = truncate_by_sentences(text, max_length)
        if not text:
            return '', 'Текст слишком длинный и не может быть обрезан'
    
    if not text.endswith(('.', '!', '?')):
        text = ensure_ends_with_dot(text)
    
    all_sentences = get_sentences(text)
    if not all_sentences:
        return '', 'Нет предложений'
    
    last_sentence = all_sentences[-1].strip() if all_sentences else ''
    if last_sentence:
        if not last_sentence.endswith(('.', '!', '?')):
            if len(all_sentences) > 1:
                text = ' '.join(all_sentences[:-1]).strip()
                text = ensure_ends_with_dot(text)
            else:
                return '', 'Последнее предложение не завершено'
        
        word_count = len(last_sentence.split())
        if word_count < 5:
            if len(all_sentences) > 1:
                text = ' '.join(all_sentences[:-1]).strip()
                text = ensure_ends_with_dot(text)
            else:
                return '', f'Последнее предложение слишком короткое ({word_count} слов)'
        
        if not is_sentence_complete(last_sentence):
            if len(all_sentences) > 1:
                text = ' '.join(all_sentences[:-1]).strip()
                text = ensure_ends_with_dot(text)
            else:
                return '', 'Последнее предложение не завершено логически'
    
    if min_length > 0 and len(text) < min_length:
        if len(all_sentences) < 2:
            return '', f'Слишком короткий ({len(text)} символов, нужно {min_length})'
        if min_length > 200 and len(text) < 200:
            return '', f'Слишком короткий ({len(text)} символов, нужно {min_length})'
    
    return text, None

def clean_text(text: str) -> str:
    if not text:
        return ''
    text = text.replace('—', '-').replace('–', '-')
    text = text.replace('@maddysontg', '').replace('@Maddysontg', '').replace('@MADDYSONTG', '')
    text = text.replace('maddysontg', '').replace('Maddysontg', '').replace('MADDYSONTG', '')
    text = re.sub(r'\s+', ' ', text).strip()
    text = clean_punctuation(text)
    return text

# ===== РАБОТА С ФАЙЛАМИ =====

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

def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_users(users_list):
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(users_list, f)
    except Exception as e:
        logger.error(f"Ошибка сохранения пользователей: {e}")

users = load_users()

def load_history():
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_history(history_list):
    try:
        if len(history_list) > 100:
            history_list = history_list[-100:]
        with open(HISTORY_FILE, "w") as f:
            json.dump(history_list, f)
    except Exception as e:
        logger.error(f"Ошибка сохранения истории: {e}")

history = load_history()

# ===== ПРОДОЛЖЕНИЕ ОБРЕЗАННОГО ТЕКСТА =====

def request_continuation(previous_text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return ""
    try:
        url = "https://api.deepseek.com/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        tail = previous_text[-500:]
        data = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Ты стендап-комик Анатолий. Текст поста был обрезан. Допиши ТОЛЬКО концовку — 1-3 завершающих предложения с логическим выводом. Не повторяй уже написанное. Только текст продолжения."},
                {"role": "user", "content": f"Вот текст, который оборвался:\n\n...{tail}\n\nДопиши концовку (1-3 предложения, завершающих мысль). Не повторяй текст выше."}
            ],
            "temperature": 0.9,
            "max_tokens": 400,
        }
        response = requests.post(url, headers=headers, json=data, timeout=30)
        if response.status_code == 200:
            result = response.json()
            if result.get("choices") and len(result["choices"]) > 0:
                return result["choices"][0].get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.error(f"Ошибка запроса продолжения: {e}")
    return ""

def complete_truncated_text(content: str, finish_reason: str) -> str:
    if finish_reason == "length" and content:
        logger.warning(f"Текст обрезан (finish_reason=length, {len(content)} символов). Запрашиваю продолжение...")
        continuation = request_continuation(content)
        if continuation:
            continuation = clean_text(continuation)
            if continuation:
                tail_100 = content[-100:].lower()
                cont_start = continuation[:100].lower()
                if tail_100 and cont_start and (tail_100 in cont_start or cont_start in tail_100):
                    logger.warning("Продолжение дублирует хвост, не склеиваю")
                else:
                    content = content.rstrip() + " " + continuation.strip()
                    logger.info(f"Продолжение получено (+{len(continuation)} символов)")
        else:
            logger.warning("Продолжение не получено, работаю с тем что есть")
    return content

# ===== ГЕНЕРАЦИЯ ПОСТОВ =====

def generate_caption() -> str:
    logger.info("Генерирую уникальный пост...")
    
    if not DEEPSEEK_API_KEY:
        logger.warning("Нет ключа DeepSeek, использую резерв")
        caption = get_fallback_caption()
        caption = clean_text(caption)
        caption = format_text_with_paragraphs(caption, 'medium')
        caption = truncate_by_sentences(caption)
        validated, error = validate_caption(caption, min_length=500, max_length=1023)
        if validated:
            return validated
        return clean_text(truncate_by_sentences(get_fallback_caption()))
    
    length_choices = [
        ('short', 200, 400),
        ('short', 200, 400),
        ('medium', 500, 700),
        ('medium', 500, 700),
        ('medium', 500, 700),
        ('long', 850, 1023),
        ('long', 850, 1023),
    ]
    
    selected = random.choice(length_choices)
    length_type, min_len, max_len = selected
    
    logger.info(f"Выбрана длина: {length_type.upper()} ({min_len}-{max_len} символов)")
    
    if length_type == 'short':
        style = 'short_joke'
        style_name = 'КОРОТКИЙ (шутка)'
    elif length_type == 'long':
        long_styles = ['long', 'long', 'everyday', 'joke']
        style = random.choice(long_styles)
        style_name = f'ДЛИННЫЙ (стиль: {style})'
    else:
        medium_styles = ['medium', 'everyday', 'funny', 'romantic', 'envy', 'joke']
        style = random.choice(medium_styles)
        style_name = f'СРЕДНИЙ (стиль: {style})'
    
    logger.info(f"Выбран стиль: {style_name}")
    
    prompt = style_prompts.get(style, style_prompts['medium'])
    prompt += "\n\nТвой ответ (ТОЛЬКО ПОСТ, БЕЗ РАССУЖДЕНИЙ):"
    
    # Редко добавляем упоминания (10% вероятность)
    mention_topic = random.random() < 0.1
    
    system_content = """Ты — Анатолий, саркастичный и самоироничный холостой блогер средних лет. Ты путешествуешь по Азии.

Твой стиль:
- Сарказм и самоирония — твоя основа
- Рассказываешь истории, где ты выглядишь смешно или глупо
- Шутишь в первую очередь над собой
- Можешь использовать мат для эмоций
- Пиши так, будто рассказываешь в баре

Важно:
- Пиши от первого лица
- Обращайся к читателям на "вы"
- Не упоминай жену
- Не используй штампы
- Обязательно заверши мысль - естественный вывод, не мораль
- Отвечай ТОЛЬКО готовым постом. БЕЗ РАССУЖДЕНИЙ."""

    if mention_topic:
        topics = [
            "Можно обсудить текущие события у русскоязычных стримеров или блогеров (Меддисон, Mellstroy, 404, или других). Но не слишком углубляйся.",
            "Можно упомянуть Меддисона (Илью) или других стримеров, но только кратко и с юмором.",
            "Иногда можно пошутить про стримеров или блогеров, но не увлекайся.",
            "Можно вспомнить какого-нибудь стримера или блогера, но мельком.",
        ]
        system_content += "\n\n" + random.choice(topics)
        logger.info("🔴 Добавлено обсуждение стримеров/блогеров (редко)")
    
    alternative_prompts = {
        'short': [
            "Напиши короткую саркастичную шутку про жизнь в Азии. 200-350 символов. БЕЗ АБЗАЦЕВ.",
            "Короткий саркастичный пост про Азию. 200-350 символов. БЕЗ АБЗАЦЕВ.",
            "Забавное наблюдение с самоиронией про жизнь в Азии. 200-350 символов. БЕЗ АБЗАЦЕВ.",
        ],
        'long': [
            "Напиши длинный саркастичный пост с историей про жизнь в Азии. 850-1023 символов. РОВНО 3 АБЗАЦА.",
            "Подробный саркастичный рассказ о жизни в Азии. 850-1023 символов. РОВНО 3 АБЗАЦА.",
            "Развёрнутая история из Азии с самоиронией. 850-1023 символов. РОВНО 3 АБЗАЦА.",
        ],
        'medium': [
            "Напиши саркастичный пост про жизнь в Азии. 500-700 символов. РОВНО 2 АБЗАЦА.",
            "История из жизни в Азии с самоиронией. 500-700 символов. РОВНО 2 АБЗАЦА.",
            "Саркастичная ситуация из Азии. 500-700 символов. РОВНО 2 АБЗАЦА.",
        ]
    }
    
    if length_type == 'short':
        alt_key = 'short'
    elif length_type == 'long':
        alt_key = 'long'
    else:
        alt_key = 'medium'
    
    last_error = None
    
    for attempt in range(5):
        try:
            url = "https://api.deepseek.com/chat/completions"
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            current_prompt = prompt
            if attempt > 0:
                alt = random.choice(alternative_prompts[alt_key])
                current_prompt = alt + "\n\nТвой ответ (ТОЛЬКО ПОСТ, БЕЗ РАССУЖДЕНИЙ):"
                logger.info(f"Пробую альтернативный промпт (попытка {attempt+1}/5)...")
            
            data = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": current_prompt}
                ],
                "temperature": 1.3,
                "max_tokens": 1500,
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 400:
                error_text = response.text.lower()
                if "извините" in error_text or "не могу" in error_text or "не разрешено" in error_text:
                    logger.warning(f"Контент заблокирован, пробую другой промпт (попытка {attempt+1}/5)...")
                    last_error = "Контент заблокирован"
                    continue
            
            if response.status_code != 200:
                logger.error(f"DeepSeek ошибка: {response.status_code}")
                last_error = f"HTTP {response.status_code}"
                continue
            
            result = response.json()
            if not result.get("choices") or len(result["choices"]) == 0:
                logger.warning("Нет choices в ответе")
                last_error = "Нет choices в ответе"
                continue
            
            choice = result["choices"][0]
            generated_content = choice.get("message", {}).get("content", "")
            finish_reason = choice.get("finish_reason", "")
            usage = result.get("usage", {})
            logger.info(f"finish_reason={finish_reason} | tokens={usage.get('completion_tokens', '?')} | chars={len(generated_content)}")
            
            if not generated_content:
                logger.warning("Пустой ответ")
                last_error = "Пустой ответ"
                continue
            
            if finish_reason == "length":
                generated_content = complete_truncated_text(generated_content, finish_reason)
            
            if not generated_content or len(generated_content.strip()) < 20:
                logger.warning("Пустой или короткий ответ")
                last_error = "Слишком короткий"
                continue
            
            caption = generated_content.strip().strip('"').strip("'")
            
            if not caption:
                continue
            
            if caption.lower().startswith(("мы должны", "нужно", "я должен", "напиши", "вот", "давайте", "попробуем", "извините")):
                logger.warning("DeepSeek выдал рассуждение или отказ, пробуем другой промпт...")
                last_error = "Рассуждение вместо поста"
                continue
            
            if is_similar(caption):
                logger.warning("Пост похож на недавний, пробуем ещё...")
                last_error = "Похож на предыдущий"
                continue
            
            caption = clean_text(caption)
            caption = format_text_with_paragraphs(caption, style)
            
            if len(caption) > max_len:
                caption = truncate_by_sentences(caption, max_length=max_len)
            
            actual_len = len(caption)
            
            if length_type == 'short':
                if actual_len < 100:
                    logger.warning(f"Пост слишком короткий ({actual_len} символов, нужно 100+)")
                    last_error = f"Слишком короткий ({actual_len}/100)"
                    continue
                if actual_len > 400:
                    caption = truncate_by_sentences(caption, max_length=400)
                    actual_len = len(caption)
                    if actual_len > 400:
                        logger.warning(f"Пост слишком длинный ({actual_len} символов, нужно до 400)")
                        last_error = f"Слишком длинный ({actual_len}/400)"
                        continue
            elif length_type == 'long':
                if actual_len < 700:
                    logger.warning(f"Пост слишком короткий ({actual_len} символов, нужно 700+)")
                    last_error = f"Слишком короткий ({actual_len}/700)"
                    continue
                if actual_len > 1023:
                    caption = truncate_by_sentences(caption, max_length=1023)
                    actual_len = len(caption)
                    if actual_len > 1023:
                        logger.warning(f"Пост слишком длинный ({actual_len} символов, нужно до 1023)")
                        last_error = f"Слишком длинный ({actual_len}/1023)"
                        continue
            else:
                if actual_len < 400:
                    logger.warning(f"Пост слишком короткий ({actual_len} символов, нужно 400+)")
                    last_error = f"Слишком короткий ({actual_len}/400)"
                    continue
                if actual_len > 750:
                    caption = truncate_by_sentences(caption, max_length=750)
                    actual_len = len(caption)
                    if actual_len > 750:
                        logger.warning(f"Пост слишком длинный ({actual_len} символов, нужно до 750)")
                        last_error = f"Слишком длинный ({actual_len}/750)"
                        continue
            
            if length_type == 'short':
                validated, error = validate_caption(caption, min_length=100, max_length=400)
            elif length_type == 'long':
                validated, error = validate_caption(caption, min_length=700, max_length=1023)
            else:
                validated, error = validate_caption(caption, min_length=400, max_length=750)
            
            if validated:
                final_len = len(validated)
                logger.info(f"✅ Сгенерирован пост ({final_len} символов, тип: {length_type.upper()}/{style}, попытка {attempt+1})")
                add_to_last_posts(validated)
                return validated
            else:
                logger.warning(f"Текст не прошёл проверку: {error}")
                last_error = error
                continue
            
        except Exception as e:
            logger.error(f"Ошибка генерации (попытка {attempt+1}/5): {e}")
            last_error = str(e)
            continue
    
    logger.warning(f"❌ Не удалось сгенерировать пост после 5 попыток. Последняя ошибка: {last_error}")
    logger.info("Использую резервный текст (fallback)")
    
    caption = get_fallback_caption()
    caption = clean_text(caption)
    caption = format_text_with_paragraphs(caption, 'medium')
    
    if len(caption) > 1023:
        caption = truncate_by_sentences(caption, max_length=1023)
    
    validated, error = validate_caption(caption, min_length=400, max_length=1023)
    
    if validated:
        logger.info(f"✅ Использован fallback ({len(validated)} символов)")
        add_to_last_posts(validated)
        return validated
    
    logger.error("❌ Даже fallback не прошёл валидацию!")
    emergency = "Жизнь в Азии — это постоянный сюрприз. И я, как обычно, в центре этого сюрприза. Оставайтесь на связи, коллеги!"
    add_to_last_posts(emergency)
    return emergency

# ===== ПОИСК ФОТО =====

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
        patterns = [
            r'"murl":"([^"]+)"',
            r'"mediaurl":"([^"]+)"',
            r'"contentUrl":"([^"]+)"',
            r'"url":"([^"]+)"',
        ]
        images = []
        for pattern in patterns:
            found = re.findall(pattern, response.text)
            images.extend(found)
        clean_images = []
        for img in images:
            img = img.replace('\\u0026', '&').replace('\\/', '/')
            if not any(ext in img.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                continue
            if any(x in img.lower() for x in ['gstatic', 'google', 'favicon', 'logo', 'bing', 'avatar']):
                continue
            if is_photo_valid(img):
                clean_images.append(img)
        if clean_images:
            clean_images = list(dict.fromkeys(clean_images))
            return random.choice(clean_images)
        return None
    except Exception as e:
        logger.error(f"Ошибка Bing: {e}")
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
                        if is_photo_valid(img):
                            clean_images.append(img)
        clean_images = list(dict.fromkeys(clean_images))
        if clean_images:
            return random.choice(clean_images)
        return None
    except Exception as e:
        logger.error(f"Ошибка Google: {e}")
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
                        if is_photo_valid(img):
                            clean_images.append(img)
        clean_images = list(dict.fromkeys(clean_images))
        if clean_images:
            return random.choice(clean_images)
        return None
    except Exception as e:
        logger.error(f"Ошибка Yandex: {e}")
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
                random.shuffle(photos)
                for photo in photos:
                    url = photo["src"]["large"]
                    if is_photo_valid(url):
                        return url
        return None
    except Exception as e:
        logger.error(f"Ошибка Pexels: {e}")
        return None

def search_pinterest(query):
    """Поиск на Pinterest через прямой запрос"""
    if not query:
        return None
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        encoded_query = quote(query)
        url = f"https://www.pinterest.com/search/pins/?q={encoded_query}&rs=typed"
        response = requests.get(url, headers=headers, timeout=15)
        pattern = r'"images":{"orig":{"url":"([^"]+)"'
        images = re.findall(pattern, response.text)
        clean_images = []
        for img in images:
            img = img.replace('\\u0026', '&')
            if any(ext in img.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                if is_photo_valid(img):
                    clean_images.append(img)
        if clean_images:
            clean_images = list(dict.fromkeys(clean_images))
            return random.choice(clean_images)
        return None
    except Exception as e:
        logger.error(f"Ошибка Pinterest: {e}")
        return None

# ===== АСИНХРОННАЯ ФУНКЦИЯ ПОЛУЧЕНИЯ ФОТО =====

async def get_random_photo():
    global history
    
    if len(history) > 80:
        logger.info("История переполнена, очищаю...")
        history = []
        save_history(history)
    
    queries = KPOP_QUERIES.copy()
    queries.extend(SEARCH_QUERIES.copy())
    
    if random.random() < 0.2:
        queries.extend(BEACH_QUERIES)
        logger.info("Добавлены пляжные запросы")
    
    if random.random() < 0.3:
        queries.extend(BLOGGER_QUERIES)
        logger.info("Добавлены запросы блогеров")
    
    random.shuffle(queries)
    
    search_functions = [
        ('Pinterest', search_pinterest),
        ('Bing', search_bing),
        ('Google', search_google_direct),
        ('Yandex', search_yandex),
        ('Pexels', search_pexels),
    ]
    
    for query in queries:
        for source_name, search_func in search_functions:
            try:
                logger.info(f"Поиск в {source_name}: {query}")
                photo = search_func(query)
                if photo and photo not in history:
                    if is_photo_valid(photo):
                        history.append(photo)
                        save_history(history)
                        logger.info(f"✅ Найдено подходящее фото: {photo[:60]}...")
                        return photo
            except Exception as e:
                logger.error(f"Ошибка в {source_name}: {e}")
                continue
            await asyncio.sleep(0.3)
    
    logger.warning("⚠️ Не удалось найти новое фото, очищаю историю...")
    history = []
    save_history(history)
    
    for query in queries[:10]:
        for source_name, search_func in search_functions:
            try:
                photo = search_func(query)
                if photo and is_photo_valid(photo):
                    history.append(photo)
                    save_history(history)
                    logger.info(f"✅ Найдено фото после очистки: {photo[:60]}...")
                    return photo
            except:
                continue
    
    logger.error("❌ Не удалось найти подходящее фото!")
    return None

# ===== ОЧЕРЕДЬ ЗАДАЧ =====

class TaskQueue:
    def __init__(self):
        self.redis = None
        self.connected = False
        self._local_queue: Dict[str, List[Dict[str, Any]]] = {}
    
    async def connect(self):
        if not REDIS_AVAILABLE:
            return False
        try:
            if REDIS_URL:
                self.redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            else:
                self.redis = redis.Redis(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    db=REDIS_DB,
                    password=REDIS_PASSWORD,
                    decode_responses=True
                )
            await self.redis.ping()
            self.connected = True
            logger.info("Redis подключен")
            return True
        except Exception as e:
            logger.error(f"Ошибка подключения к Redis: {e}")
            self.connected = False
            return False
    
    async def push(self, queue_name: str, data: Dict[str, Any]):
        try:
            if self.connected:
                task_id = f"{queue_name}:{int(time.time())}:{hashlib.md5(str(data).encode()).hexdigest()[:8]}"
                await self.redis.rpush(queue_name, json.dumps({
                    "id": task_id,
                    "data": data,
                    "created_at": time.time()
                }))
                logger.info(f"Задача добавлена в очередь {queue_name}: {task_id}")
                return True
            else:
                if queue_name not in self._local_queue:
                    self._local_queue[queue_name] = []
                self._local_queue[queue_name].append(data)
                logger.info(f"Задача добавлена в локальную очередь {queue_name}")
                return True
        except Exception as e:
            logger.error(f"Ошибка добавления в очередь: {e}")
            return False
    
    async def pop(self, queue_name: str) -> Optional[Dict[str, Any]]:
        try:
            if self.connected:
                item = await self.redis.lpop(queue_name)
                if item:
                    return json.loads(item)
                return None
            else:
                if queue_name in self._local_queue and self._local_queue[queue_name]:
                    return self._local_queue[queue_name].pop(0)
                return None
        except Exception as e:
            logger.error(f"Ошибка получения из очереди: {e}")
            return None
    
    async def get_queue_length(self, queue_name: str) -> int:
        try:
            if self.connected:
                return await self.redis.llen(queue_name) or 0
            else:
                if queue_name in self._local_queue:
                    return len(self._local_queue[queue_name])
                return 0
        except:
            return 0

task_queue = TaskQueue()

# ===== СИСТЕМА МОДЕРАЦИИ =====

class ModerationStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"

@dataclass
class PostContent:
    photo_url: str
    caption: str
    chat_id: str
    user_id: int
    timestamp: float
    status: ModerationStatus = ModerationStatus.PENDING
    moderator_id: Optional[int] = None
    moderation_note: Optional[str] = None
    moderation_timestamp: Optional[float] = None

class ContentModerator:
    def __init__(self):
        self.pending_posts = {}
        self.approved_history = []
        self.rejected_history = []
        self.auto_approve_threshold = 0.85
        self.banned_words = [
            'naked', 'nude', 'explicit', 'porn', 'sex', 'fuck',
            'наркотики', 'оружие', 'насилие', 'убийство', 'экстремизм',
            'child', 'children', 'kid', 'baby', 'teen', 'minor', 'underage',
            'college', 'university', 'student', 'school'
        ]
        self.suspicious_patterns = [
            r'https?://\S+\.(ru|su|cc|to|top|club|online|site|xyz|click|win|bid)',
            r'\b(купить|продать|деньги|заработать|бизнес|инвестиции)\b',
        ]
    
    async def moderate_content(self, post: PostContent) -> Tuple[Optional[bool], str]:
        try:
            text_lower = post.caption.lower()
            photo_lower = post.photo_url.lower()
            
            for word in self.banned_words:
                if word in text_lower or word in photo_lower:
                    return False, f"Обнаружено запрещенное слово: {word}"
            
            erotic_words = ['naked', 'nude', 'porn', 'xxx', 'erotic', 'explicit']
            for word in erotic_words:
                if word in text_lower or word in photo_lower:
                    return False, f"Обнаружено эротическое содержание: {word}"
            
            for pattern in self.suspicious_patterns:
                if re.search(pattern, post.caption, re.IGNORECASE):
                    return False, "Обнаружена подозрительная ссылка"
            
            if len(post.caption) < 100:
                return False, "Слишком короткий текст"
            if len(post.caption) > 1024:
                return False, "Превышен лимит символов"
            
            caption_hash = hashlib.md5(post.caption.encode()).hexdigest()
            if caption_hash in [p.get('hash') for p in self.approved_history[-50:]]:
                return False, "Похожий пост уже был опубликован"
            
            quality_score = self._check_text_quality(post.caption)
            if quality_score >= self.auto_approve_threshold:
                return True, "auto_approved"
            return None, "manual_review_required"
        except Exception as e:
            logger.error(f"Ошибка модерации: {e}")
            return False, f"Ошибка: {str(e)}"
    
    def _check_text_quality(self, text: str) -> float:
        try:
            score = 0.0
            if 500 <= len(text) <= 900:
                score += 0.3
            elif 300 <= len(text) < 500:
                score += 0.2
            sentences = re.split(r'[.!?]+', text)
            if 5 <= len(sentences) <= 15:
                score += 0.2
            if re.search(r'\b(бля|сука|пиздец|хуйня)\b', text.lower()):
                score += 0.1
            if re.search(r'\b(вы|вам|вас|ваши)\b', text.lower()):
                score += 0.1
            if re.search(r'\b(я|меня|мне|мой|моя|моего|моему)\b', text.lower()):
                if re.search(r'\b(дурак|глупый|смешной|неловкий|странный)\b', text.lower()):
                    score += 0.1
            if self._check_structure(text):
                score += 0.2
            return min(score, 1.0)
        except Exception as e:
            logger.error(f"Ошибка проверки качества: {e}")
            return 0.5
    
    def _check_structure(self, text: str) -> bool:
        try:
            sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
            if len(sentences) < 5:
                return False
            first_sentence = sentences[0].lower()
            hooks = ['сижу', 'стою', 'иду', 'вчера', 'сегодня', 'зашел', 'увидел', 'подумал']
            has_hook = any(hook in first_sentence for hook in hooks)
            last_sentence = sentences[-1].lower()
            conclusion_words = ['понял', 'вывод', 'итог', 'вот', 'значит', 'оказывается']
            has_conclusion = any(word in last_sentence for word in conclusion_words)
            return has_hook and has_conclusion
        except Exception as e:
            logger.error(f"Ошибка проверки структуры: {e}")
            return False
    
    async def manual_moderate(self, post_id: str, approved: bool, moderator_id: int, note: str = ""):
        try:
            if post_id in self.pending_posts:
                post = self.pending_posts[post_id]
                post.status = ModerationStatus.APPROVED if approved else ModerationStatus.REJECTED
                post.moderator_id = moderator_id
                post.moderation_note = note
                post.moderation_timestamp = time.time()
                if approved:
                    self.approved_history.append({
                        'id': post_id,
                        'hash': hashlib.md5(post.caption.encode()).hexdigest(),
                        'timestamp': time.time()
                    })
                    if len(self.approved_history) > 100:
                        self.approved_history = self.approved_history[-100:]
                else:
                    self.rejected_history.append({
                        'id': post_id,
                        'note': note,
                        'timestamp': time.time()
                    })
                return True
            return False
        except Exception as e:
            logger.error(f"Ошибка ручной модерации: {e}")
            return False

moderator = ContentModerator()

# ===== ОБРАБОТЧИК ОЧЕРЕДИ =====

async def send_post(chat_id, photo_url=None, caption=None):
    try:
        if not photo_url:
            photo_url = await get_random_photo()
        
        if not photo_url:
            logger.error("Не удалось найти фото")
            return False
        
        if not is_photo_valid(photo_url):
            logger.warning(f"Фото не прошло проверку: {photo_url[:60]}...")
            return False
        
        if not caption:
            caption = generate_caption()
            caption = clean_text(caption)
            caption = format_text_with_paragraphs(caption, 'medium')
            caption = truncate_by_sentences(caption, max_length=1023)
            validated, error = validate_caption(caption, min_length=400, max_length=1023)
            if validated:
                caption = validated
            else:
                caption = clean_text(get_fallback_caption())
                caption = format_text_with_paragraphs(caption, 'medium')
                caption = truncate_by_sentences(caption, max_length=1023)
                validated, error = validate_caption(caption, min_length=400, max_length=1023)
                if validated:
                    caption = validated
        
        if not caption:
            await bot.send_photo(chat_id=chat_id, photo=photo_url)
            logger.info(f"Фото (без подписи) отправлено в чат {chat_id}")
            return True
        
        if len(caption) > 1024:
            caption = truncate_by_sentences(caption, max_length=1023)
        
        await bot.send_photo(
            chat_id=chat_id,
            photo=photo_url,
            caption=caption
        )
        logger.info(f"Пост отправлен в чат {chat_id}")
        return True
        
    except TelegramAPIError as e:
        logger.error(f"Ошибка Telegram при отправке в {chat_id}: {e}")
        if "forbidden" in str(e).lower() or "chat not found" in str(e).lower():
            users_list = load_users()
            if str(chat_id) in [str(u) for u in users_list]:
                users_list.remove(str(chat_id))
                save_users(users_list)
                logger.info(f"Пользователь {chat_id} удалён из-за ошибки")
        return False
    except Exception as e:
        logger.error(f"Ошибка отправки в {chat_id}: {e}")
        return False

async def queue_processor():
    logger.info("Запущен обработчик очереди...")
    while True:
        try:
            task = await task_queue.pop(QUEUE_NAME)
            if task:
                logger.info(f"Получена задача из очереди: {task.get('id', 'unknown')}")
                if 'data' in task:
                    data = task['data']
                else:
                    data = task
                if data.get('needs_moderation', False):
                    await task_queue.push(MODERATION_QUEUE, data)
                    logger.info("Задача отправлена на модерацию")
                    continue
                await process_post_task(data)
            mod_task = await task_queue.pop(MODERATION_QUEUE)
            if mod_task:
                logger.info(f"Получена задача модерации: {mod_task.get('id', 'unknown')}")
                if 'data' in mod_task:
                    data = mod_task['data']
                else:
                    data = mod_task
                await process_moderation_task(data)
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка в обработчике очереди: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(5)

async def process_post_task(data: Dict[str, Any]):
    try:
        chat_id = data.get('chat_id')
        photo_url = data.get('photo_url')
        caption = data.get('caption')
        if not chat_id:
            logger.error("Нет chat_id в задаче")
            return
        await send_post(chat_id, photo_url, caption)
        logger.info(f"Пост отправлен в {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка обработки задачи: {e}")

async def process_moderation_task(data: Dict[str, Any]):
    try:
        post_data = data.get('post_data', {})
        if not post_data:
            post_data = data
        post_id = post_data.get('id', f"post_{int(time.time())}")
        post = PostContent(
            photo_url=post_data.get('photo_url', ''),
            caption=post_data.get('caption', ''),
            chat_id=post_data.get('chat_id', ''),
            user_id=post_data.get('user_id', 0),
            timestamp=time.time()
        )
        approved, reason = await moderator.moderate_content(post)
        if approved is True:
            post.status = ModerationStatus.AUTO_APPROVED
            logger.info(f"Пост {post_id} автоматически одобрен: {reason}")
            await task_queue.push(QUEUE_NAME, {
                'id': post_id,
                'chat_id': post.chat_id,
                'photo_url': post.photo_url,
                'caption': post.caption,
                'user_id': post.user_id,
                'timestamp': post.timestamp,
                'needs_moderation': False
            })
        elif approved is None:
            post.status = ModerationStatus.PENDING
            moderator.pending_posts[post_id] = post
            await notify_owner_for_moderation(post_id, post)
            logger.info(f"Пост {post_id} отправлен на ручную модерацию")
        else:
            post.status = ModerationStatus.REJECTED
            logger.info(f"Пост {post_id} отклонен: {reason}")
    except Exception as e:
        logger.error(f"Ошибка модерации: {e}")
        import traceback
        traceback.print_exc()

async def notify_owner_for_moderation(post_id: str, post: PostContent):
    if not OWNER_ID:
        return
    try:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"mod_approve_{post_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mod_reject_{post_id}")
            ]
        ])
        caption_preview = post.caption[:200] + "..." if len(post.caption) > 200 else post.caption
        await bot.send_message(
            chat_id=OWNER_ID,
            text=f"📋 Требуется модерация поста #{post_id}\n\n"
                 f"📸 Фото: {post.photo_url[:100]}...\n"
                 f"📝 Текст:\n{caption_preview}\n\n"
                 f"👤 Автор: {post.user_id}\n"
                 f"📢 Канал: {post.chat_id}",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления владельца: {e}")

async def generate_and_queue_post(chat_id: str, user_id: int = 0, skip_moderation: bool = False):
    try:
        photo_url = await get_random_photo()
        if not photo_url:
            logger.error("Не удалось найти фото")
            return False
        caption = generate_caption()
        if not caption:
            logger.error("Не удалось сгенерировать текст")
            return False
        post_id = f"post_{int(time.time())}_{hashlib.md5(caption.encode()).hexdigest()[:8]}"
        post_data = {
            'id': post_id,
            'chat_id': chat_id,
            'photo_url': photo_url,
            'caption': caption,
            'user_id': user_id,
            'timestamp': time.time(),
            'needs_moderation': not skip_moderation
        }
        if skip_moderation:
            await task_queue.push(QUEUE_NAME, post_data)
            logger.info(f"Пост {post_id} добавлен в очередь отправки")
            return True
        await task_queue.push(MODERATION_QUEUE, {
            'id': post_id,
            'post_data': post_data
        })
        logger.info(f"Пост {post_id} добавлен в очередь модерации")
        return True
    except Exception as e:
        logger.error(f"Ошибка генерации поста: {e}")
        return False

async def auto_send_to_all_users():
    try:
        users_list = load_users()
        if not users_list:
            logger.warning("Нет пользователей для отправки")
            return
        
        logger.info(f"Авто-рассылка для {len(users_list)} пользователей...")
        
        photo_url = await get_random_photo()
        if not photo_url:
            logger.error("Не удалось найти фото")
            return
        
        caption = generate_caption()
        caption = clean_text(caption)
        caption = format_text_with_paragraphs(caption, 'medium')
        caption = truncate_by_sentences(caption, max_length=1023)
        validated, error = validate_caption(caption, min_length=400, max_length=1023)
        if validated:
            caption = validated
        else:
            caption = clean_text(get_fallback_caption())
            caption = format_text_with_paragraphs(caption, 'medium')
            caption = truncate_by_sentences(caption, max_length=1023)
            validated, error = validate_caption(caption, min_length=400, max_length=1023)
            if validated:
                caption = validated
        
        if not caption or not photo_url:
            logger.error("Не удалось сгенерировать пост")
            return
        
        add_to_last_posts(caption)
        
        logger.info(f"✅ Сгенерирован пост для авто-рассылки ({len(caption)} символов)")
        
        sent_count = 0
        failed_count = 0
        
        for chat_id in users_list:
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_url,
                    caption=caption
                )
                sent_count += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Ошибка отправки в {chat_id}: {e}")
                failed_count += 1
                if "forbidden" in str(e).lower() or "chat not found" in str(e).lower():
                    if str(chat_id) in [str(u) for u in users_list]:
                        users_list.remove(str(chat_id))
                        save_users(users_list)
                        logger.info(f"Пользователь {chat_id} удалён из-за ошибки")
        
        channel_id = CHANNEL_ID
        if not channel_id or not channel_id.strip():
            channel_id = await get_channel_id()
        if channel_id:
            try:
                await bot.send_photo(
                    chat_id=channel_id,
                    photo=photo_url,
                    caption=caption
                )
                logger.info(f"✅ Пост отправлен в канал {channel_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки в канал {channel_id}: {e}")
        
        logger.info(f"📊 Авто-рассылка: отправлено {sent_count}, ошибок {failed_count}")
        
    except Exception as e:
        logger.error(f"Ошибка в auto_send_to_all_users: {e}")

async def get_channel_id() -> Optional[str]:
    if CHANNEL_ID and CHANNEL_ID.strip():
        return CHANNEL_ID.strip()
    try:
        me = await bot.get_me()
        logger.info(f"Бот: @{me.username}")
        try:
            updates = await asyncio.wait_for(
                bot.get_updates(offset=-1, limit=10),
                timeout=10
            )
            for update in updates:
                if update.channel_post:
                    chat_id = update.channel_post.chat.id
                    try:
                        chat_member = await bot.get_chat_member(chat_id, bot.id)
                        if chat_member.status in ["administrator", "creator"]:
                            logger.info(f"Найден канал: {chat_id}")
                            return str(chat_id)
                    except:
                        pass
        except asyncio.TimeoutError:
            logger.warning("Таймаут получения обновлений")
        except Exception as e:
            logger.error(f"Ошибка получения обновлений: {e}")
    except Exception as e:
        logger.error(f"Ошибка поиска канала: {e}")
    return None

# ===== КОМАНДЫ =====

async def check_user_can_use_command(message: Message) -> bool:
    try:
        chat_type = message.chat.type
        if chat_type == "private":
            return True
        if chat_type in ["group", "supergroup"]:
            return await is_user_admin(message.chat.id, message.from_user.id)
        return False
    except Exception as e:
        logger.error(f"Ошибка проверки прав: {e}")
        return False

async def is_user_admin(chat_id: int, user_id: int) -> bool:
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ["administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка проверки админа: {e}")
        return False

# ===== КОМАНДА /PRICE =====

@dp.message(Command("price"))
async def set_price(message: Message):
    try:
        if message.from_user.id != OWNER_ID:
            await message.answer("⛔ Доступ запрещён. Только для владельца.")
            return
        args = message.text.replace("/price", "").strip()
        if not args:
            current_price = load_broadcast_price()
            await message.answer(
                f"💰 Текущая цена рассылки: {current_price} ⭐ звёзд\n\n"
                f"Чтобы изменить, напишите:\n"
                f"/price 10\n\n"
                f"Цена должна быть от 1 до 1000 звёзд."
            )
            return
        try:
            price = int(args)
            if price < 1 or price > 1000:
                await message.answer("❌ Цена должна быть от 1 до 1000 звёзд.")
                return
            save_broadcast_price(price)
            global broadcast_price
            broadcast_price = price
            await message.answer(f"✅ Цена рассылки установлена: {price} ⭐ звёзд")
            logger.info(f"Цена рассылки изменена на {price} звёзд")
        except ValueError:
            await message.answer("❌ Введите число. Пример: /price 10")
    except Exception as e:
        logger.error(f"Ошибка в команде price: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")


# ===== КОМАНДА /BALANCE =====

@dp.message(Command("balance"))
async def check_stars_balance(message: Message):
    try:
        # Команда доступна только владельцу
        if message.from_user.id != OWNER_ID:
            await message.answer("⛔ Доступ запрещён. Только для владельца.")
            return
        
        # Только в личных сообщениях
        if message.chat.type != "private":
            await message.answer("ℹ️ Эта команда работает только в личных сообщениях с ботом.")
            return
        
        await message.answer("⏳ Проверяю баланс звёзд...")
        
        try:
            # Используем метод для получения баланса звёзд
            balance = await bot.get_business_account_star_balance(chat_id=STARS_CHANNEL_ID)
            await message.answer(
                f"⭐ Баланс звёзд в канале {STARS_CHANNEL_ID}:\n\n"
                f"💰 {balance} ⭐ звёзд\n\n"
                f"💡 1 звезда = 1 цент (≈ 1 рубль)\n"
                f"📊 Звёзды поступают за платные рассылки (/broadcast)"
            )
            logger.info(f"Владелец проверил баланс: {balance} звёзд")
        except Exception as e:
            logger.error(f"Ошибка получения баланса: {e}")
            await message.answer(
                f"❌ Не удалось получить баланс звёзд.\n\n"
                f"Возможные причины:\n"
                f"• Бот не является администратором канала {STARS_CHANNEL_ID}\n"
                f"• Канал {STARS_CHANNEL_ID} не существует или недоступен\n"
                f"• У бота нет прав на просмотр баланса\n\n"
                f"Проверьте права бота в канале командой /check_channel"
            )
    except Exception as e:
        logger.error(f"Ошибка в команде balance: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")


# ===== КОМАНДА /BROADCAST (ОБНОВЛЁННАЯ) =====

# Хранилище для данных рассылки
broadcast_data = {}
pending_broadcasts = {}

@dp.message(Command("broadcast"))
async def broadcast_command(message: Message):
    try:
        if message.chat.type != "private":
            await message.answer("ℹ️ Эта команда работает только в личных сообщениях с ботом.")
            return
        
        user_id = message.from_user.id
        chat_id = message.chat.id
        
        # Проверяем, есть ли вложение
        has_media = False
        media_type = None
        media_file_id = None
        text = ""
        
        # Проверяем текст
        if message.text:
            text = message.text.replace("/broadcast", "").strip()
        
        # Проверяем вложения
        if message.photo:
            has_media = True
            media_type = "photo"
            media_file_id = message.photo[-1].file_id  # Берём самое большое фото
            text = message.caption or ""
        elif message.video:
            has_media = True
            media_type = "video"
            media_file_id = message.video.file_id
            text = message.caption or ""
        elif message.document:
            has_media = True
            media_type = "document"
            media_file_id = message.document.file_id
            text = message.caption or ""
        elif message.animation:  # GIF
            has_media = True
            media_type = "animation"
            media_file_id = message.animation.file_id
            text = message.caption or ""
        elif message.audio:
            has_media = True
            media_type = "audio"
            media_file_id = message.audio.file_id
            text = message.caption or ""
        elif message.voice:
            has_media = True
            media_type = "voice"
            media_file_id = message.voice.file_id
            text = message.caption or ""
        elif message.video_note:  # Кружок
            has_media = True
            media_type = "video_note"
            media_file_id = message.video_note.file_id
            text = message.caption or ""
        
        # Если нет ни текста, ни вложения
        if not text and not has_media:
            current_price = load_broadcast_price()
            await message.answer(
                f"📢 Чтобы отправить сообщение всем подписчикам, отправьте:\n"
                f"• Текст: /broadcast Ваше сообщение\n"
                f"• Фото: подпись к фото или без\n"
                f"• Видео: подпись к видео или без\n"
                f"• Документ: подпись к документу или без\n"
                f"• GIF: подпись к GIF или без\n\n"
                f"⭐ Стоимость: {current_price} звёзд\n"
                f"💰 Средства поступят на канал\n\n"
                f"После оплаты сообщение будет отправлено на модерацию."
            )
            return
        
        # Убираем команду из текста, если она есть
        if text and text.startswith("/broadcast"):
            text = text.replace("/broadcast", "").strip()
        
        current_price = load_broadcast_price()
        
        # Создаём описание для счёта
        description = "Отправка сообщения всем подписчикам бота"
        if text:
            description += f"\n\nТекст: {text[:100]}{'...' if len(text) > 100 else ''}"
        if has_media:
            media_names = {
                "photo": "📸 Фото",
                "video": "🎬 Видео",
                "document": "📄 Документ",
                "animation": "🎥 GIF",
                "audio": "🎵 Аудио",
                "voice": "🎤 Голосовое",
                "video_note": "🔄 Видео-кружок"
            }
            description += f"\n{media_names.get(media_type, '📎 Медиафайл')}"
        
        prices = [LabeledPrice(label="⭐ Рассылка", amount=current_price)]
        
        await bot.send_invoice(
            chat_id=chat_id,
            title="📢 Рассылка сообщения",
            description=description[:255],  # Telegram ограничение
            payload=f"broadcast_{user_id}_{int(time.time())}",
            provider_token="",
            currency="XTR",
            prices=prices,
            start_parameter="broadcast",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"⭐ Оплатить {current_price} звёзд", pay=True)]
            ])
        )
        
        # Сохраняем данные для отправки после оплаты
        broadcast_data[user_id] = {
            'text': text,
            'has_media': has_media,
            'media_type': media_type,
            'media_file_id': media_file_id,
            'timestamp': time.time(),
            'chat_id': chat_id,
            'user_id': user_id
        }
        
    except Exception as e:
        logger.error(f"Ошибка в команде broadcast: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")


# ===== ОБРАБОТЧИК ОПЛАТЫ =====

@dp.message(lambda message: message.successful_payment is not None)
async def process_successful_payment(message: Message):
    try:
        user_id = message.from_user.id
        payload = message.successful_payment.invoice_payload
        if not payload.startswith("broadcast_"):
            return
        
        broadcast_info = broadcast_data.get(user_id)
        if not broadcast_info:
            await message.answer("❌ Данные о сообщении не найдены. Попробуйте снова.")
            return
        
        text = broadcast_info.get('text', '')
        has_media = broadcast_info.get('has_media', False)
        media_type = broadcast_info.get('media_type')
        media_file_id = broadcast_info.get('media_file_id')
        
        broadcast_id = f"broadcast_{int(time.time())}_{hashlib.md5(str(broadcast_info).encode()).hexdigest()[:8]}"
        del broadcast_data[user_id]
        
        # Сохраняем данные о рассылке
        pending_broadcasts[broadcast_id] = {
            'text': text,
            'has_media': has_media,
            'media_type': media_type,
            'media_file_id': media_file_id,
            'user_id': user_id,
            'timestamp': time.time(),
            'chat_id': message.chat.id
        }
        
        # Отправляем на модерацию
        await send_broadcast_for_moderation(broadcast_id, broadcast_info)
        await message.answer(
            f"✅ Оплата получена! Сообщение отправлено на модерацию.\n"
            f"📝 Текст: {text[:100]}{'...' if len(text) > 100 else '' if text else 'Без текста'}\n"
            f"{'📎 С медиафайлом' if has_media else ''}\n\n"
            f"⏳ Ожидайте подтверждения от администратора."
        )
    except Exception as e:
        logger.error(f"Ошибка в successful_payment: {e}")
        await message.answer(f"❌ Ошибка при обработке платежа: {str(e)}")


# ===== ОТПРАВКА НА МОДЕРАЦИЮ =====

async def send_broadcast_for_moderation(broadcast_id: str, broadcast_info: dict):
    if not OWNER_ID:
        return
    try:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"broad_approve_{broadcast_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"broad_reject_{broadcast_id}")
            ]
        ])
        
        text = broadcast_info.get('text', '')
        has_media = broadcast_info.get('has_media', False)
        media_type = broadcast_info.get('media_type')
        media_file_id = broadcast_info.get('media_file_id')
        user_id = broadcast_info.get('user_id')
        
        # Создаём превью сообщения
        preview_text = f"📋 Новая рассылка на модерацию #{broadcast_id}\n\n"
        preview_text += f"👤 Заказчик ID: {user_id}\n"
        preview_text += f"💰 Оплачено: {load_broadcast_price()} ⭐\n"
        preview_text += f"📤 Средства поступят на канал {STARS_CHANNEL_ID}\n"
        
        if text:
            preview_text += f"\n📝 Текст:\n{text[:300]}{'...' if len(text) > 300 else ''}\n"
        else:
            preview_text += f"\n📝 Текст: (без текста)\n"
        
        if has_media:
            media_names = {
                "photo": "📸 Фото",
                "video": "🎬 Видео",
                "document": "📄 Документ",
                "animation": "🎥 GIF",
                "audio": "🎵 Аудио",
                "voice": "🎤 Голосовое",
                "video_note": "🔄 Видео-кружок"
            }
            preview_text += f"\n📎 {media_names.get(media_type, 'Медиафайл')} (будет отправлено)\n"
        
        preview_text += f"\n⏳ После подтверждения будет отправлено всем подписчикам."
        
        # Отправляем превью владельцу
        if has_media and media_file_id:
            # Отправляем медиа с превью
            if media_type == "photo":
                await bot.send_photo(
                    chat_id=OWNER_ID,
                    photo=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard
                )
            elif media_type == "video":
                await bot.send_video(
                    chat_id=OWNER_ID,
                    video=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard
                )
            elif media_type == "document":
                await bot.send_document(
                    chat_id=OWNER_ID,
                    document=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard
                )
            elif media_type == "animation":
                await bot.send_animation(
                    chat_id=OWNER_ID,
                    animation=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard
                )
            elif media_type == "audio":
                await bot.send_audio(
                    chat_id=OWNER_ID,
                    audio=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard
                )
            elif media_type == "voice":
                await bot.send_voice(
                    chat_id=OWNER_ID,
                    voice=media_file_id,
                    caption=preview_text,
                    reply_markup=keyboard
                )
            elif media_type == "video_note":
                await bot.send_video_note(
                    chat_id=OWNER_ID,
                    video_note=media_file_id,
                    reply_markup=keyboard
                )
                # Отправляем текст отдельно для видео-кружка
                await bot.send_message(
                    chat_id=OWNER_ID,
                    text=preview_text,
                    reply_markup=keyboard
                )
        else:
            # Только текст
            await bot.send_message(
                chat_id=OWNER_ID,
                text=preview_text,
                reply_markup=keyboard
            )
        
        logger.info(f"Рассылка {broadcast_id} отправлена на модерацию владельцу")
    except Exception as e:
        logger.error(f"Ошибка отправки на модерацию: {e}")


# ===== ОБРАБОТЧИК МОДЕРАЦИИ РАССЫЛКИ =====

@dp.callback_query(lambda c: c.data and c.data.startswith('broad_'))
async def handle_broadcast_moderation(callback: CallbackQuery):
    try:
        if callback.from_user.id != OWNER_ID:
            await callback.answer("⛔ Доступ запрещен", show_alert=True)
            return
        
        parts = callback.data.split('_')
        action = parts[1]
        broadcast_id = '_'.join(parts[2:])
        approved = action == 'approve'
        
        if broadcast_id not in pending_broadcasts:
            await callback.answer("❌ Сообщение не найдено", show_alert=True)
            return
        
        broadcast_info = pending_broadcasts[broadcast_id]
        
        if approved:
            await callback.answer("✅ Сообщение одобрено. Отправляется всем подписчикам...", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n✅ ОДОБРЕНО (отправляется всем подписчикам)",
                reply_markup=None
            )
            
            text = broadcast_info.get('text', '')
            has_media = broadcast_info.get('has_media', False)
            media_type = broadcast_info.get('media_type')
            media_file_id = broadcast_info.get('media_file_id')
            users_list = load_users()
            
            sent_count = 0
            failed_count = 0
            
            # Отправляем всем пользователям
            for chat_id in users_list:
                try:
                    if has_media and media_file_id:
                        # Отправляем с медиа
                        if media_type == "photo":
                            await bot.send_photo(
                                chat_id=chat_id,
                                photo=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "video":
                            await bot.send_video(
                                chat_id=chat_id,
                                video=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "document":
                            await bot.send_document(
                                chat_id=chat_id,
                                document=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "animation":
                            await bot.send_animation(
                                chat_id=chat_id,
                                animation=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "audio":
                            await bot.send_audio(
                                chat_id=chat_id,
                                audio=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "voice":
                            await bot.send_voice(
                                chat_id=chat_id,
                                voice=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "video_note":
                            await bot.send_video_note(
                                chat_id=chat_id,
                                video_note=media_file_id
                            )
                            if text:
                                await bot.send_message(chat_id=chat_id, text=text)
                    else:
                        # Только текст
                        if text:
                            await bot.send_message(chat_id=chat_id, text=text)
                    
                    sent_count += 1
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.error(f"Ошибка отправки в {chat_id}: {e}")
                    failed_count += 1
                    if "forbidden" in str(e).lower() or "chat not found" in str(e).lower():
                        if str(chat_id) in [str(u) for u in users_list]:
                            users_list.remove(str(chat_id))
                            save_users(users_list)
                            logger.info(f"Пользователь {chat_id} удалён из-за ошибки")
            
            # Отправляем в канал (если указан)
            try:
                channel_id = CHANNEL_ID
                if not channel_id or not channel_id.strip():
                    channel_id = await get_channel_id()
                if channel_id:
                    if has_media and media_file_id:
                        if media_type == "photo":
                            await bot.send_photo(
                                chat_id=channel_id,
                                photo=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "video":
                            await bot.send_video(
                                chat_id=channel_id,
                                video=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "document":
                            await bot.send_document(
                                chat_id=channel_id,
                                document=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "animation":
                            await bot.send_animation(
                                chat_id=channel_id,
                                animation=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "audio":
                            await bot.send_audio(
                                chat_id=channel_id,
                                audio=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "voice":
                            await bot.send_voice(
                                chat_id=channel_id,
                                voice=media_file_id,
                                caption=text if text else None
                            )
                        elif media_type == "video_note":
                            await bot.send_video_note(
                                chat_id=channel_id,
                                video_note=media_file_id
                            )
                            if text:
                                await bot.send_message(chat_id=channel_id, text=text)
                    else:
                        if text:
                            await bot.send_message(chat_id=channel_id, text=text)
                    logger.info(f"✅ Отправлено в канал {channel_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки в канал: {e}")
            
            # Удаляем из ожидающих
            del pending_broadcasts[broadcast_id]
            
            # Отчёт владельцу
            try:
                await bot.send_message(
                    chat_id=OWNER_ID,
                    text=f"📊 Рассылка #{broadcast_id} завершена!\n"
                         f"✅ Отправлено подписчикам: {sent_count}\n"
                         f"❌ Ошибок: {failed_count}\n"
                         f"📝 Текст: {text[:200]}{'...' if len(text) > 200 else '' if text else '(без текста)'}\n"
                         f"{'📎 С медиафайлом' if has_media else ''}"
                )
            except Exception as e:
                logger.error(f"Ошибка отправки отчета: {e}")
            
            # Уведомление заказчика
            try:
                user_id = broadcast_info.get('user_id')
                if user_id:
                    await bot.send_message(
                        chat_id=user_id,
                        text=f"✅ Ваше сообщение опубликовано!\n"
                             f"📨 Отправлено: {sent_count} подписчикам\n"
                             f"📝 Текст: {text[:100]}{'...' if len(text) > 100 else '' if text else '(без текста)'}\n"
                             f"{'📎 С медиафайлом' if has_media else ''}"
                    )
            except Exception as e:
                logger.error(f"Ошибка уведомления заказчика: {e}")
                
        else:
            await callback.answer("❌ Сообщение отклонено", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n❌ ОТКЛОНЕНО",
                reply_markup=None
            )
            try:
                user_id = broadcast_info.get('user_id')
                if user_id:
                    await bot.send_message(
                        chat_id=user_id,
                        text="❌ Ваше сообщение отклонено модератором."
                    )
            except Exception as e:
                logger.error(f"Ошибка уведомления заказчика: {e}")
            if broadcast_id in pending_broadcasts:
                del pending_broadcasts[broadcast_id]
    except Exception as e:
        logger.error(f"Ошибка в broadcast модерации: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


# ===== КОМАНДА /CHECK_CHANNEL =====

@dp.message(Command("check_channel"))
async def check_channel(message: Message):
    try:
        if message.from_user.id != OWNER_ID:
            await message.answer("⛔ Доступ запрещён")
            return
        try:
            chat_member = await bot.get_chat_member(STARS_CHANNEL_ID, bot.id)
            status_text = f"📊 Статус бота в канале {STARS_CHANNEL_ID}:\n"
            status_text += f"• Статус: {chat_member.status}\n"
            status_text += f"• Может отправлять: {chat_member.can_send_messages}\n"
            status_text += f"• Может управлять: {chat_member.can_manage_chat}\n"
            status_text += f"• Может публиковать: {chat_member.can_post_messages}\n"
            status_text += f"• Может управлять видеочатами: {chat_member.can_manage_video_chats}\n"
            await message.answer(status_text)
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}\n\nУбедитесь, что бот добавлен в канал {STARS_CHANNEL_ID} как администратор.")
    except Exception as e:
        logger.error(f"Ошибка проверки канала: {e}")
        await message.answer("❌ Произошла ошибка")

# ===== КОМАНДА /PHOTO =====

@dp.message(Command("photo"))
async def photo(msg: Message):
    try:
        chat_id = msg.chat.id
        user_id = msg.from_user.id
        chat_type = msg.chat.type
        
        if chat_type == "channel":
            await msg.answer("ℹ️ В канале отправка по команде не требуется.")
            return
        
        if chat_type == "private":
            if user_id not in ALLOWED_PHOTO_USERS:
                await msg.answer("⛔ Команда /photo в личных сообщениях доступна только владельцу бота.")
                return
        
        if chat_type in ["group", "supergroup"]:
            if not await is_user_admin(chat_id, user_id):
                await msg.reply("⛔ Только администраторы могут запрашивать фото.")
                return
        
        if str(chat_id) not in [str(u) for u in users]:
            await msg.answer("⚠️ Бот не активирован. Напишите /start")
            return
        
        await generate_and_queue_post(str(chat_id), user_id, skip_moderation=True)
        await msg.answer("✅ Пост добавлен в очередь отправки")
        
    except Exception as e:
        logger.error(f"Ошибка в команде photo: {e}")
        await msg.answer("❌ Произошла ошибка. Попробуйте позже.")

# ===== КОМАНДА /POST =====

@dp.message(Command("post"))
async def post_to_all(msg: Message):
    try:
        if msg.from_user.id != OWNER_ID:
            await msg.answer("⛔ Доступ запрещён. Только для владельца.")
            return
        
        if msg.chat.type != "private":
            await msg.answer("ℹ️ Эта команда работает только в личных сообщениях с ботом.")
            return
        
        await msg.answer("⏳ Генерирую пост для всех подписчиков...")
        
        photo_url = await get_random_photo()
        if not photo_url:
            await msg.answer("❌ Не удалось найти фото")
            return
        
        caption = generate_caption()
        caption = clean_text(caption)
        caption = format_text_with_paragraphs(caption, 'medium')
        caption = truncate_by_sentences(caption, max_length=1023)
        validated, error = validate_caption(caption, min_length=400, max_length=1023)
        if validated:
            caption = validated
        else:
            caption = clean_text(get_fallback_caption())
            caption = format_text_with_paragraphs(caption, 'medium')
            caption = truncate_by_sentences(caption, max_length=1023)
            validated, error = validate_caption(caption, min_length=400, max_length=1023)
            if validated:
                caption = validated
        
        if not caption or not photo_url:
            await msg.answer("❌ Не удалось сгенерировать пост")
            return
        
        add_to_last_posts(caption)
        
        logger.info(f"✅ Сгенерирован пост для рассылки ({len(caption)} символов)")
        
        users_list = load_users()
        if not users_list:
            await msg.answer("⚠️ Нет подписчиков для рассылки")
            return
        
        sent_count = 0
        failed_count = 0
        
        status_msg = await msg.answer(f"📨 Начинаю рассылку {len(users_list)} пользователям...")
        
        for chat_id in users_list:
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_url,
                    caption=caption
                )
                sent_count += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Ошибка отправки в {chat_id}: {e}")
                failed_count += 1
                if "forbidden" in str(e).lower() or "chat not found" in str(e).lower():
                    if str(chat_id) in [str(u) for u in users_list]:
                        users_list.remove(str(chat_id))
                        save_users(users_list)
                        logger.info(f"Пользователь {chat_id} удалён из-за ошибки")
            
            if (sent_count + failed_count) % 10 == 0:
                try:
                    await status_msg.edit_text(
                        f"📨 Рассылка: {sent_count + failed_count}/{len(users_list)}\n"
                        f"✅ Отправлено: {sent_count}\n"
                        f"❌ Ошибок: {failed_count}"
                    )
                except:
                    pass
        
        channel_id = CHANNEL_ID
        if not channel_id or not channel_id.strip():
            channel_id = await get_channel_id()
        
        channel_status = ""
        if channel_id:
            try:
                await bot.send_photo(
                    chat_id=channel_id,
                    photo=photo_url,
                    caption=caption
                )
                channel_status = f"\n📢 Канал: ✅ отправлено"
                logger.info(f"✅ Пост отправлен в канал {channel_id}")
            except Exception as e:
                channel_status = f"\n📢 Канал: ❌ ошибка - {str(e)[:50]}"
                logger.error(f"Ошибка отправки в канал {channel_id}: {e}")
        else:
            channel_status = "\n📢 Канал: ⚠️ не найден"
        
        await status_msg.edit_text(
            f"✅ Рассылка завершена!\n"
            f"📨 Всего: {len(users_list)}\n"
            f"✅ Отправлено: {sent_count}\n"
            f"❌ Ошибок: {failed_count}\n"
            f"{channel_status}\n"
            f"📝 Текст: {caption[:100]}{'...' if len(caption) > 100 else ''}"
        )
        
    except Exception as e:
        logger.error(f"Ошибка в команде post: {e}")
        await msg.answer(f"❌ Произошла ошибка: {str(e)[:100]}")

# ===== КОМАНДА /POSTALL =====

@dp.message(Command("postall"))
async def post_all_alias(msg: Message):
    await post_to_all(msg)

# ===== КОМАНДА /START =====

@dp.message(Command("start"))
async def start(msg: Message):
    try:
        chat_id = msg.chat.id
        user_id = msg.from_user.id
        chat_type = msg.chat.type
        
        if chat_type == "channel":
            await msg.answer("ℹ️ Я работаю в канале автоматически, команды не требуются.")
            return
        
        if not await check_user_can_use_command(msg):
            await msg.reply("⛔ Эта команда только для администраторов группы.")
            return
        
        if chat_type in ["group", "supergroup"]:
            try:
                chat_member = await bot.get_chat_member(chat_id, bot.id)
                is_admin = chat_member.status in ["administrator", "creator"]
            except:
                is_admin = False
            
            if not is_admin:
                await msg.answer("❌ Я должен быть администратором группы!")
                return
        
        # Подписываем пользователя
        chat_id_str = str(chat_id)
        if chat_id_str not in [str(u) for u in users]:
            users.append(chat_id_str)
            save_users(users)
            logger.info(f"✅ Добавлен пользователь: {chat_id}")
        else:
            logger.info(f"ℹ️ Пользователь {chat_id} уже подписан")
        
        # Информация о статусе
        channel_status = f"\n📢 Канал: {'✅ подключён' if CHANNEL_ID and CHANNEL_ID.strip() else '🔄 авто-поиск'}"
        current_schedule = load_schedule()
        times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
        current_price = load_broadcast_price()
        
        is_owner = (user_id == OWNER_ID)
        owner_commands = ""
        if is_owner:
            owner_commands = f"\n\n👑 Команды владельца:\n📢 /post - отправить пост всем подписчикам\n📸 /photo - получить пост только себе\n⭐ /balance - проверить баланс звёзд"
        
        await msg.answer(
            f"✅ Бот активирован!\n"
            f"📸 Уникальные посты про азиатских девушек\n"
            f"⏰ Расписание: {times}\n"
            f"{channel_status}\n"
            f"🔄 /photo - получить пост прямо сейчас\n"
            f"🛑 /stop - отписаться{owner_commands}"
        )
        
    except Exception as e:
        logger.error(f"Ошибка в команде start: {e}")
        await msg.answer("❌ Произошла ошибка. Попробуйте позже.")

# ===== КОМАНДА /STOP =====

@dp.message(Command("stop"))
async def stop(msg: Message):
    try:
        chat_id = msg.chat.id
        chat_type = msg.chat.type
        if chat_type == "channel":
            await msg.answer("ℹ️ В канале отписка не требуется.")
            return
        if not await check_user_can_use_command(msg):
            await msg.reply("⛔ Только администраторы могут отключить бота.")
            return
        chat_id_str = str(chat_id)
        if chat_id_str in [str(u) for u in users]:
            users.remove(chat_id_str)
            save_users(users)
            await msg.answer("🛑 Вы отписаны от рассылки")
            logger.info(f"Удалён пользователь: {chat_id}")
        else:
            await msg.answer("ℹ️ Вы и так не подписаны")
    except Exception as e:
        logger.error(f"Ошибка в команде stop: {e}")
        await msg.answer("❌ Произошла ошибка. Попробуйте позже.")

# ===== КОМАНДА /STATUS =====

@dp.message(Command("status"))
async def status(msg: Message):
    try:
        chat_id = msg.chat.id
        chat_type = msg.chat.type
        if chat_type == "channel":
            channel_info = f"📊 Статус канала:\n"
            channel_info += f"• ID: {chat_id}\n"
            channel_info += f"• Бот: {'✅ админ' if await is_user_admin(chat_id, bot.id) else '❌ не админ'}"
            await msg.answer(channel_info)
            return
        if not await check_user_can_use_command(msg):
            await msg.reply("⛔ Только администраторы могут смотреть статус.")
            return
        is_subscribed = str(chat_id) in [str(u) for u in users]
        channel_id = CHANNEL_ID or await get_channel_id()
        current_schedule = load_schedule()
        times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
        current_price = load_broadcast_price()
        status_text = (
            f"📊 Статус бота:\n"
            f"• Подписка: {'✅ Активна' if is_subscribed else '❌ Неактивна'}\n"
            f"• Всего подписчиков: {len(users)}\n"
            f"• Фото в истории: {len(history)}\n"
            f"• Расписание: {times}\n"
            f"• Канал: {'✅ ' + channel_id if channel_id else '❌ не найден'}\n"
            f"• Цена рассылки: {current_price} ⭐\n"
            f"• Канал для звёзд: {STARS_CHANNEL_ID}"
        )
        await msg.answer(status_text)
    except Exception as e:
        logger.error(f"Ошибка в команде status: {e}")
        await msg.answer("❌ Произошла ошибка. Попробуйте позже.")

# ===== КОМАНДА /SCHEDULE =====

@dp.message(Command("schedule"))
async def schedule(msg: Message):
    try:
        if not await check_user_can_use_command(msg):
            await msg.reply("⛔ Только администраторы могут изменять расписание.")
            return
        if msg.from_user.id != OWNER_ID:
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
    except Exception as e:
        logger.error(f"Ошибка в команде schedule: {e}")
        await msg.answer("❌ Произошла ошибка. Попробуйте позже.")

# ===== КОМАНДА /MODERATE =====

@dp.message(Command("moderate"))
async def moderate_pending(msg: Message):
    try:
        if msg.from_user.id != OWNER_ID:
            await msg.answer("⛔ Доступ запрещён")
            return
        if not moderator.pending_posts:
            await msg.answer("📭 Нет постов на модерации")
            return
        count = len(moderator.pending_posts)
        await msg.answer(f"📋 На модерации: {count} постов\n"
                        f"Используйте кнопки в уведомлениях для модерации")
    except Exception as e:
        logger.error(f"Ошибка в команде moderate: {e}")
        await msg.answer("❌ Произошла ошибка. Попробуйте позже.")

# ===== КОМАНДА /MODERATION_STATS =====

@dp.message(Command("moderation_stats"))
async def moderation_stats(msg: Message):
    try:
        if msg.from_user.id != OWNER_ID:
            await msg.answer("⛔ Доступ запрещён")
            return
        stats = f"📊 Статистика модерации:\n"
        stats += f"• На модерации: {len(moderator.pending_posts)}\n"
        stats += f"• Одобрено: {len(moderator.approved_history)}\n"
        stats += f"• Отклонено: {len(moderator.rejected_history)}\n"
        stats += f"• Ожидают broadcast: {len(pending_broadcasts)}\n"
        queue_len = await task_queue.get_queue_length(QUEUE_NAME)
        mod_queue_len = await task_queue.get_queue_length(MODERATION_QUEUE)
        stats += f"\n📊 Очереди:\n"
        stats += f"• Отправка: {queue_len}\n"
        stats += f"• Модерация: {mod_queue_len}"
        await msg.answer(stats)
    except Exception as e:
        logger.error(f"Ошибка в команде moderation_stats: {e}")
        await msg.answer("❌ Произошла ошибка. Попробуйте позже.")

# ===== ОБРАБОТЧИК CALLBACK'ОВ МОДЕРАЦИИ =====

@dp.callback_query(lambda c: c.data and c.data.startswith('mod_'))
async def handle_moderation_callback(callback: CallbackQuery):
    try:
        if callback.from_user.id != OWNER_ID:
            await callback.answer("⛔ Доступ запрещен", show_alert=True)
            return
        parts = callback.data.split('_')
        action = parts[1]
        post_id = '_'.join(parts[2:])
        approved = action == 'approve'
        if post_id not in moderator.pending_posts:
            await callback.answer("❌ Пост не найден", show_alert=True)
            return
        post = moderator.pending_posts[post_id]
        if approved:
            await moderator.manual_moderate(post_id, True, callback.from_user.id, "Одобрено владельцем")
            await task_queue.push(QUEUE_NAME, {
                'id': post_id,
                'chat_id': post.chat_id,
                'photo_url': post.photo_url,
                'caption': post.caption,
                'user_id': 0,
                'timestamp': time.time(),
                'needs_moderation': False
            })
            await callback.answer("✅ Пост одобрен и отправлен в очередь", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n✅ ОДОБРЕН",
                reply_markup=None
            )
        else:
            await moderator.manual_moderate(post_id, False, callback.from_user.id, "Отклонено владельцем")
            await callback.answer("❌ Пост отклонен", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n❌ ОТКЛОНЕН",
                reply_markup=None
            )
    except Exception as e:
        logger.error(f"Ошибка в callback модерации: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

# ===== ПЕРЕСЫЛКА ВСЕХ СООБЩЕНИЙ ВЛАДЕЛЬЦУ =====

owner_message_queue = []
owner_message_lock = asyncio.Lock()
last_owner_message_time = 0

async def send_owner_message_delayed():
    global last_owner_message_time
    while True:
        try:
            async with owner_message_lock:
                if not owner_message_queue:
                    await asyncio.sleep(1)
                    continue
                current_time = time.time()
                time_since_last = current_time - last_owner_message_time
                if time_since_last < 60:
                    wait_time = 60 - time_since_last
                    await asyncio.sleep(wait_time)
                    continue
                msg_data = owner_message_queue.pop(0)
                last_owner_message_time = time.time()
            try:
                await bot.send_message(
                    chat_id=OWNER_ID,
                    text=msg_data['text'],
                    **msg_data.get('kwargs', {})
                )
                logger.info(f"Сообщение владельцу отправлено (очередь: {len(owner_message_queue)})")
            except Exception as e:
                logger.error(f"Ошибка отправки владельцу: {e}")
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка в обработчике очереди владельца: {e}")
            await asyncio.sleep(5)

@dp.message()
async def forward_all_messages_to_owner(message: Message):
    try:
        if message.from_user.id == OWNER_ID:
            return
        if message.text and message.text.startswith('/'):
            return
        if not message.text and not message.photo and not message.video and not message.document and not message.voice and not message.sticker:
            return
        user = message.from_user
        if user.username:
            user_link = f"@{user.username}"
        else:
            user_link = f"[{user.first_name}](tg://user?id={user.id})"
        chat_info = f"📨 Новое сообщение от пользователя\n\n"
        chat_info += f"👤 Имя: {user.first_name}"
        if user.last_name:
            chat_info += f" {user.last_name}"
        chat_info += f"\n"
        chat_info += f"🆔 ID: {user.id}\n"
        chat_info += f"🔗 Ссылка: {user_link}\n"
        if message.chat.type != "private":
            chat_info += f"📢 Чат: {message.chat.title} (ID: {message.chat.id})\n"
        chat_info += f"\n📝 Сообщение:\n"
        if message.text:
            text_preview = message.text[:500] + "..." if len(message.text) > 500 else message.text
            full_text = chat_info + text_preview
            async with owner_message_lock:
                owner_message_queue.append({
                    'text': full_text,
                    'kwargs': {}
                })
                logger.info(f"Сообщение добавлено в очередь владельца (очередь: {len(owner_message_queue)})")
        elif message.photo or message.video or message.document or message.voice or message.sticker:
            media_text = f"{chat_info}\n📎 Получено медиафайл"
            async with owner_message_lock:
                owner_message_queue.append({
                    'text': media_text,
                    'kwargs': {}
                })
                logger.info(f"Медиа добавлено в очередь владельца (очередь: {len(owner_message_queue)})")
    except Exception as e:
        logger.error(f"Ошибка пересылки сообщения владельцу: {e}")

# ===== РАСПИСАНИЕ СЛУЧАЙНЫХ ПОСТОВ =====

is_sending = False
last_post_time = 0
MIN_POST_INTERVAL = 2 * 60 * 60

async def scheduler():
    global is_sending, last_post_time
    await asyncio.sleep(10)
    logger.info("Планировщик запущен с случайным временем отправки (не чаще 1 раза в 2 часа)")
    while True:
        try:
            current_time = time.time()
            time_since_last = current_time - last_post_time
            if time_since_last < MIN_POST_INTERVAL:
                wait_time = random.randint(1800, 3600)
                logger.info(f"Следующая проверка через {wait_time // 60} минут")
                await asyncio.sleep(wait_time)
                continue
            
            random_delay = random.randint(3600, 14400)
            post_time = datetime.now() + timedelta(seconds=random_delay)
            logger.info(f"Следующий пост запланирован на {post_time.strftime('%Y-%m-%d %H:%M:%S')} "
                       f"(через {random_delay // 3600} часов {random_delay % 3600 // 60} минут)")
            await asyncio.sleep(random_delay)
            
            if time.time() - last_post_time < MIN_POST_INTERVAL:
                logger.info("Пост уже был отправлен, пропускаем")
                continue
            
            if not is_sending:
                is_sending = True
                try:
                    logger.info("Отправка запланированного поста...")
                    await auto_send_to_all_users()
                    last_post_time = time.time()
                    logger.info(f"Пост отправлен! Следующий не ранее чем через {MIN_POST_INTERVAL // 3600} часов")
                except Exception as e:
                    logger.error(f"Ошибка отправки: {e}")
                finally:
                    is_sending = False
            else:
                logger.warning("Отправка уже идёт, пропускаем")
        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}")
            await asyncio.sleep(60)

# ===== ЗАПУСК =====

async def main():
    try:
        logger.info("=" * 60)
        logger.info("Бот запущен с очередью и модерацией")
        logger.info("Приоритет: Pinterest → Bing → Google → Yandex → Pexels")
        logger.info(f"Подписчиков: {len(load_users())}")
        current_schedule = load_schedule()
        times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
        logger.info(f"Расписание: {times}")
        logger.info(f"Канал: {CHANNEL_ID if CHANNEL_ID else 'авто-поиск'}")
        logger.info(f"Владелец: {OWNER_ID if OWNER_ID else '❌ не задан'}")
        current_price = load_broadcast_price()
        logger.info(f"⭐ Цена broadcast: {current_price} звёзд")
        logger.info(f"💰 Получатель звёзд (канал): {STARS_CHANNEL_ID}")
        logger.info("Азиатские девушки | Модерация включена")
        logger.info("🚫 Детские фото СТРОГО запрещены")
        logger.info("🚫 Студенты и учебные заведения исключены")
        logger.info("🚫 Мужчины на фото исключены")
        logger.info("🚫 Пожилые люди исключены")
        logger.info("✅ KPOP модели в приоритете")
        logger.info("✅ Pinterest в приоритете")
        logger.info("✅ Бикини разрешены (без эротики)")
        logger.info("✅ Пляжные фото разрешены")
        logger.info(f"📨 Сообщения владельцу отправляются с интервалом 1 минута")
        logger.info(f"📊 Посты в канал не чаще 1 раза в {MIN_POST_INTERVAL // 3600} часа (случайное время)")
        logger.info("📢 /broadcast - только в личных сообщениях (поддерживает фото, видео, документы, GIF)")
        logger.info("📸 /photo - только для владельца (в ЛС)")
        logger.info("📢 /post - рассылка всем подписчикам (только владелец)")
        logger.info("⭐ /balance - проверить баланс звёзд (только владелец)")
        logger.info("💡 /check_channel - проверить права бота в канале для звёзд")
        await task_queue.connect()
        logger.info("=" * 60)
        gc.collect()
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Webhook удалён")
        except Exception as e:
            logger.warning(f"Ошибка webhook: {e}")
        asyncio.create_task(queue_processor())
        asyncio.create_task(scheduler())
        asyncio.create_task(send_owner_message_delayed())
        retry_count = 0
        max_retries = 5
        while retry_count < max_retries:
            try:
                await dp.start_polling(
                    bot,
                    allowed_updates=["message", "callback_query", "pre_checkout_query"],
                    skip_updates=True,
                    polling_timeout=30
                )
                break
            except TelegramConflictError as e:
                retry_count += 1
                wait_time = retry_count * 10
                logger.warning(f"Конфликт: {e}")
                logger.info(f"Ожидание {wait_time} секунд... (попытка {retry_count}/{max_retries})")
                if retry_count >= max_retries:
                    logger.error("Превышено количество попыток. Завершаю работу.")
                    sys.exit(1)
                await asyncio.sleep(wait_time)
            except Exception as e:
                logger.error(f"Ошибка в polling: {e}")
                await asyncio.sleep(5)
                continue
            finally:
                await bot.session.close()
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Фатальная ошибка: {e}")
        sys.exit(1)
