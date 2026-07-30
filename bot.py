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
from aiogram.types import Message, ChatMember, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, PreCheckoutQuery, LabeledPrice
from aiogram.exceptions import TelegramConflictError, TelegramAPIError

# ===== КОНФИГУРАЦИЯ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_ID = int(os.getenv("OWNER_ID", 0))

# Настройки для Stars
STARS_CHANNEL_ID = 1361723521  # Получатель звёзд
BROADCAST_CHANNEL_ID = -1003988169576  # Канал для команды broadcast
BROADCAST_PRICE_FILE = "broadcast_price.json"  # Файл для хранения цены

# Redis настройки (опционально)
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

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===== ФАЙЛЫ ДЛЯ ХРАНЕНИЯ ДАННЫХ =====
USERS_FILE = "users.json"
HISTORY_FILE = "history.json"
SCHEDULE_FILE = "schedule.json"

# ===== РАБОТА С ЦЕНОЙ =====

def load_broadcast_price() -> int:
    """Загружает цену из файла"""
    try:
        with open(BROADCAST_PRICE_FILE, "r") as f:
            data = json.load(f)
            return data.get("price", 5)
    except:
        return 5

def save_broadcast_price(price: int):
    """Сохраняет цену в файл"""
    try:
        with open(BROADCAST_PRICE_FILE, "w") as f:
            json.dump({"price": price}, f)
        return True
    except:
        return False

broadcast_price = load_broadcast_price()

# ===== РАСШИРЕННЫЕ СПИСКИ КЛЮЧЕВЫХ СЛОВ =====

# Азиатские страны и национальности
ASIAN_KEYWORDS = [
    'asian', 'japanese', 'korean', 'chinese', 'thai', 'vietnamese',
    'filipino', 'indonesian', 'malaysian', 'singaporean', 'taiwanese',
    'mongolian', 'burmese', 'cambodian', 'laotian', 'east asian',
    'south east asian', 'oriental', 'asia girl', 'asia woman',
    'japan', 'korea', 'china', 'thailand', 'vietnam', 'philippines',
    'indonesia', 'malaysia', 'singapore', 'taiwan', 'mongolia',
    'myanmar', 'cambodia', 'laos', 'hong kong', 'macau',
]

# Не азиатские страны и национальности
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

# Азиатские имена (для дополнительной фильтрации)
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

# Упоминания возраста (для азиаток часто указывают возраст)
AGE_POSITIVE_KEYWORDS = [
    '18', '19', '20', '21', '22', '23', '24', '25',
    '26', '27', '28', '29', '30',
    '18year', '19year', '20year', '21year', '22year',
    '18yo', '19yo', '20yo', '21yo', '22yo', '23yo',
    '20s', 'twenties', 'young', 'college', 'university',
    'student', 'freshman', 'sophomore', 'junior', 'senior',
]

# Традиционная одежда (исключаем)
TRADITIONAL_EXCLUDE = [
    'kimono', 'hanbok', 'cheongsam', 'qi pao', 'sari', 'ao dai',
    'traditional', 'folk costume', 'national dress', 'hanfu',
    'mongolian traditional', 'tibetan traditional', 'uyghur traditional',
]

