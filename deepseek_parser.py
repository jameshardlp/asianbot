# ===== deepseek_parser.py =====
"""
Модуль для работы с DeepSeek API и парсинга контента
"""
import os
import re
import json
import time
import random
import hashlib
import requests
import logging
import base64
import asyncio
from typing import Optional, Tuple, List, Dict, Any
from urllib.parse import quote
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ===== КОНФИГУРАЦИЯ =====
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = "deepseek-chat"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
MIN_DATE = datetime(2026, 1, 1)

# ===== КЭШ ПОСТОВ =====
last_posts = []
_system_prompt_cache = {}

# ===== ИНФОРМАЦИЯ О СТРИМЕРАХ =====
STREAMER_INFO = {
    'voodoosh': {
        'name': 'Вудуш', 'gender': 'male', 'nominative': 'Вудуш',
        'genitive': 'Вудуша', 'dative': 'Вудушу', 'accusative': 'Вудуша',
        'instrumental': 'Вудушем', 'prepositional': 'Вудуше',
        'pronoun': 'он', 'possessive': 'его',
        'verb_past_male': 'сделал', 'verb_past_female': 'сделала',
        'verb_present': 'делает', 'verb_future': 'сделает',
        'display_name': 'Вудуш'
    },
    'praden': {
        'name': 'Праден', 'gender': 'male', 'nominative': 'Праден',
        'genitive': 'Прадена', 'dative': 'Прадену', 'accusative': 'Прадена',
        'instrumental': 'Праденом', 'prepositional': 'Прадене',
        'pronoun': 'он', 'possessive': 'его',
        'verb_past_male': 'сделал', 'verb_past_female': 'сделала',
        'verb_present': 'делает', 'verb_future': 'сделает',
        'display_name': 'Праден'
    },
    'bratishkinoff': {
        'name': 'Братишкин', 'gender': 'male', 'nominative': 'Братишкин',
        'genitive': 'Братишкина', 'dative': 'Братишкину', 'accusative': 'Братишкина',
        'instrumental': 'Братишкиным', 'prepositional': 'Братишкине',
        'pronoun': 'он', 'possessive': 'его',
        'verb_past_male': 'сделал', 'verb_past_female': 'сделала',
        'verb_present': 'делает', 'verb_future': 'сделает',
        'display_name': 'Братишкин'
    },
    'sasavot': {
        'name': 'Сасавот', 'gender': 'male', 'nominative': 'Сасавот',
        'genitive': 'Сасавота', 'dative': 'Сасавоту', 'accusative': 'Сасавота',
        'instrumental': 'Сасавотом', 'prepositional': 'Сасавоте',
        'pronoun': 'он', 'possessive': 'его',
        'verb_past_male': 'сделал', 'verb_past_female': 'сделала',
        'verb_present': 'делает', 'verb_future': 'сделает',
        'display_name': 'Сасавот'
    },
    'alina_rin': {
        'name': 'Алина Рин', 'gender': 'female', 'nominative': 'Алина Рин',
        'genitive': 'Алины Рин', 'dative': 'Алине Рин', 'accusative': 'Алину Рин',
        'instrumental': 'Алиной Рин', 'prepositional': 'Алине Рин',
        'pronoun': 'она', 'possessive': 'её',
        'verb_past_male': 'сделал', 'verb_past_female': 'сделала',
        'verb_present': 'делает', 'verb_future': 'сделает',
        'display_name': 'Алина Рин'
    },
    'lasqa': {
        'name': 'Ласка', 'gender': 'male', 'nominative': 'Ласка',
        'genitive': 'Ласки', 'dative': 'Ласке', 'accusative': 'Ласку',
        'instrumental': 'Лаской', 'prepositional': 'Ласке',
        'pronoun': 'он', 'possessive': 'его',
        'verb_past_male': 'сделал', 'verb_past_female': 'сделала',
        'verb_present': 'делает', 'verb_future': 'сделает',
        'display_name': 'Ласка'
    },
    'arrowwoods': {
        'name': 'Аравудус', 'gender': 'male', 'nominative': 'Аравудус',
        'genitive': 'Аравудуса', 'dative': 'Аравудусу', 'accusative': 'Аравудуса',
        'instrumental': 'Аравудусом', 'prepositional': 'Аравудусе',
        'pronoun': 'он', 'possessive': 'его',
        'verb_past_male': 'сделал', 'verb_past_female': 'сделала',
        'verb_present': 'делает', 'verb_future': 'сделает',
        'display_name': 'Аравудус'
    },
    'evelone': {
        'name': 'Эвелон', 'gender': 'male', 'nominative': 'Эвелон',
        'genitive': 'Эвелона', 'dative': 'Эвелону', 'accusative': 'Эвелона',
        'instrumental': 'Эвелоном', 'prepositional': 'Эвелоне',
        'pronoun': 'он', 'possessive': 'его',
        'verb_past_male': 'сделал', 'verb_past_female': 'сделала',
        'verb_present': 'делает', 'verb_future': 'сделает',
        'display_name': 'Эвелон'
    },
    'buster': {
        'name': 'Бустер', 'gender': 'male', 'nominative': 'Бустер',
        'genitive': 'Бустера', 'dative': 'Бустеру', 'accusative': 'Бустера',
        'instrumental': 'Бустером', 'prepositional': 'Бустере',
        'pronoun': 'он', 'possessive': 'его',
        'verb_past_male': 'сделал', 'verb_past_female': 'сделала',
        'verb_present': 'делает', 'verb_future': 'сделает',
        'display_name': 'Бустер'
    }
}

