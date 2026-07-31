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
    logger.warning("Redis не установлен. Использую локальную очередь")

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
    'south east asian', 'oriental', 'asia girl', 'asia woman',
    'japan', 'korea', 'china', 'thailand', 'vietnam', 'philippines',
    'indonesia', 'malaysia', 'singapore', 'taiwan', 'mongolia',
    'myanmar', 'cambodia', 'laos', 'hong kong', 'macau',
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
    'rwandan', 'somali', 'sudanese', 'american girl', 'european girl',
    'russian girl', 'ukrainian girl', 'indian girl', 'african girl',
    'american woman', 'european woman', 'russian woman', 'ukrainian woman',
    'latina girl', 'brazilian girl', 'mexican girl', 'arab girl',
    'persian girl', 'turkish girl', 'caucasian girl', 'white girl',
    'black girl', 'african woman', 'latina woman', 'brazilian woman',
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

# ТОЛЬКО 18+ (убраны все упоминания младше 18)
AGE_POSITIVE_KEYWORDS = [
    '18', '19', '20', '21', '22', '23', '24', '25',
    '26', '27', '28', '29', '30', '31', '32', '33', '34', '35',
    '18year', '19year', '20year', '21year', '22year',
    '18yo', '19yo', '20yo', '21yo', '22yo', '23yo',
    '20s', 'twenties', 'young adult', 'college', 'university',
    'student', 'freshman', 'sophomore', 'junior', 'senior',
    'adult', 'mature young', 'woman', 'lady',
]

# РАСШИРЕННЫЙ СПИСОК ДЛЯ ФИЛЬТРАЦИИ ДЕТЕЙ (ОЧЕНЬ СТРОГИЙ)
CHILD_EXCLUDE_WORDS = [
    'child', 'children', 'kid', 'kids', 'baby', 'babies', 'toddler',
    'infant', 'preschool', 'kindergarten', 'schoolgirl', 'schoolboy',
    'girl scout', 'boy scout', 'cub scout', 'teen', 'teenager',
    'minor', 'underage', 'little girl', 'little boy', 'young girl',
    'young boy', 'daughter', 'son', 'family', 'family photo',
    'childhood', 'baby girl', 'baby boy', 'newborn', 'cute baby',
    'child model', 'kid model', 'baby model', 'toddler girl', 'toddler boy',
    'elementary', 'middle school', 'high school', 'school uniform',
    'pigtails', 'braces', 'childhood friend', 'young teen',
    'preteen', 'tween', 'grade school', 'primary school',
    'secondary school', 'kindergarten', 'nursery', 'playground',
    'childrens', 'kids', 'childish', 'infantile',
    '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', 
    '13', '14', '15', '16', '17', 'year old girl', 'year old boy',
]

TRADITIONAL_EXCLUDE = [
    'kimono', 'hanbok', 'cheongsam', 'qi pao', 'sari', 'ao dai',
    'traditional', 'folk costume', 'national dress', 'hanfu',
    'mongolian traditional', 'tibetan traditional', 'uyghur traditional',
]

MEN_EXCLUDE_WORDS = [
    'man', 'men', 'boy', 'male', 'guy', 'dude', 'brother',
    'father', 'husband', 'boyfriend', 'gentleman', 'sir',
    'bloke', 'chap', 'fellow', 'lad', 'young man',
]

# ===== ПОИСКОВЫЕ ЗАПРОСЫ (ТОЛЬКО 18+) =====
SEARCH_QUERIES = [
    "japanese woman friend photo casual",
    "japanese woman everyday life candid",
    "japanese woman natural shot street",
    "japanese woman friend taking picture",
    "japanese woman candid moment cafe",
    "japanese woman casual day out",
    "japanese woman authentic daily life",
    "japanese woman spontaneous photo",
    "japanese woman real life snapshot",
    "japanese woman friend photo outside",
    "korean woman friend photo casual",
    "korean woman everyday life candid",
    "korean woman natural shot street",
    "korean woman friend taking picture",
    "korean woman candid moment cafe",
    "korean woman casual day out",
    "korean woman authentic daily life",
    "korean woman spontaneous photo",
    "korean woman real life snapshot",
    "korean woman friend photo outside",
    "chinese woman friend photo casual",
    "chinese woman everyday life candid",
    "chinese woman natural shot street",
    "chinese woman friend taking picture",
    "chinese woman candid moment cafe",
    "chinese woman casual day out",
    "chinese woman authentic daily life",
    "chinese woman spontaneous photo",
    "chinese woman real life snapshot",
    "chinese woman friend photo outside",
    "thai woman friend photo casual",
    "thai woman everyday life candid",
    "thai woman natural shot street",
    "thai woman friend taking picture",
    "thai woman candid moment cafe",
    "thai woman casual day out",
    "thai woman authentic daily life",
    "thai woman spontaneous photo",
    "thai woman real life snapshot",
    "thai woman friend photo outside",
    "vietnamese woman friend photo casual",
    "vietnamese woman everyday life candid",
    "vietnamese woman natural shot street",
    "vietnamese woman friend photo",
    "vietnamese woman candid moment cafe",
    "vietnamese woman casual day out",
    "filipina woman friend photo casual",
    "filipina woman everyday life candid",
    "filipina woman natural shot street",
    "filipina woman friend photo",
    "filipina woman candid moment cafe",
    "indonesian woman friend photo casual",
    "indonesian woman everyday life candid",
    "indonesian woman natural shot street",
    "indonesian woman friend photo",
    "asian woman friend photo outside",
    "asian woman everyday life candid",
    "asian woman natural shot street",
    "asian woman friend taking picture",
    "asian woman candid moment cafe",
    "asian woman casual day out",
    "asian woman authentic daily life",
    "asian woman spontaneous photo",
    "asian woman real life snapshot",
    "asian woman friend photo casual",
    "asian woman laughing with friend",
    "asian woman talking to friend",
    "asian woman walking with friend",
    "asian woman sitting with friend",
    "asian woman shopping with friend",
    "asian woman eating with friend",
    "asian woman coffee with friend",
    "asian woman market with friend",
    "asian woman street food friend",
    "asian woman casual outfit friend",
    "asian woman candid laugh",
    "asian woman natural smile",
    "asian woman genuine moment",
    "asian woman carefree day",
    "asian woman relaxed photo",
    "asian woman happy moment",
    "asian woman friend group photo",
    "asian woman friend gathering",
    "asian woman portrait 20s",
    "asian woman portrait 30s",
    "adult asian woman everyday",
    "mature asian woman casual",
    "asian woman 20 years old",
    "asian woman 30 years old",
]