# ===== ПОИСКОВЫЕ ЗАПРОСЫ (улучшенные) =====
SEARCH_QUERIES = [
    "japanese girl casual selfie 20",
    "japanese woman everyday life 20s",
    "japanese girl instagram photo 20",
    "japanese woman casual style 20",
    "japanese girl natural portrait 20",
    "japanese woman street style 20",
    "japanese girl city selfie 20",
    "japanese woman cafe selfie 20",
    "japanese girl summer outfit 20",
    "japanese woman modern style 20",
    "japanese college girl 20",
    "japanese university student 20",
    "japanese girl 20s portrait",
    "chinese girl casual selfie 20",
    "chinese woman everyday life 20s",
    "chinese girl instagram photo 20",
    "chinese woman casual style 20",
    "chinese girl natural portrait 20",
    "chinese woman street style 20",
    "chinese girl city selfie 20",
    "chinese woman cafe selfie 20",
    "chinese girl summer dress 20",
    "chinese woman modern outfit 20",
    "chinese college girl 20",
    "chinese university student 20",
    "korean girl casual selfie 20",
    "korean woman everyday life 20s",
    "korean girl instagram photo 20",
    "korean woman casual style 20",
    "korean girl natural portrait 20",
    "korean woman street style 20",
    "korean girl city selfie 20",
    "korean woman cafe selfie 20",
    "korean girl summer dress 20",
    "korean woman modern style 20",
    "korean college girl 20",
    "korean university student 20",
    "thai girl casual selfie 20",
    "thai woman everyday life 20s",
    "thai girl instagram photo 20",
    "thai woman casual style 20",
    "thai girl natural portrait 20",
    "thai woman street style 20",
    "thai girl city selfie 20",
    "thai woman cafe selfie 20",
    "thai girl summer outfit 20",
    "thai woman modern dress 20",
    "thai college girl 20",
    "thai university student 20",
    "asian girl 20 years old instagram",
    "east asian woman 20s casual",
    "southeast asian girl 20s photo",
    "young asian woman 20s portrait",
    "asian college girl 20",
    "asian university student 20s",
    "asian girl 20s fashion",
    "asian woman 20s lifestyle",
]

FITNESS_QUERIES = [
    "japanese fitness girl 20s",
    "korean gym girl 20s",
    "chinese fitness woman 20s",
    "thai sport girl 20s",
]

# ===== УЛУЧШЕННАЯ ФИЛЬТРАЦИЯ =====

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
    
    if 'child' in url_lower or 'kid' in url_lower or 'baby' in url_lower:
        return False
    
    if 'mature' in url_lower or 'old' in url_lower or 'senior' in url_lower:
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

def is_photo_acceptable(url: str, additional_context: str = "") -> Tuple[bool, str]:
    if not url:
        return False, "Пустой URL"
    
    if not is_asian_photo(url, additional_context):
        return False, "Не азиатская внешность"
    
    if not is_age_appropriate(url):
        return False, "Возраст не подходит"
    
    if is_traditional_clothing(url):
        return False, "Традиционная одежда"
    
    unwanted = ['naked', 'nude', 'porn', 'xxx', 'sex', 'erotic', 'bikini']
    for word in unwanted:
        if word in url.lower():
            return False, f"Нежелательное содержание: {word}"
    
    return True, "OK"