# ===== ПРОМПТЫ =====
style_prompts = {
    'streamer': """
Ты — уставший мужик лет 35-40, работяга. Сидишь вечером с пивом, смотришь стримеров и ржешь с них. Твой стиль — как в гараже с мужиками: грубо, с матом, но с юмором.

Напиши пост про стримера/стримеров. Пост должен быть живым, эмоциональным, с реальными историями и наблюдениями.

⚠️ ПРАВИЛА ИСПОЛЬЗОВАНИЯ ПАДЕЖЕЙ (ЭТО ВАЖНО!):
- Вудуш: у Вудуша, Вудушу, Вудушем, о Вудуше
- Праден: у Прадена, Прадену, Праденом, о Прадене
- Братишкин: у Братишкина, Братишкину, Братишкиным, о Братишкине
- Сасавот: у Сасавота, Сасавоту, Сасавотом, о Сасавоте
- Алина Рин: у Алины Рин, Алине Рин, Алиной Рин, об Алине Рин (ОНА!)
- Ласка: у Ласки, Ласке, Лаской, о Ласке
- Аравудус: у Аравудуса, Аравудусу, Аравудусом, о Аравудусе
- Эвелон: у Эвелона, Эвелону, Эвелоном, о Эвелоне
- Бустер: у Бустера, Бустеру, Бустером, о Бустере

Требования:
- Пиши пост любого размера, но сохраняй логику и смысл
- Мат 2-5 раз
- Обязательно используй 1-2 локальных мема про стримера
- Используй правильные падежи!
- Острые шутки с юмором
- Используй "так называемый/ая/ые" с иронией
- Не называй своё имя
- Обращайся к читателям на "вы"
""",
    'asia': """
Ты — уставший мужик, работяга. Иногда вспоминаешь про Азию, где всё по-другому. Напиши пост про Азию с юмором и самоиронией.

Требования:
- Пиши пост любого размера, но сохраняй логику и смысл
- Мат 1-2 раза
- Острая шутка с юмором
- Используй "так называемый/ая/ые" с иронией
- Не называй своё имя
- Обращайся к читателям на "вы"
""",
}

# ===== КЛЮЧЕВЫЕ СЛОВА ДЛЯ ПОИСКА =====
STREAMER_QUERIES = {
    'voodoosh': [
        "вудуш на стриме", "voodoosh стрим", "вудуш стример", 
        "вудуш лицо", "voodoosh stream", "вудуш фото"
    ],
    'praden': [
        "праден на стриме", "praden стрим", "праден стример",
        "праден лицо", "praden stream", "праден фото"
    ],
    'bratishkinoff': [
        "братишкин на стриме", "bratishkinoff стрим", "братишкин стример",
        "братишкин лицо", "bratishkinoff stream", "вова братишкин"
    ],
    'sasavot': [
        "сасавот на стриме", "sasavot стрим", "сасавот стример",
        "сасавот лицо", "sasavot stream", "сасавот фото"
    ],
    'alina_rin': [
        "алина рин на стриме", "alina rin стрим", "алина рин стример",
        "алина рин лицо", "alina rin stream", "алина рин фото"
    ],
    'lasqa': [
        "ласка на стриме", "lasqa стрим", "ласка стример",
        "ласка лицо", "lasqa stream", "ласка фото"
    ],
    'arrowwoods': [
        "аравудус на стриме", "arrowwoods стрим", "аравудус стример",
        "аравудус лицо", "arrowwoods stream", "аравудус фото"
    ],
    'evelone': [
        "эвелон на стриме", "evelone стрим", "эвелон стример",
        "эвелон лицо", "evelone stream", "эвелон фото"
    ],
    'buster': [
        "бустер на стриме", "buster стрим", "бустер стример",
        "бустер лицо", "buster stream", "бустер фото"
    ],
}

ASIAN_QUERIES = [
    "japanese girl friend photo casual",
    "korean girl natural shot street",
    "thai girl friend photo outside",
    "vietnamese woman friend photo",
    "asian girl laughing with friend",
    "asian woman talking to friend",
    "asian girl walking with friend",
]

ASIAN_KEYWORDS = [
    'asian', 'japanese', 'korean', 'chinese', 'thai', 'vietnamese',
    'filipino', 'indonesian', 'malaysian', 'singaporean', 'taiwanese',
    'mongolian', 'burmese', 'cambodian', 'laotian', 'east asian',
    'south east asian', 'oriental', 'asia girl', 'asia woman',
    'japan', 'korea', 'china', 'thailand', 'vietnam', 'philippines',
]

NON_ASIAN_KEYWORDS = [
    'african', 'black', 'white', 'caucasian', 'european', 'american',
    'latina', 'mexican', 'brazilian', 'indian', 'middle eastern',
    'arab', 'persian', 'turkish', 'russian', 'ukrainian', 'polish',
]