FITNESS_QUERIES = [
    "japanese fitness woman friend photo",
    "korean gym woman friend photo",
    "chinese fitness woman friend photo",
    "thai sport woman friend photo",
    "asian woman gym with friend",
]

# ===== ФУНКЦИИ ФИЛЬТРАЦИИ (УСИЛЕННАЯ ФИЛЬТРАЦИЯ ДЕТЕЙ) =====

def has_man_in_photo(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    for word in MEN_EXCLUDE_WORDS:
        if word in url_lower:
            return True
    return False

def is_child_photo(url: str) -> bool:
    """Строгая проверка на наличие детей (ВОЗВРАЩАЕТ True если есть ребёнок)"""
    if not url:
        return False
    url_lower = url.lower()
    
    # Проверка по ключевым словам
    for word in CHILD_EXCLUDE_WORDS:
        if word in url_lower:
            logger.warning(f"Обнаружено детское слово: {word} в URL")
            return True
    
    # Проверка возраста 17 и младше
    age_patterns = [
        r'\b(0|1|2|3|4|5|6|7|8|9|10|11|12|13|14|15|16|17)\b',
        r'\b(infant|toddler|child|kid|teen|preteen|tween)\b',
        r'\b(grade|class|school)\s+[1-9]\b',
        r'\b(age|years?|yo|y/o)\s*(0|1|2|3|4|5|6|7|8|9|10|11|12|13|14|15|16|17)\b',
        r'\b(0|1|2|3|4|5|6|7|8|9|10|11|12|13|14|15|16|17)\s*(years?|yo|y/o)\b',
    ]
    for pattern in age_patterns:
        if re.search(pattern, url_lower, re.IGNORECASE):
            logger.warning(f"Обнаружен возраст 0-17 в URL")
            return True
    
    # Проверка на школьную форму или детскую одежду
    school_patterns = [
        r'school\s*uniform',
        r'high\s*school',
        r'middle\s*school',
        r'elementary\s*school',
        r'primary\s*school',
        r'secondary\s*school',
        r'kindergarten',
        r'nursery',
        r'playground',
    ]
    for pattern in school_patterns:
        if re.search(pattern, url_lower, re.IGNORECASE):
            logger.warning(f"Обнаружена школа/детское учреждение в URL")
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
    has_age = False
    for pattern in AGE_POSITIVE_KEYWORDS:
        if pattern in text_to_check:
            has_age = True
            break
    if has_age:
        for keyword in ['blonde', 'blue eyes', 'green eyes', 'redhead', 'ginger']:
            if keyword in text_to_check:
                return False
        return True
    asian_features = [
        'slender', 'petite', 'olive skin', 'dark hair', 'black hair',
        'straight hair', 'bangs', 'double eyelid', 'monolid',
        'kawaii', 'cute', 'innocent', 'pure', 'delicate',
        'slender figure', 'small face', 'fair skin',
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
    """Проверка что возраст 18+ (НЕ возвращает True для детей)"""
    if not url:
        return False
    url_lower = url.lower()
    
    # Сначала проверяем что это НЕ ребёнок
    if is_child_photo(url):
        return False
    
    # Проверяем наличие 18+
    for word in AGE_POSITIVE_KEYWORDS:
        if word in url_lower:
            return True
    
    # Проверяем явное упоминание adult/mature
    if re.search(r'\b(adult|mature|18\+|18plus|eighteen)\b', url_lower, re.IGNORECASE):
        return True
    
    # Проверяем возраст в формате "age 18+" и т.д.
    age_patterns = [
        r'\b(age|years?|yo|y/o)\s*(18|19|20|21|22|23|24|25|26|27|28|29|30|31|32|33|34|35)\b',
        r'\b(18|19|20|21|22|23|24|25|26|27|28|29|30|31|32|33|34|35)\s*(years?|yo|y/o)\b',
        r'\b18\+|18plus|eighteen\b',
    ]
    for pattern in age_patterns:
        if re.search(pattern, url_lower, re.IGNORECASE):
            return True
    
    # Если есть подозрительные слова о возрасте но нет 18+ - отклоняем
    if re.search(r'\b(age|years?|yo|y/o)\b', url_lower, re.IGNORECASE):
        return False
    
    # Если есть слова mature/old - пропускаем (это взрослые)
    if 'mature' in url_lower or 'old' in url_lower or 'senior' in url_lower:
        return True
    
    # По умолчанию - если нет признаков ребёнка и есть азиатские признаки - пропускаем
    # Но с осторожностью, лучше отклонить сомнительные
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

def is_photo_valid(url: str) -> bool:
    """Проверяет фото по всем критериям (ОЧЕНЬ СТРОГАЯ ПРОВЕРКА)"""
    if not url:
        return False
    
    # ПЕРВАЯ И САМАЯ ВАЖНАЯ ПРОВЕРКА - НЕТ ДЕТЕЙ!
    if is_child_photo(url):
        logger.warning(f"Фото отклонено: содержит ребёнка - {url[:100]}")
        return False
    
    if has_man_in_photo(url):
        logger.warning(f"Фото отклонено: содержит мужчину")
        return False
    
    if not is_asian_photo(url):
        logger.warning(f"Фото отклонено: не азиатская внешность")
        return False
    
    if not is_age_appropriate(url):
        logger.warning(f"Фото отклонено: возраст не подходит (нужно 18+)")
        return False
    
    if is_traditional_clothing(url):
        logger.warning(f"Фото отклонено: традиционная одежда")
        return False
    
    unwanted = ['naked', 'nude', 'porn', 'xxx', 'sex', 'erotic', 'bikini']
    for word in unwanted:
        if word in url.lower():
            logger.warning(f"Фото отклонено: нежелательное содержание {word}")
            return False
    
    # Дополнительная проверка на детские лица
    child_face_patterns = [
        r'child\s*face', r'kid\s*face', r'young\s*face',
        r'cute\s*girl', r'cute\s*boy', r'sweet\s*girl',
        r'teen\s*girl', r'teen\s*boy',
    ]
    for pattern in child_face_patterns:
        if re.search(pattern, url.lower(), re.IGNORECASE):
            logger.warning(f"Фото отклонено: детское лицо - {pattern}")
            return False
    
    return True

def is_photo_acceptable(url: str, additional_context: str = "") -> Tuple[bool, str]:
    if not url:
        return False, "Пустой URL"
    
    # Самая строгая проверка на детей
    if is_child_photo(url):
        return False, "Фото содержит ребёнка (строгий запрет)"
    
    if has_man_in_photo(url):
        return False, "Фото содержит мужчину"
    
    if not is_asian_photo(url, additional_context):
        return False, "Не азиатская внешность"
    
    if not is_age_appropriate(url):
        return False, "Возраст не 18+"
    
    if is_traditional_clothing(url):
        return False, "Традиционная одежда"
    
    unwanted = ['naked', 'nude', 'porn', 'xxx', 'sex', 'erotic', 'bikini']
    for word in unwanted:
        if word in url.lower():
            return False, f"Нежелательное содержание: {word}"
    
    return True, "OK"

# ===== СТИЛИ ДЛЯ ГЕНЕРАЦИИ (ТОЛЬКО @maddysontg) =====
style_prompts = {
    'short_joke': """
Ты — Анатолий, холостой блогер средних лет.

ВАЖНО:
- Это КОРОТКИЙ пост (200-350 символов)
- Просто смешная мысль или шутка про жизнь в Азии
- Без длинных историй, без воды
- Одна острая шутка или забавное наблюдение
- Можно спросить у подписчиков: "как у вас там?"

Твой стиль:
- Коротко, ёмко, смешно
- Как будто написал в статус или твит

Напиши короткий смешной пост про жизнь в Азии.

Требования:
- 200-350 символов
- Мат 0-1 раз
- Одна шутка или наблюдение
- Обращайся к читателям на "вы"
- Пиши только готовый пост
""",

    'medium': """
Ты — Анатолий, холостой блогер средних лет, который много путешествует по Азии и заводит знакомства с местными девушками.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- Одна история или ситуация
- Не слишком длинно, но с деталями
- Ты НЕ переезжаешь из страны в страну чаще раза в неделю
- Если вчера ты был в Бангкоке — сегодня ты там же
- Ты описываешь как путешествия, так и семейную жизнь с азиатками
- У тебя НЕТ жены, но когда-то она была (НЕ упоминай когда именно и кто это был)
- ИНОГДА давай советы о жизни в Азии (как секретный разговор)
- Можно спросить у подписчиков: "как у вас там?"

Твой стиль:
- Рассказываешь реальную историю
- Самоирония и юмор
- Живой разговорный язык

Структура:
1. Зацепка (1 предложение)
2. История с деталями
3. Вывод или шутка

Требования:
- 500-700 символов
- Мат 1-2 раза
- Одна острая шутка
- Обращайся к читателям на "вы"
- НЕ упоминай жену (бывшую тоже)
- Пиши только готовый пост
""",

    'long': """
Ты — Анатолий, холостой блогер средних лет, который много путешествует по Азии и заводит знакомства с местными девушками.

ВАЖНО:
- Это ДЛИННЫЙ пост (850-1023 символов)
- Полноценная история с несколькими событиями
- Ты НЕ переезжаешь из страны в страну чаще раза в неделю
- Если вчера ты был в Бангкоке — сегодня ты там же
- Ты описываешь как путешествия, так и семейную жизнь с азиатками
- У тебя НЕТ жены, но когда-то она была (НЕ упоминай когда именно и кто это был)
- МОЖНО дать развёрнутый совет о жизни в Азии (как секретный разговор)
- Можно задать вопрос подписчикам

Твой стиль:
- Детальный рассказ
- Самоирония и юмор
- Живой разговорный язык
- Можно добавить диалоги

Структура:
1. Зацепка (1-2 предложения)
2. Развитие истории с деталями
3. Неожиданный поворот или шутка
4. Естественный вывод

Требования:
- 850-1023 символов
- Мат 2-3 раза
- 1-2 острые шутки
- Обращайся к читателям на "вы"
- НЕ упоминай жену (бывшую тоже)
- Пиши только готовый пост
""",

    'everyday': """
Ты — Анатолий, холостой блогер средних лет, который много путешествует по Азии и заводит знакомства с местными девушками.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- Одна история или ситуация
- Ты НЕ переезжаешь из страны в страну чаще раза в неделю
- Если вчера ты был в Бангкоке — сегодня ты там же
- Ты описываешь как путешествия, так и семейную жизнь с азиатками
- У тебя НЕТ жены, но когда-то она была (НЕ упоминай когда именно и кто это был)
- ИНОГДА давай советы о выгодной жизни в Азии (как секретный разговор)
- Чаще спрашивай у подписчиков в духе: "как там у вас, всё ещё дошираки доедаете?"

Твой стиль:
- Рассказываешь реальные истории
- Самоирония
- Добавляй одну острую шутку
- Пишешь живым разговорным языком

Напиши пост про реальную ситуацию из жизни в Азии (путешествия, знакомства, быт).

Структура:
1. Зацепка
2. История с деталями
3. Самоироничные размышления
4. Естественный вывод (НЕ мораль)

Требования:
- 500-700 символов
- Мат 1-2 раза
- Одна острая шутка
- Обращайся к читателям на "вы"
- НЕ упоминай жену (бывшую тоже)
- Пиши только готовый пост
""",

    'funny': """
Ты — Анатолий, холостой блогер средних лет.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- Смешная история
- Ты НЕ переезжаешь из страны в страну чаще раза в неделю
- Ты описываешь как путешествия, так и семейную жизнь с азиатками
- У тебя НЕТ жены, но когда-то она была (НЕ упоминай когда именно и кто это был)

Твой стиль:
- Рассказываешь смешные истории
- Главный объект шуток — ты сам
- Юмор самоироничный
- Добавляй одну острую шутку
- Пишешь живым языком

Напиши смешной пост про свою жизнь в Азии.

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
- Пиши только готовый пост
""",

    'romantic': """
Ты — Анатолий, холостой блогер средних лет.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- Романтичная история
- Ты НЕ переезжаешь из страны в страну чаще раза в неделю
- Ты описываешь как путешествия, так и семейную жизнь с азиатками
- У тебя НЕТ жены, но когда-то она была (НЕ упоминай когда именно и кто это был)

Твой стиль:
- Рассказываешь о своих чувствах с самоиронией
- Немного романтики, но с юмором
- Честно говоришь о своих недостатках
- Добавляй одну острую шутку (про себя)

Напиши романтичный пост о встрече с азиаткой во время путешествия.

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
- Пиши только готовый пост
""",

    'envy': """
Ты — Анатолий, холостой блогер средних лет.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- Зависть с юмором
- Ты НЕ переезжаешь из страны в страну чаще раза в неделю
- Ты описываешь как путешествия, так и семейную жизнь с азиатками
- У тебя НЕТ жены, но когда-то она была (НЕ упоминай когда именно и кто это был)
- ИНОГДА давай советы о жизни в Азии (как секретный разговор)

Твой стиль:
- Рассказываешь о том, чему завидуешь, с юмором
- Самоирония
- Добавляй одну острую шутку
- Пишешь живо

Напиши пост о том, чему ты завидуешь в Азии.

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
- Пиши только готовый пост
""",

    'joke': """
Ты — Анатолий, холостой блогер средних лет.

ВАЖНО:
- Это СРЕДНИЙ пост (500-700 символов)
- 70% шуток, 30% наблюдений
- Ты НЕ переезжаешь из страны в страну чаще раза в неделю
- Ты описываешь как путешествия, так и семейную жизнь с азиатками
- У тебя НЕТ жены, но когда-то она была (НЕ упоминай когда именно и кто это был)
- Можно спросить у подписчиков: "как у вас там?"

Твой стиль:
- Острые шутки без оскорблений
- Можно использовать мат
- Пишешь как в баре

Напиши пост с острой шуткой про жизнь в Азии.

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

# ===== КЭШ =====
last_posts = []

def add_to_last_posts(text: str):
    global last_posts
    if not text or len(text) < 10:
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

def get_fallback_caption() -> str:
    fallbacks = [
        "Вчера в Бангкоке ко мне подошла стайка тайских девчонок и попросила сфоткаться. Я сразу расправил плечи - ну, думаю, наконец-то заметили мой шарм, мою харизму. Делаю serious face, как будто я важный чел. А они визжат, тычут пальцами. И тут одна тянет мой телефон, начинает листать и показывает на фото какого-то китайского блогера с двумя миллионами подписчиков. Оказалось, я просто попал в кадр, потому что стоял на том же месте, где он снимал своё видосик. Стою, улыбаюсь, а в голове: Анатолий, ну ты и дурак, опять повёлся. Ну и ладно, зато теперь я типа знаменит локально - сегодня меня уже трижды окликнули эй, Толик! на базаре. Вывод один: слава - это когда тебя путают с другим, но ты всё равно рад, что хоть с кем-то перепутали. И это пиздец как греет душу, честно вам скажу.",
        "Сижу в кафе в Чиангмае, пью кофе, смотрю на прохожих. Вдруг подходит местная девушка и говорит: Вы тот самый блогер? Я сразу напрягся, думаю - неужели узнали? А она показывает на мою футболку с логотипом какой-то группы и говорит, что ей нравится их музыка. Оказалось, она думала, что я участник группы. Я даже не стал её разочаровывать - улыбнулся, сфоткался с ней и пошёл дальше. Теперь я официально музыкант. Хотя на гитаре играю только в голове. Но знаете, приятно, когда тебя замечают, даже если по ошибке. Вот так и живём, ребята.",
        "Вчера на рынке в Бангкоке продавщица назвала меня красивым иностранным мужчиной. Я чуть не подавился соком. Расправил плечи, уже приготовился торговаться с чувством собственного достоинства. А она оказалась просто вежливая - так она всех мужиков называет, чтобы цену набить. Но осадочек остался, приятный такой. Домой пришёл, в зеркало посмотрел - ну вроде ничего, харизма есть. Наверное, я всё-таки красавчик, просто в этом городе слишком много настоящих красавчиков. Но мы не сдаёмся, коллеги!",
        "Тайские девушки - это отдельный вид искусства. Вчера одна сказала мне: Ты такой забавный, как мой папа. Я чуть кофе не поперхнулся. Думаю - ну всё, старость пришла. А она потом говорит: Это комплимент, папа у меня крутой! Ну ладно, тогда норм. Буду теперь гордо носить звание папик в Таиланде. Хотя, сука, обидно было первые пять секунд.",
    ]
    return random.choice(fallbacks)

def generate_caption() -> str:
    logger.info("Генерирую уникальный пост...")
    
    if not DEEPSEEK_API_KEY:
        logger.warning("Нет ключа DeepSeek, использую резерв")
        caption = get_fallback_caption()
        caption = clean_text(caption)
        caption = truncate_by_sentences(caption)
        validated, error = validate_caption(caption, min_length=500, max_length=1023)
        if validated:
            return validated
        return clean_text(truncate_by_sentences(get_fallback_caption()))
    
    rand = random.random()
    if rand < 0.20:
        style = 'short_joke'
        logger.info("Выбран КОРОТКИЙ пост (шутка)")
        min_len, max_len = 200, 400
    elif rand < 0.40:
        style = 'long'
        logger.info("Выбран ДЛИННЫЙ пост")
        min_len, max_len = 850, 1023
    else:
        weighted_styles = ['everyday', 'everyday', 'funny', 'romantic', 'envy', 'joke']
        style = random.choice(weighted_styles)
        logger.info(f"Выбран СРЕДНИЙ пост (стиль: {style})")
        min_len, max_len = 500, 700
    
    prompt = style_prompts.get(style, style_prompts['medium'])
    prompt += "\n\nТвой ответ (ТОЛЬКО ПОСТ, БЕЗ РАССУЖДЕНИЙ):"
    
    alternative_prompts = {
        'short_joke': [
            "Напиши короткую смешную мысль про жизнь в Азии. 200-350 символов.",
            "Короткая шутка про Азию. 200-350 символов.",
            "Забавное наблюдение про жизнь в Азии. 200-350 символов.",
        ],
        'long': [
            "Напиши длинный пост с историей про жизнь в Азии. 850-1023 символов.",
            "Подробный рассказ о жизни в Азии. 850-1023 символов.",
            "Развёрнутая история из Азии с деталями. 850-1023 символов.",
        ],
        'medium': [
            "Напиши пост про жизнь в Азии с юмором. 500-700 символов.",
            "История из жизни в Азии. 500-700 символов.",
            "Забавная ситуация из Азии. 500-700 символов.",
        ]
    }
    
    for attempt in range(5):
        try:
            url = "https://api.deepseek.com/chat/completions"
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            current_prompt = prompt
            if attempt > 0:
                if style == 'short_joke':
                    alt = random.choice(alternative_prompts['short_joke'])
                elif style == 'long':
                    alt = random.choice(alternative_prompts['long'])
                else:
                    alt = random.choice(alternative_prompts['medium'])
                current_prompt = alt + "\n\nТвой ответ (ТОЛЬКО ПОСТ, БЕЗ РАССУЖДЕНИЙ):"
                logger.info(f"Пробую альтернативный промпт (попытка {attempt+1})...")
            
            data = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": """Ты — Анатолий, холостой блогер средних лет. Ты путешествуешь по Азии и ведёшь блог от своего лица.

Твой стиль:
- Самоирония и сарказм
- Рассказываешь реальные истории из жизни
- Можешь добавить острую шутку — не оскорбительную, с юмором, может содержать мат
- Шути про себя или про жизнь, но без политики
- Пиши так, будто рассказываешь друзьям в баре

Важно:
- Пиши от первого лица
- Используй мат для эмоций
- Обращайся к читателям на "вы"
- Не упоминай жену
- Не используй штампы
- Обязательно заверши мысль - естественный вывод, не мораль
- Если пишешь шутку — она должна быть острой, но не оскорбительной
- Отвечай ТОЛЬКО готовым постом. БЕЗ РАССУЖДЕНИЙ. Только текст поста."""},
                    {"role": "user", "content": current_prompt}
                ],
                "temperature": 1.2,
                "max_tokens": 1500,
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 400:
                error_text = response.text.lower()
                if "извините" in error_text or "не могу" in error_text or "не разрешено" in error_text:
                    logger.warning(f"Контент заблокирован, пробую другой промпт (попытка {attempt+1})...")
                    continue
            
            if response.status_code != 200:
                logger.error(f"DeepSeek ошибка: {response.status_code}")
                continue
            
            result = response.json()
            if not result.get("choices") or len(result["choices"]) == 0:
                logger.warning("Нет choices в ответе")
                continue
            
            choice = result["choices"][0]
            generated_content = choice.get("message", {}).get("content", "")
            finish_reason = choice.get("finish_reason", "")
            usage = result.get("usage", {})
            logger.info(f"finish_reason={finish_reason} | tokens={usage.get('completion_tokens', '?')} | chars={len(generated_content)}")
            
            if not generated_content:
                logger.warning("Пустой ответ")
                continue
            
            if finish_reason == "length":
                generated_content = complete_truncated_text(generated_content, finish_reason)
            
            if not generated_content or len(generated_content.strip()) < 20:
                logger.warning("Пустой или короткий ответ")
                continue
            
            caption = generated_content.strip().strip('"').strip("'")
            
            if not caption:
                continue
            
            if caption.lower().startswith(("мы должны", "нужно", "я должен", "напиши", "вот", "давайте", "попробуем", "извините")):
                logger.warning("DeepSeek выдал рассуждение или отказ, пробуем другой промпт...")
                continue
            
            if is_similar(caption):
                logger.warning("Пост похож на недавний, пробуем ещё...")
                continue
            
            caption = clean_text(caption)
            caption = truncate_by_sentences(caption, max_length=1023)
            
            if len(caption) < min_len:
                logger.warning(f"Пост слишком короткий ({len(caption)} символов, нужно {min_len}), пробуем ещё...")
                continue
            
            if len(caption) > max_len + 50:
                logger.warning(f"Пост слишком длинный ({len(caption)} символов, нужно {max_len}), пробуем ещё...")
                continue
            
            if style == 'short_joke':
                validated, error = validate_caption(caption, min_length=100, max_length=400)
            else:
                validated, error = validate_caption(caption, min_length=min_len, max_length=max_len)
            
            if validated:
                logger.info(f"Сгенерирован пост ({len(validated)} символов, тип: {style})")
                add_to_last_posts(validated)
                return validated
            else:
                logger.warning(f"Текст не прошёл проверку: {error}, пробуем ещё...")
                continue
            
        except Exception as e:
            logger.error(f"Ошибка генерации (попытка {attempt+1}): {e}")
            continue
    
    logger.warning("Не удалось сгенерировать уникальный пост, использую резерв")
    caption = get_fallback_caption()
    caption = clean_text(caption)
    caption = truncate_by_sentences(caption, max_length=1023)
    validated, error = validate_caption(caption, min_length=500, max_length=1023)
    if validated:
        return validated
    return clean_text(truncate_by_sentences(get_fallback_caption(), max_length=1023))

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
        url = f"https://www.bing.com/images/search?q={encoded_query}&form=HDRSC3&first=1&count=35&safeSearch=strict"
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

# ===== АСИНХРОННАЯ ФУНКЦИЯ ПОЛУЧЕНИЯ ФОТО =====

async def get_random_photo():
    global history
    
    if len(history) > 80:
        logger.info("История переполнена, очищаю...")
        history = []
        save_history(history)
    
    queries = SEARCH_QUERIES.copy()
    
    if random.random() < 0.1:
        queries.extend(FITNESS_QUERIES)
        logger.info("Добавлен фитнес-запрос (редко)")
    
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
                logger.info(f"Поиск в {source_name}: {query}")
                photo = search_func(query)
                if photo and photo not in history:
                    if is_photo_valid(photo):
                        history.append(photo)
                        save_history(history)
                        logger.info(f"Найдено подходящее фото: {photo[:60]}...")
                        return photo
            except Exception as e:
                logger.error(f"Ошибка в {source_name}: {e}")
                continue
            await asyncio.sleep(0.3)
    
    logger.warning("Не удалось найти новое фото, очищаю историю...")
    history = []
    save_history(history)
    
    for query in queries[:10]:
        for source_name, search_func in search_functions:
            try:
                photo = search_func(query)
                if photo and is_photo_valid(photo):
                    history.append(photo)
                    save_history(history)
                    logger.info(f"Найдено фото после очистки: {photo[:60]}...")
                    return photo
            except:
                continue
    
    logger.error("Не удалось найти подходящее фото!")
    return None

# ===== ОЧЕРЕДЬ ЗАДАЧ =====

class TaskQueue:
    def __init__(self):
        self.redis = None
        self.connected = False
        self._local_queue: Dict[str, List[Dict[str, Any]]] = {}
    
    async def connect(self):
        if not REDIS_AVAILABLE:
            logger.warning("Redis недоступен, использую локальную очередь")
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
            'child', 'children', 'kid', 'baby', 'teen', 'minor', 'underage'
        ]
        self.suspicious_patterns = [
            r'https?://\S+\.(ru|su|cc|to|top|club|online|site|xyz|click|win|bid)',
            r'\b(купить|продать|деньги|заработать|бизнес|инвестиции)\b',
        ]
    
    async def moderate_content(self, post: PostContent) -> Tuple[Optional[bool], str]:
        try:
            text_lower = post.caption.lower()
            photo_lower = post.photo_url.lower()
            
            # Строгая проверка на детей в тексте
            for word in self.banned_words:
                if word in text_lower or word in photo_lower:
                    if word in ['child', 'children', 'kid', 'baby', 'teen', 'minor', 'underage']:
                        return False, f"Обнаружено упоминание ребёнка: {word}"
                    return False, f"Обнаружено запрещенное слово: {word}"
            
            # Проверка на возраст 18+ в тексте
            if re.search(r'\b(17|16|15|14|13|12|11|10|9|8|7|6|5|4|3|2|1|0)\b', text_lower):
                if not re.search(r'\b(18|19|20|21|22|23|24|25|26|27|28|29|30)\b', text_lower):
                    return False, "Обнаружен возраст младше 18"
            
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
            caption = truncate_by_sentences(caption, max_length=1023)
            validated, error = validate_caption(caption, min_length=500, max_length=1023)
            if validated:
                caption = validated
            else:
                caption = clean_text(get_fallback_caption())
                caption = truncate_by_sentences(caption, max_length=1023)
                validated, error = validate_caption(caption, min_length=500, max_length=1023)
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

async def send_to_all_users():
    try:
        users_list = load_users()
        if not users_list:
            logger.warning("Нет пользователей для отправки")
            return
        logger.info(f"Добавление постов в очередь для {len(users_list)} пользователей...")
        photo_url = await get_random_photo()
        if not photo_url:
            logger.error("Не удалось найти фото")
            return
        caption = generate_caption()
        caption = clean_text(caption)
        caption = truncate_by_sentences(caption, max_length=1023)
        validated, error = validate_caption(caption, min_length=500, max_length=1023)
        if validated:
            caption = validated
        else:
            caption = clean_text(get_fallback_caption())
            caption = truncate_by_sentences(caption, max_length=1023)
            validated, error = validate_caption(caption, min_length=500, max_length=1023)
            if validated:
                caption = validated
        base_post_id = f"post_{int(time.time())}"
        for chat_id in users_list:
            post_data = {
                'id': f"{base_post_id}_{chat_id}",
                'chat_id': chat_id,
                'photo_url': photo_url,
                'caption': caption,
                'user_id': 0,
                'timestamp': time.time(),
                'needs_moderation': False
            }
            await task_queue.push(QUEUE_NAME, post_data)
        channel_id = CHANNEL_ID
        if not channel_id or not channel_id.strip():
            channel_id = await get_channel_id()
        if channel_id:
            await task_queue.push(QUEUE_NAME, {
                'id': f"{base_post_id}_channel",
                'chat_id': channel_id,
                'photo_url': photo_url,
                'caption': caption,
                'user_id': 0,
                'timestamp': time.time(),
                'needs_moderation': False
            })
        logger.info(f"{len(users_list)} задач добавлены в очередь")
    except Exception as e:
        logger.error(f"Ошибка в send_to_all_users: {e}")

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

# ===== КОМАНДА /BROADCAST =====

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
        text = message.text.replace("/broadcast", "").strip()
        if not text:
            current_price = load_broadcast_price()
            await message.answer(
                f"📢 Чтобы отправить сообщение всем подписчикам, напишите:\n"
                f"/broadcast Ваше сообщение\n\n"
                f"⭐ Стоимость: {current_price} звёзд\n"
                f"💰 Средства поступят на канал\n\n"
                f"После оплаты сообщение будет отправлено на модерацию."
            )
            return
        current_price = load_broadcast_price()
        prices = [LabeledPrice(label="⭐ Рассылка", amount=current_price)]
        await bot.send_invoice(
            chat_id=chat_id,
            title="📢 Рассылка сообщения",
            description=f"Отправка сообщения всем подписчикам бота\n\nТекст: {text[:100]}{'...' if len(text) > 100 else ''}",
            payload=f"broadcast_{user_id}_{int(time.time())}",
            provider_token="",
            currency="XTR",
            prices=prices,
            start_parameter="broadcast",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"⭐ Оплатить {current_price} звёзд", pay=True)]
            ])
        )
        broadcast_data[user_id] = {
            'text': text,
            'timestamp': time.time(),
            'chat_id': chat_id,
            'user_id': user_id
        }
    except Exception as e:
        logger.error(f"Ошибка в команде broadcast: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")

@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    try:
        if pre_checkout_query.invoice_payload.startswith("broadcast_"):
            await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
        else:
            await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Неизвестный платёж")
    except Exception as e:
        logger.error(f"Ошибка в pre_checkout: {e}")
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Ошибка")

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
        if not text:
            await message.answer("❌ Текст сообщения не найден.")
            return
        broadcast_id = f"broadcast_{int(time.time())}_{hashlib.md5(text.encode()).hexdigest()[:8]}"
        del broadcast_data[user_id]
        pending_broadcasts[broadcast_id] = {
            'text': text,
            'user_id': user_id,
            'timestamp': time.time(),
            'chat_id': message.chat.id
        }
        await send_broadcast_for_moderation(broadcast_id, text, user_id)
        await message.answer(
            f"✅ Оплата получена! Сообщение отправлено на модерацию.\n"
            f"📝 Текст: {text[:100]}{'...' if len(text) > 100 else ''}\n\n"
            f"⏳ Ожидайте подтверждения от администратора."
        )
    except Exception as e:
        logger.error(f"Ошибка в successful_payment: {e}")
        await message.answer(f"❌ Ошибка при обработке платежа: {str(e)}")

async def send_broadcast_for_moderation(broadcast_id: str, text: str, user_id: int):
    if not OWNER_ID:
        return
    try:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"broad_approve_{broadcast_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"broad_reject_{broadcast_id}")
            ]
        ])
        text_preview = text[:300] + "..." if len(text) > 300 else text
        await bot.send_message(
            chat_id=OWNER_ID,
            text=f"📋 Новая рассылка на модерацию #{broadcast_id}\n\n"
                 f"📝 Текст:\n{text_preview}\n\n"
                 f"👤 Заказчик ID: {user_id}\n"
                 f"💰 Оплачено: {load_broadcast_price()} ⭐\n"
                 f"📤 Средства поступят на канал {STARS_CHANNEL_ID}\n\n"
                 f"⏳ После подтверждения будет задержка 5 минут перед публикацией.",
            reply_markup=keyboard
        )
        logger.info(f"Рассылка {broadcast_id} отправлена на модерацию владельцу")
    except Exception as e:
        logger.error(f"Ошибка отправки на модерацию: {e}")

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
            await callback.answer("✅ Сообщение одобрено. Будет опубликовано через 5 минут.", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n✅ ОДОБРЕНО (будет опубликовано через 5 минут)",
                reply_markup=None
            )
            await asyncio.sleep(300)
            if broadcast_id in pending_broadcasts:
                text = broadcast_info['text']
                users_list = load_users()
                sent_count = 0
                failed_count = 0
                for chat_id in users_list:
                    try:
                        await bot.send_message(chat_id=chat_id, text=text)
                        sent_count += 1
                        await asyncio.sleep(0.3)
                    except Exception as e:
                        logger.error(f"Ошибка отправки в {chat_id}: {e}")
                        failed_count += 1
                try:
                    if CHANNEL_ID and CHANNEL_ID.strip():
                        await bot.send_message(chat_id=CHANNEL_ID, text=text)
                        logger.info(f"Отправлено в канал {CHANNEL_ID}")
                except Exception as e:
                    logger.error(f"Ошибка отправки в канал: {e}")
                del pending_broadcasts[broadcast_id]
                try:
                    await bot.send_message(
                        chat_id=OWNER_ID,
                        text=f"📊 Рассылка #{broadcast_id} завершена!\n"
                             f"✅ Отправлено: {sent_count}\n"
                             f"❌ Ошибок: {failed_count}\n"
                             f"📝 Текст: {text[:200]}{'...' if len(text) > 200 else ''}"
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки отчета: {e}")
                try:
                    user_id = broadcast_info.get('user_id')
                    if user_id:
                        await bot.send_message(
                            chat_id=user_id,
                            text=f"✅ Ваше сообщение опубликовано!\n"
                                 f"📨 Отправлено: {sent_count} пользователям\n"
                                 f"📝 Текст: {text[:100]}{'...' if len(text) > 100 else ''}"
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

# ===== ОСТАЛЬНЫЕ КОМАНДЫ =====

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
        if str(chat_id) not in [str(u) for u in users]:
            users.append(str(chat_id))
            save_users(users)
            logger.info(f"Добавлен пользователь: {chat_id}")
        await generate_and_queue_post(str(chat_id), user_id, skip_moderation=True)
        channel_status = f"\n📢 Канал: {'✅ подключён' if CHANNEL_ID and CHANNEL_ID.strip() else '🔄 авто-поиск'}"
        current_schedule = load_schedule()
        times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
        current_price = load_broadcast_price()
        await msg.answer(
            f"✅ Вы подписаны на рассылку!\n"
            f"📸 Уникальные посты про молодых азиаток (18-30 лет)\n"
            f"⏰ Расписание: {times}\n"
            f"{channel_status}\n"
            f"🔄 /photo - получить фото сейчас\n"
            f"⏰ /schedule - изменить расписание\n"
            f"📢 /broadcast - отправить сообщение всем (⭐ {current_price} звёзд)\n"
            f"🛑 /stop - отписаться"
        )
    except Exception as e:
        logger.error(f"Ошибка в команде start: {e}")
        await msg.answer("❌ Произошла ошибка. Попробуйте позже.")

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
        if not await check_user_can_use_command(msg):
            await msg.reply("⛔ Только администраторы могут запрашивать фото.")
            return
        if str(chat_id) not in [str(u) for u in users]:
            await msg.answer("⚠️ Бот не активирован. Напишите /start")
            return
        is_owner = (user_id in ALLOWED_PHOTO_USERS)
        if is_owner:
            await generate_and_queue_post(str(chat_id), user_id, skip_moderation=True)
            channel_id = CHANNEL_ID
            if not channel_id or not channel_id.strip():
                channel_id = await get_channel_id()
            if channel_id:
                await generate_and_queue_post(str(channel_id), user_id, skip_moderation=True)
                await msg.answer("✅ Посты добавлены в очередь")
        else:
            await generate_and_queue_post(str(chat_id), user_id, skip_moderation=True)
            await msg.answer("✅ Пост добавлен в очередь")
    except Exception as e:
        logger.error(f"Ошибка в команде photo: {e}")
        await msg.answer("❌ Произошла ошибка. Попробуйте позже.")

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
                    await send_to_all_users()
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
        logger.info("Приоритет: Bing → Google → Yandex → Pexels")
        logger.info(f"Подписчиков: {len(load_users())}")
        current_schedule = load_schedule()
        times = ", ".join(current_schedule.get("times", ["12:00", "21:00"]))
        logger.info(f"Расписание: {times}")
        logger.info(f"Канал: {CHANNEL_ID if CHANNEL_ID else 'авто-поиск'}")
        logger.info(f"Владелец: {OWNER_ID if OWNER_ID else '❌ не задан'}")
        current_price = load_broadcast_price()
        logger.info(f"⭐ Цена broadcast: {current_price} звёзд")
        logger.info(f"💰 Получатель звёзд (канал): {STARS_CHANNEL_ID}")
        logger.info("Азиатские девушки | 18-30 лет | Модерация включена")
        logger.info("🚫 Детские фото СТРОГО запрещены (0-17 лет)")
        logger.info("🚫 Мужчины на фото исключены")
        logger.info("📸 Только любительские съёмки в Азии")
        logger.info(f"📨 Сообщения владельцу отправляются с интервалом 1 минута")
        logger.info(f"📊 Посты в канал не чаще 1 раза в {MIN_POST_INTERVAL // 3600} часа (случайное время)")
        logger.info("📢 /broadcast - только в личных сообщениях")
        logger.info("📸 /photo - в ЛС только для владельца и пользователя 1361723521")
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