# ===== СТИЛИ ДЛЯ ГЕНЕРАЦИИ (С ШУТКАМИ) =====
style_prompts = {
    'everyday': """
Ты — Анатолий, холостой блогер средних лет, который много путешествует по Азии.

Твоя внешность:
- Носишь очки
- Короткая стрижка
- Небольшая щетина на лице
- Обычный парень, не модель

Твой стиль:
- Рассказываешь реальные истории, будто они произошли вчера или сегодня.
- Всегда сначала действие, потом размышления.
- Главный объект самоиронии — ты сам. Ты часто оказываешься в неловких ситуациях.
- Юмор строится на иронии над собой и ситуациях, где ты выглядишь глупо.
- Добавляй одну острую шутку в стиле @Maddysontg — не оскорбительную, с юмором, может содержать мат. Шути про себя или про жизнь, но без политики.
- Пишешь живым разговорным языком, будто рассказываешь историю друзьям.

Напиши пост про реальную ситуацию в Азии, где ты попал в неловкое положение.

Структура поста:
1. Первое предложение - зацепка: конкретная ситуация
2. Затем подробный рассказ с деталями
3. Самоироничные размышления о себе
4. Естественный вывод из истории

Требования:
- 700-900 символов
- Мат 1-2 раза (бля, сука, пиздец), только как эмоция
- Одна острая шутка в стиле @Maddysontg
- Обращайся к читателям на "вы"
- Не упоминай жену
- Не используй штампы
- Пиши только готовый пост
""",

    'funny': """
Ты — Анатолий, холостой блогер средних лет, в очках, с короткой стрижкой и небольшой щетиной.

Твой стиль:
- Рассказываешь смешные истории из жизни в Азии
- Главный объект шуток — ты сам и твои неловкие ситуации
- Юмор самоироничный, без оскорблений других
- Добавляй одну острую шутку в стиле @Maddysontg
- Пишешь живым языком, как рассказываешь друзьям

Напиши смешной пост про свою жизнь в Азии.

Структура:
1. Необычная ситуация
2. Подробности с диалогами
3. Самоирония
4. Смешной вывод

Требования:
- 700-900 символов
- Мат 1-2 раза
- Одна острая шутка
- Обращайся к читателям на "вы"
- Пиши только готовый пост
""",

    'romantic': """
Ты — Анатолий, холостой блогер средних лет, в очках, с короткой стрижкой и щетиной.

Твой стиль:
- Рассказываешь о своих чувствах с самоиронией
- Немного романтики, но с юмором
- Честно говоришь о своих недостатках
- Добавляй одну острую шутку в стиле @Maddysontg (про себя, не про девушку)
- Пишешь тепло, но без пафоса

Напиши романтичный пост о встрече с азиаткой.

Структура:
1. Неожиданная встреча
2. Твои чувства и сомнения
3. Самоирония над собой
4. Тёплый вывод

Требования:
- 700-900 символов
- Мат 1-2 раза
- Одна острая шутка
- Обращайся к читателям на "вы"
- Пиши только готовый пост
""",

    'envy': """
Ты — Анатолий, холостой блогер средних лет, в очках, с короткой стрижкой и щетиной.

Твой стиль:
- Рассказываешь о том, чему завидуешь, с юмором
- Самоирония над своей жизнью
- Честно и смешно о своих желаниях
- Добавляй одну острую шутку в стиле @Maddysontg
- Пишешь живо и увлекательно

Напиши пост о том, чему ты завидуешь в Азии.

Структура:
1. Что тебя поразило
2. Твои размышления
3. Сравнение с собой
4. Ироничный вывод

Требования:
- 700-900 символов
- Мат 1-2 раза
- Одна острая шутка
- Обращайся к читателям на "вы"
- Пиши только готовый пост
""",

    'joke': """
Ты — Анатолий, холостой блогер средних лет, в очках, с короткой стрижкой и щетиной.

Твой стиль:
- Твои посты — это 70% шуток и 30% жизненных наблюдений
- Ты можешь пошутить про себя, про других, про жизнь в Азии
- Шутки острые, но не оскорбительные, без политики
- Можно использовать мат для усиления эффекта
- Главное — смешно и честно
- Пишешь так, будто рассказываешь историю в баре

Напиши пост с острой шуткой про жизнь в Азии.

Структура:
1. Жизненная ситуация
2. Острая шутка (в стиле @Maddysontg)
3. Развитие ситуации
4. Ещё одна шутка или ироничный вывод

Требования:
- 700-900 символов
- Мат 1-3 раза
- 2-3 шутки, одна из них острая
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
    
    incomplete_adverbs = ['тогда', 'потом', 'сейчас', 'здесь', 'там', 'тут', 'вчера', 'сегодня', 'завтра', 'всегда', 'никогда', 'иногда', 'уже', 'ещё', 'просто', 'даже', 'почти', 'совсем', 'очень', 'слишком', 'также', 'тоже']
    
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

def validate_caption(text: str, min_length: int = 700, max_length: int = 1023) -> Tuple[str, Optional[str]]:
    if not text:
        return '', 'Текст пустой'
    
    text = clean_text(text)
    
    if len(text) < 10:
        return '', 'Слишком короткий'
    
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
    
    if len(text) < min_length:
        if len(all_sentences) < 2:
            return '', f'Слишком короткий ({len(text)} символов)'
    
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

# ===== ПРОДОЛЖЕНИЕ ОБРЕЗАННОГО ТЕКСТА =====

def request_continuation(previous_text: str) -> str:
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
                {"role": "user", "content": f"Вот текст, который оборвался