ASIAN_NAMES = [
    'yuki', 'haruka', 'sakura', 'ai', 'miyu', 'rina', 'mika', 'kaori',
    'hana', 'momoko', 'chihiro', 'nanami', 'hinata', 'yui', 'mizuki',
    'yeon', 'jiwoo', 'eunji', 'yuna', 'hyejin', 'sooyoung', 'jisoo',
]

AGE_POSITIVE_KEYWORDS = [
    '18', '19', '20', '21', '22', '23', '24', '25',
    '26', '27', '28', '29', '30',
    '18year', '19year', '20year', '21year', '22year',
    '18yo', '19yo', '20yo', '21yo', '22yo', '23yo',
    '20s', 'twenties', 'young', 'college', 'university',
    'student', 'freshman', 'sophomore', 'junior', 'senior',
]

CHILD_EXCLUDE_WORDS = [
    'child', 'children', 'kid', 'kids', 'baby', 'babies', 'toddler',
    'infant', 'preschool', 'kindergarten', 'schoolgirl', 'schoolboy',
    'girl scout', 'boy scout', 'cub scout', 'teen', 'teenager',
    'minor', 'underage', 'little girl', 'little boy', 'young girl',
    'young boy', 'daughter', 'son', 'family', 'family photo',
    'childhood', 'baby girl', 'baby boy', 'newborn', 'cute baby',
    'child model', 'kid model', 'baby model', 'toddler girl', 'toddler boy',
]

MEN_EXCLUDE_WORDS = [
    'man', 'men', 'boy', 'male', 'guy', 'dude', 'brother',
    'father', 'husband', 'boyfriend', 'gentleman', 'sir',
    'bloke', 'chap', 'fellow', 'lad', 'young man',
]

TRADITIONAL_EXCLUDE = [
    'kimono', 'hanbok', 'cheongsam', 'qi pao', 'sari', 'ao dai',
    'traditional', 'folk costume', 'national dress', 'hanfu',
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
    if len(words) < 2:
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
    if last_word in incomplete_adverbs and len(words) < 5:
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
    if len(clean) > 20:
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

def clean_text(text: str) -> str:
    if not text:
        return ''
    text = text.replace('—', '-').replace('–', '-')
    text = text.replace('@maddysontg', '').replace('@Maddysontg', '').replace('@MADDYSONTG', '')
    text = text.replace('maddysontg', '').replace('Maddysontg', '').replace('MADDYSONTG', '')
    text = re.sub(r'\s+', ' ', text).strip()
    text = clean_punctuation(text)
    return text

def validate_caption(text: str, max_length: int = 1023) -> Tuple[str, Optional[str]]:
    if not text:
        return '', 'Текст пустой'
    text = clean_text(text)
    if len(text) < 10:
        return '', 'Слишком короткий (меньше 10 символов)'
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
        if word_count < 2:
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
    return text, None

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
        if len(key) > 10 and same_chars / len(key) > 0.70:
            return True
    return False

# ===== ФУНКЦИИ ПРОВЕРКИ ДАТЫ =====

def parse_date_from_text(text: str) -> Optional[datetime]:
    if not text:
        return None
    
    date_patterns = [
        r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})',
        r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})',
        r'(\d{1,2})\s+(янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)\s+(\d{4})',
        r'(\d{4})\s+год',
        r'(\d{2})\.(\d{2})\.(\d{4})',
    ]
    
    months_map = {
        'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4, 'май': 5, 'июн': 6,
        'июл': 7, 'авг': 8, 'сен': 9, 'окт': 10, 'ноя': 11, 'дек': 12
    }
    
    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            groups = match.groups()
            try:
                if len(groups) == 3:
                    if groups[0].isdigit() and len(groups[0]) == 4:
                        year = int(groups[0])
                        month = int(groups[1])
                        day = int(groups[2])
                    elif groups[2].isdigit() and len(groups[2]) == 4:
                        day = int(groups[0])
                        month = int(groups[1])
                        year = int(groups[2])
                    elif groups[1].lower() in months_map:
                        day = int(groups[0])
                        month = months_map[groups[1].lower()]
                        year = int(groups[2])
                    else:
                        continue
                    
                    if 2000 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                        return datetime(year, month, day)
            except (ValueError, IndexError):
                continue
    
    return None

def check_date_in_content(content: str, url: str = "") -> bool:
    text_to_check = content
    if url:
        text_to_check = f"{text_to_check} {url}"
    
    date = parse_date_from_text(text_to_check)
    if date:
        return date >= MIN_DATE
    
    old_keywords = [
        '2019', '2020', '2021', '2022', '2023', '2024', '2025',
        'ретро', 'старый', 'архив', 'давно', 'год назад',
        'old', 'archive', 'classic', 'vintage', 'retro',
    ]
    
    text_lower = text_to_check.lower()
    for keyword in old_keywords:
        if keyword in text_lower:
            if keyword in ['2019', '2020', '2021', '2022', '2023', '2024', '2025']:
                return False
            if keyword in ['старый', 'архив', 'давно', 'ретро']:
                return False
    
    return True

# ===== ФУНКЦИИ DEEPSEEK API =====

def get_system_prompt() -> str:
    cache_key = "system_prompt_v4"
    if cache_key not in _system_prompt_cache:
        _system_prompt_cache[cache_key] = """Ты — уставший мужик лет 35-40, работяга. Сидишь вечером с пивом, смотришь стримеров и ржешь с них.

⚠️ ПРАВИЛА РУССКОГО ЯЗЫКА:
1. Все стримеры (кроме Алины Рин) — МУЖСКОГО РОДА. Используй: он, его, ему, им, нём.
2. Алина Рин — ЖЕНСКОГО РОДА. Используй: она, её, ей, ей, ней.
3. Падежи для мужских имён:
   - Вудуш → у Вудуша, Вудушу, Вудушем, о Вудуше
   - Праден → у Прадена, Прадену, Праденом, о Прадене
   - Братишкин → у Братишкина, Братишкину, Братишкиным, о Братишкине
   - Сасавот → у Сасавота, Сасавоту, Сасавотом, о Сасавоте
   - Ласка → у Ласки, Ласке, Лаской, о Ласке
   - Аравудус → у Аравудуса, Аравудусу, Аравудусом, о Аравудусе
   - Эвелон → у Эвелона, Эвелону, Эвелоном, о Эвелоне
   - Бустер → у Бустера, Бустеру, Бустером, о Бустере
4. Падежи для женских имён:
   - Алина Рин → у Алины Рин, Алине Рин, Алиной Рин, об Алине Рин

Отвечай ТОЛЬКО готовым постом. БЕЗ РАССУЖДЕНИЙ."""
        logger.info("💾 Системный промпт закэширован")
    return _system_prompt_cache[cache_key]

def get_style_prompt(style: str, streamer_key: str = None) -> str:
    cache_key = f"style_prompt_{style}_{streamer_key}"
    
    if cache_key not in _system_prompt_cache:
        base_prompt = style_prompts.get(style, style_prompts['streamer'])
        
        if streamer_key and streamer_key in STREAMER_INFO:
            info = STREAMER_INFO[streamer_key]
            name = info['name']
            pronoun = info['pronoun']
            genitive = info['genitive']
            dative = info['dative']
            accusative = info['accusative']
            instrumental = info['instrumental']
            prepositional = info['prepositional']
            
            gender_hint = f"""
⚠️ ВАЖНО! СТРИМЕР {name} — {pronoun.upper()}

Правильные падежи для {name}:
- Именительный: {name}
- Родительный: {genitive}
- Дательный: {dative}
- Винительный: {accusative}
- Творительный: {instrumental}
- Предложный: {prepositional}
"""
            _system_prompt_cache[cache_key] = gender_hint + base_prompt + """

⚠️ ВАЖНО: Пиши строго по теме. Без рассуждений. Только готовый пост.
Твой ответ (ТОЛЬКО ПОСТ, БЕЗ РАССУЖДЕНИЙ):"""
        else:
            _system_prompt_cache[cache_key] = base_prompt + """

⚠️ ВАЖНО: Пиши строго по теме. Без рассуждений. Только готовый пост.
Твой ответ (ТОЛЬКО ПОСТ, БЕЗ РАССУЖДЕНИЙ):"""
        
        logger.info(f"💾 Промпт для стиля {style} закэширован")
    
    return _system_prompt_cache[cache_key]

def clear_prompt_cache():
    global _system_prompt_cache
    _system_prompt_cache.clear()
    logger.info("🗑️ Кэш промптов очищен")

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
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": "Ты уставший мужик. Текст поста был обрезан. Допиши ТОЛЬКО концовку — 1-3 завершающих предложения с логическим выводом. Не повторяй уже написанное. Только текст продолжения."},
                {"role": "user", "content": f"Вот текст, который оборвался:\n\n...{tail}\n\nДопиши концовку (1-3 предложения)."}
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

def validate_post_with_deepseek(post_text: str) -> Tuple[bool, str]:
    if not DEEPSEEK_API_KEY:
        logger.warning("⚠️ Нет DeepSeek API ключа для проверки поста")
        return True, post_text
    
    try:
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": """Ты — строгий модератор контента. Проверяй посты на соответствие правилам:

1. Пост должен быть о стримерах или Азии (по теме)
2. Допускается грубая лексика и мат (это стиль автора)
3. Не должно быть призывов к насилию или экстремизму
4. Пост должен быть грамотным
5. Пост должен быть завершённым

Если пост соответствует — напиши "APPROVED".
Если пост НЕ соответствует — напиши "REJECT: причина"."""},
                {"role": "user", "content": f"Проверь этот пост:\n\n{post_text}"}
            ],
            "temperature": 0.3,
            "max_tokens": 100,
        }
        
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=15
        )
        
        if response.status_code == 200:
            result = response.json()
            verdict = result["choices"][0]["message"]["content"].strip()
            
            if verdict.startswith("APPROVED"):
                logger.info("✅ Пост прошёл проверку DeepSeek")
                return True, post_text
            elif verdict.startswith("REJECT:"):
                reason = verdict.replace("REJECT:", "").strip()
                logger.warning(f"❌ Пост отклонён: {reason}")
                return False, reason
            else:
                logger.warning(f"⚠️ Неизвестный ответ DeepSeek: {verdict}")
                return True, post_text
        else:
            logger.error(f"❌ Ошибка проверки поста: {response.status_code}")
            return True, post_text
            
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке поста через DeepSeek: {e}")
        return True, post_text

def get_streamer_for_post() -> Tuple[str, str]:
    streamers = [
        ('voodoosh', 'Вудуш'), ('praden', 'Праден'), ('bratishkinoff', 'Братишкин'),
        ('sasavot', 'Сасавот'), ('alina_rin', 'Алина Рин'), ('lasqa', 'Ласка'),
        ('arrowwoods', 'Аравудус'), ('evelone', 'Эвелон'), ('buster', 'Бустер'),
    ]
    key, name = random.choice(streamers)
    return key, name

def generate_caption_with_validation() -> Tuple[str, Optional[str]]:
    logger.info("Генерирую уникальный пост с проверкой...")
    
    rand = random.random()
    if rand < 0.85:
        style = 'streamer'
        streamer_key, streamer_display = get_streamer_for_post()
        topic = f"стример {streamer_display}"
        logger.info(f"Генерация поста про {streamer_display}")
    else:
        style = 'asia'
        streamer_key = None
        streamer_display = None
        topic = "Азия"
        logger.info(f"Генерация поста про Азию")
    
    if not DEEPSEEK_API_KEY:
        logger.error("❌ Нет ключа DeepSeek API")
        return "Мне потребуется чуть больше времени на ответ, ожидайте.", streamer_key
    
    max_attempts = 20
    for attempt in range(max_attempts):
        try:
            logger.info(f"Попытка {attempt+1}/{max_attempts} для {topic}")
            
            base_prompt = get_style_prompt(style, streamer_key)
            
            streamer_topics = []
            if streamer_key and streamer_key in STREAMER_INFO:
                info = STREAMER_INFO[streamer_key]
                name = info['name']
                pronoun = info['pronoun']
                genitive = info['genitive']
                dative = info['dative']
                accusative = info['accusative']
                
                streamer_topics = [
                    f"Напиши живой пост про стримера {name}. Расскажи, как {pronoun} накручивает зрителей или тупит на стриме. Используй мат и юмор.",
                    f"Напиши пост про {name}. У {genitive} опять проблемы на стриме. Расскажи с юмором и матом.",
                    f"Напиши пост про скандал с {name}. Используй мат и чёрный юмор.",
                    f"Расскажи смешную историю про {name}. С юмором и матом.",
                    f"Напиши пост про то, как {name} накручивает зрителей. С юмором.",
                    f"У {genitive} опять проблемы со стримом. Напиши об этом с юмором.",
                    f"Смотрю на {accusative} и ржу. Расскажи почему.",
                    f"Сегодня {dative} снова не повезло. Расскажи об этом с матом.",
                ]
            else:
                streamer_topics = [
                    "Напиши живой пост про стримера. Критикуй его действия с юмором. Используй мат.",
                    "Напиши пост про стримера и его очередной провал на стриме. С юмором и матом.",
                ]
            
            asian_topics = [
                "Напиши пост про жизнь в Азии. С юмором и самоиронией.",
                "Напиши смешную историю из Азии. С юмором и матом.",
                "Напиши пост про азиатскую жизнь. С юмором.",
            ]
            
            if attempt % 2 == 0:
                current_prompt = base_prompt
            else:
                if style == 'streamer':
                    current_prompt = random.choice(streamer_topics) + "\n\n⚠️ Пиши строго по теме. Только пост без рассуждений."
                else:
                    current_prompt = random.choice(asian_topics) + "\n\n⚠️ Пиши строго по теме. Только пост без рассуждений."
                logger.info(f"Пробую альтернативный промпт #{attempt}")
            
            system_prompt = get_system_prompt()
            
            url = "https://api.deepseek.com/chat/completions"
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": current_prompt}
                ],
                "temperature": 1.1,  # Понижена температура до 1.1
                "max_tokens": 1500,
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=60)
            
            if response.status_code == 400:
                error_text = response.text.lower()
                if "извините" in error_text or "не могу" in error_text or "не разрешено" in error_text:
                    logger.warning(f"Контент заблокирован, пробую другой промпт...")
                    continue
                else:
                    logger.error(f"Ошибка 400: {response.text[:200]}")
                    continue
            
            if response.status_code != 200:
                logger.error(f"DeepSeek ошибка {response.status_code}: {response.text[:200]}")
                time.sleep(1)
                continue
            
            result = response.json()
            if not result.get("choices") or len(result["choices"]) == 0:
                logger.warning("Нет choices в ответе")
                continue
            
            choice = result["choices"][0]
            generated_content = choice.get("message", {}).get("content", "")
            finish_reason = choice.get("finish_reason", "")
            
            if not generated_content or len(generated_content.strip()) < 20:
                logger.warning("Пустой или короткий ответ")
                continue
            
            if finish_reason == "length":
                continuation = request_continuation(generated_content)
                if continuation:
                    generated_content = generated_content.rstrip() + " " + continuation.strip()
            
            caption = generated_content.strip().strip('"').strip("'")
            
            if not caption:
                continue
            
            if caption.lower().startswith(("мы должны", "нужно", "я должен", "напиши", "вот", "давайте", "попробуем", "извините", "к сожалению")):
                logger.warning("DeepSeek выдал рассуждение, пробуем другой промпт...")
                continue
            
            caption = clean_text(caption)
            caption = truncate_by_sentences(caption, max_length=1023)
            
            if len(caption) < 50:
                logger.warning(f"Слишком короткий ({len(caption)} символов)")
                continue
            
            validated, error = validate_caption(caption, max_length=1023)
            
            if not validated:
                logger.warning(f"Текст не прошёл проверку: {error}")
                continue
            
            approved, result = validate_post_with_deepseek(caption)
            
            if approved:
                logger.info(f"✅ Пост одобрен! (попытка {attempt+1})")
                add_to_last_posts(caption)
                return caption, streamer_key
            else:
                logger.warning(f"❌ Пост не прошёл проверку: {result}")
                continue
            
        except requests.exceptions.Timeout:
            logger.warning(f"Таймаут запроса (попытка {attempt+1})")
            continue
        except Exception as e:
            logger.error(f"Ошибка генерации (попытка {attempt+1}): {e}")
            continue
    
    logger.warning("⚠️ Все попытки генерации не удались")
    return "Мне потребуется чуть больше времени на ответ, ожидайте.", streamer_key

# ===== ФУНКЦИИ ПОИСКА ФОТО =====

def search_bing(query):
    """Поиск изображений через Bing Картинки"""
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
            clean_images.append(img)
        if clean_images:
            clean_images = list(dict.fromkeys(clean_images))
            return random.choice(clean_images)
        return None
    except Exception as e:
        logger.error(f"Ошибка Bing: {e}")
        return None

def search_google_direct(query):
    """Поиск изображений через Google Картинки"""
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
                        clean_images.append(img)
        clean_images = list(dict.fromkeys(clean_images))
        if clean_images:
            return random.choice(clean_images)
        return None
    except Exception as e:
        logger.error(f"Ошибка Google Картинки: {e}")
        return None

def search_yandex(query):
    """Поиск изображений через Яндекс Картинки"""
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
                        clean_images.append(img)
        clean_images = list(dict.fromkeys(clean_images))
        if clean_images:
            return random.choice(clean_images)
        return None
    except Exception as e:
        logger.error(f"Ошибка Яндекс Картинки: {e}")
        return None

def search_pexels(query):
    """Поиск изображений через Pexels API"""
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
                    if check_date_in_content("", url):
                        return url
        return None
    except Exception as e:
        logger.error(f"Ошибка Pexels: {e}")
        return None

def search_instagram(streamer_name: str, streamer_display: str) -> Optional[str]:
    """Поиск изображений через Instagram (через Google Картинки с site:instagram.com)"""
    try:
        queries = [
            f"{streamer_display} стрим",
            f"{streamer_display} стример",
            f"{streamer_display} фото",
            f"{streamer_display} лицо",
            f"@{streamer_name}",
        ]
        
        for query in queries[:3]:
            search_query = f"{query} site:instagram.com"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            }
            encoded_query = quote(search_query)
            url = f"https://www.google.com/search?q={encoded_query}&tbm=isch&safe=active"
            response = requests.get(url, headers=headers, timeout=15)
            
            pattern = r'imgurl=([^&]+)'
            images = re.findall(pattern, response.text)
            
            for img in images:
                img = img.replace('\\u0026', '&').replace('\\/', '/')
                if any(ext in img.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                    if 'instagram.com' in img.lower() or 'cdninstagram.com' in img.lower():
                        if not any(x in img.lower() for x in ['gstatic', 'google', 'favicon', 'logo']):
                            if check_date_in_content("", img):
                                logger.info(f"✅ Найдено фото из Instagram для {streamer_display}")
                                return img
        
        return None
    except Exception as e:
        logger.error(f"Ошибка поиска в Instagram: {e}")
        return None

def search_streamer_screenshot(streamer_key: str, streamer_display: str) -> Optional[str]:
    """Поиск скринов стримера со стримов"""
    queries = [
        f"{streamer_display} на стриме скрин",
        f"{streamer_display} стрим лицо",
        f"{streamer_display} стример лицо",
        f"{streamer_display} на стриме фото",
    ]
    
    random.shuffle(queries)
    
    search_functions = [
        (search_bing, "Bing Картинки"),
        (search_google_direct, "Google Картинки"),
        (search_yandex, "Яндекс Картинки"),
        (search_instagram, "Instagram"),
    ]
    random.shuffle(search_functions)
    
    for query in queries[:3]:
        for search_func, source_name in search_functions:
            try:
                logger.info(f"Поиск скрина для {streamer_display} в {source_name}: {query}")
                photo = search_func(query)
                if photo:
                    if check_date_in_content("", photo):
                        logger.info(f"✅ Найден скрин для {streamer_display}")
                        return photo
            except Exception as e:
                logger.error(f"Ошибка поиска скрина в {source_name}: {e}")
                continue
    
    return None

def search_youtube_clip(streamer_name: str, streamer_display: str) -> Optional[str]:
    """Поиск клипа стримера на YouTube"""
    if not YOUTUBE_API_KEY:
        logger.warning("⚠️ YouTube API ключ не настроен")
        return None
    
    try:
        search_queries = [
            f"{streamer_display} клип стрим",
            f"{streamer_display} момент стрим",
            f"{streamer_display} на стриме",
            f"{streamer_display} стрим",
        ]
        
        meme_queries = {
            'Вудуш': [f"{streamer_display} перезагрузка", f"{streamer_display} ладно я пошёл"],
            'Праден': [f"{streamer_display} проиграл", f"{streamer_display} обиделся"],
            'Братишкин': [f"{streamer_display} лысина", f"{streamer_display} качалка"],
            'Сасавот': [f"{streamer_display} смех", f"{streamer_display} засмеялся"],
            'Алина Рин': [f"{streamer_display} орёт", f"{streamer_display} эмоции"],
            'Ласка': [f"{streamer_display} забил", f"{streamer_display} сейчас"],
            'Аравудус': [f"{streamer_display} тильт", f"{streamer_display} проблемы"],
            'Эвелон': [f"{streamer_display} краш", f"{streamer_display} устал"],
            'Бустер': [f"{streamer_display} накрутил", f"{streamer_display} зрители"],
        }
        
        if streamer_display in meme_queries:
            search_queries.extend(meme_queries[streamer_display])
        
        random.shuffle(search_queries)
        
        for query in search_queries[:5]:
            url = "https://www.googleapis.com/youtube/v3/search"
            params = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "order": "relevance",
                "maxResults": 10,
                "videoDuration": "short",
                "key": YOUTUBE_API_KEY,
                "relevanceLanguage": "ru",
            }
            
            logger.info(f"🔍 Поиск клипа для {streamer_display}: {query}")
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("items") and len(data["items"]) > 0:
                    for item in data["items"]:
                        video_id = item["id"]["videoId"]
                        title = item["snippet"]["title"]
                        channel_title = item["snippet"]["channelTitle"]
                        description = item["snippet"].get("description", "")
                        published_at = item["snippet"].get("publishedAt", "")
                        
                        if published_at:
                            try:
                                pub_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                                if pub_date < MIN_DATE:
                                    logger.info(f"⏭️ Пропускаем видео от {pub_date.strftime('%Y-%m-%d')} (старше 2026 года)")
                                    continue
                            except:
                                pass
                        
                        combined_text = f"{title} {description} {channel_title}".lower()
                        streamer_names = [streamer_display.lower(), streamer_name.lower()]
                        
                        if streamer_display == "Эвелон":
                            streamer_names.extend(["evelon", "эвелон"])
                        elif streamer_display == "Братишкин":
                            streamer_names.extend(["bratishkin", "братишкин", "вова братишкин"])
                        elif streamer_display == "Вудуш":
                            streamer_names.extend(["voodoo", "voodoosh"])
                        elif streamer_display == "Праден":
                            streamer_names.extend(["praden"])
                        elif streamer_display == "Сасавот":
                            streamer_names.extend(["sasavot"])
                        elif streamer_display == "Алина Рин":
                            streamer_names.extend(["alina rin", "алина рин"])
                        elif streamer_display == "Ласка":
                            streamer_names.extend(["lasqa"])
                        elif streamer_display == "Аравудус":
                            streamer_names.extend(["arrowwoods"])
                        elif streamer_display == "Бустер":
                            streamer_names.extend(["buster"])
                        
                        has_streamer_name = any(name in combined_text for name in streamer_names)
                        
                        exclude_words = ['самолет', 'авиа', 'flight', 'plane', 'avalon', 'airport', 
                                       'автомобиль', 'car', 'auto', 'машина', 'игра', 'game']
                        has_exclude = any(word in combined_text for word in exclude_words)
                        
                        if not has_streamer_name or has_exclude:
                            logger.info(f"⏭️ Пропускаем видео: {title[:50]}... (не связано со стримером)")
                            continue
                        
                        if "подкаст" in title.lower() or "podcast" in title.lower():
                            continue
                        
                        video_url = f"https://www.youtube.com/watch?v={video_id}"
                        logger.info(f"✅ Найден клип для {streamer_display}: {title[:50]}...")
                        return video_url
            else:
                logger.error(f"❌ Ошибка YouTube API: {response.status_code}")
                continue
        
        return None
        
    except Exception as e:
        logger.error(f"❌ Ошибка поиска клипа: {e}")
        return None

def get_streamer_photo(streamer_name: str) -> Optional[str]:
    """Поиск фото стримера"""
    queries = STREAMER_QUERIES.get(streamer_name, [])
    if not queries:
        return None
    
    random.shuffle(queries)
    
    search_functions = [
        (search_bing, "Bing Картинки"),
        (search_google_direct, "Google Картинки"),
        (search_yandex, "Яндекс Картинки"),
    ]
    random.shuffle(search_functions)
    
    for query in queries:
        for search_func, source_name in search_functions:
            try:
                logger.info(f"Поиск фото для {streamer_name} в {source_name}: {query}")
                photo = search_func(query)
                if photo:
                    if check_date_in_content("", photo):
                        logger.info(f"✅ Найдено новое фото для {streamer_name}")
                        return photo
            except Exception as e:
                logger.error(f"Ошибка поиска для {streamer_name} в {source_name}: {e}")
                continue
    
    logger.warning(f"⚠️ Не найдено фото для {streamer_name}")
    return None

def get_streamer_media(streamer_key: str, streamer_display: str) -> Tuple[Optional[str], str]:
    """Получение медиа для стримера (клип или фото)"""
    logger.info(f"📹 Ищу клип для {streamer_display}...")
    clip = search_youtube_clip(streamer_key, streamer_display)
    if clip:
        return clip, 'clip'
    
    logger.info(f"🖼️ Клип не найден, ищу фото для {streamer_display}...")
    
    screenshot = search_streamer_screenshot(streamer_key, streamer_display)
    if screenshot:
        return screenshot, 'photo'
    
    photo = get_streamer_photo(streamer_key)
    if photo:
        return photo, 'photo'
    
    logger.warning(f"⚠️ Не найдено ни клипа, ни фото для {streamer_display}")
    return None, 'none'

# ===== ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С ФОТО =====

def encode_image_to_base64_url(image_url: str) -> str:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(image_url, headers=headers, timeout=10)
        if response.status_code == 200:
            return base64.b64encode(response.content).decode('utf-8')
        return None
    except Exception as e:
        logger.error(f"Ошибка загрузки картинки: {e}")
        return None

async def analyze_photo_for_comment(image_url: str) -> Optional[str]:
    if not DEEPSEEK_API_KEY:
        return None
    
    try:
        base64_image = encode_image_to_base64_url(image_url)
        if not base64_image:
            return None
        
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Коротко опиши что на фото. 1-2 предложения. Грубо, с юмором. Используй мат."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 150,
            "temperature": 1.1
        }
        
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            comment = result["choices"][0]["message"]["content"].strip()
            logger.info(f"🖼️ Комментарий к фото: {comment}")
            return comment
        return None
    except Exception as e:
        logger.error(f"Ошибка анализа фото: {e}")
        return None

async def get_random_photo(style: str = "streamer", streamer_key: str = None, history=None) -> Optional[str]:
    """Получает случайное фото с проверкой истории и даты"""
    if history is None:
        history = []
    
    if streamer_key:
        photo = get_streamer_photo(streamer_key)
        if photo and photo not in history:
            if check_date_in_content("", photo):
                return photo
        elif photo and photo in history:
            logger.info("⏭️ Фото уже использовалось")
            return None
    
    if style == 'streamer':
        streamers = ['voodoosh', 'praden', 'bratishkinoff', 'sasavot', 
                     'alina_rin', 'lasqa', 'arrowwoods', 'evelone', 'buster']
        random.shuffle(streamers)
        
        for streamer in streamers:
            photo = get_streamer_photo(streamer)
            if photo and photo not in history:
                if check_date_in_content("", photo):
                    return photo
        
        logger.warning("⚠️ Не найдены фото стримеров, пробую общий поиск")
        fallback_queries = ["russian streamer face", "twitch streamer russian", "streamer portrait"]
        random.shuffle(fallback_queries)
        
        search_functions = [
            (search_bing, "Bing Картинки"),
            (search_google_direct, "Google Картинки"),
            (search_yandex, "Яндекс Картинки"),
        ]
        random.shuffle(search_functions)
        
        for query in fallback_queries[:2]:
            for search_func, source_name in search_functions[:2]:
                try:
                    photo = search_func(query)
                    if photo and photo not in history:
                        if check_date_in_content("", photo):
                            return photo
                except Exception as e:
                    continue
    
    queries = ASIAN_QUERIES.copy()
    random.shuffle(queries)
    
    search_functions = [
        (search_bing, "Bing Картинки"),
        (search_google_direct, "Google Картинки"),
        (search_yandex, "Яндекс Картинки"),
        (search_pexels, "Pexels"),
    ]
    random.shuffle(search_functions)
    
    for query in queries[:3]:
        for search_func, source_name in search_functions[:2]:
            try:
                photo = search_func(query)
                if photo and photo not in history and is_photo_valid(photo):
                    if check_date_in_content("", photo):
                        return photo
            except Exception as e:
                continue
    
    logger.error("❌ Не удалось найти подходящее фото!")
    return None

def is_photo_valid(url: str) -> bool:
    if not url:
        return False
    if is_child_photo(url):
        return False
    if has_man_in_photo(url):
        return False
    if not is_asian_photo(url):
        return False
    if not is_age_appropriate(url):
        return False
    if is_traditional_clothing(url):
        return False
    unwanted = ['naked', 'nude', 'porn', 'xxx', 'sex', 'erotic', 'bikini']
    for word in unwanted:
        if word in url.lower():
            return False
    return True

def is_child_photo(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    for word in CHILD_EXCLUDE_WORDS:
        if word in url_lower:
            return True
    child_age_patterns = [
        r'\b(0|1|2|3|4|5|6|7|8|9|10|11|12|13|14|15|16|17)\b',
        r'\b(infant|toddler|child|kid|teen)\b',
        r'\b(grade|class|school)\s+[1-9]\b',
    ]
    for pattern in child_age_patterns:
        if re.search(pattern, url_lower, re.IGNORECASE):
            return True
    return False

def has_man_in_photo(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    for word in MEN_EXCLUDE_WORDS:
        if word in url_lower:
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
    if not url:
        return False
    url_lower = url.lower()
    if is_child_photo(url):
        return False
    for word in AGE_POSITIVE_KEYWORDS:
        if word in url_lower:
            return True
    if re.search(r'\b(age|years?|yo|y/o)\b', url_lower, re.IGNORECASE):
        for word in AGE_POSITIVE_KEYWORDS:
            if word in url_lower:
                return True
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
