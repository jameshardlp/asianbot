def generate_caption_with_gemini() -> str:
    """
    Генерирует описание через Google Gemini 2.0 Flash
    """
    print(f"🔑 Ключ Gemini: {'✅ задан' if GEMINI_KEY else '❌ НЕ ЗАДАН'}")
    
    if not GEMINI_KEY:
        print("⚠️ GEMINI_KEY не задан, использую резерв")
        return get_fallback_caption()
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}"
        
        prompt = """Напиши короткое, романтичное и красивое описание (на русском языке) для фотографии азиатской девушки.

Примеры стиля:
- "🌸 Японская весна. Нежность и изящество сакуры в каждом взгляде."
- "💫 K-Beauty. Сияние, которое невозможно не заметить."
- "🏮 Шанхай. Огонь и элегантность в каждом движении."

Требования:
- 1-2 предложения
- Романтичный и поэтичный стиль
- Упоминание восточной культуры (Япония, Корея, Китай)
- Без кавычек и лишних слов

Напиши ТОЛЬКО описание."""

        data = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }
        
        headers = {"Content-Type": "application/json"}
        
        print("🔄 Генерация описания через Gemini 2.0 Flash...")
        
        max_retries = 3
        for attempt in range(max_retries):
            response = requests.post(url, headers=headers, json=data, timeout=20)
            
            if response.status_code == 429:
                wait_time = (attempt + 1) * 5  # 5, 10, 15 секунд
                print(f"⚠️ Ошибка 429 (лимит запросов). Попытка {attempt+1}/{max_retries}, ждём {wait_time} сек...")
                time.sleep(wait_time)
                continue
            
            break
        
        print(f"📊 Статус ответа: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ Gemini ошибка: {response.status_code}")
            print(f"📄 Текст ответа: {response.text[:200]}")
            return get_fallback_caption()
        
        try:
            result = response.json()
        except json.JSONDecodeError as e:
            print(f"❌ Ошибка парсинга JSON: {e}")
            return get_fallback_caption()
        
        if "candidates" in result and len(result["candidates"]) > 0:
            caption = result["candidates"][0]["content"]["parts"][0]["text"].strip()
            caption = caption.strip('"').strip("'")
            
            tags = ["🇯🇵 Япония", "🇰🇷 Корея", "🇨🇳 Китай", "🇹🇭 Таиланд"]
            tag = random.choice(tags)
            
            print(f"✅ Сгенерировано: {caption[:50]}...")
            return f"{caption}\n\n{tag} 📸"
        else:
            print("❌ Нет candidates в ответе")
            return get_fallback_caption()
            
    except Exception as e:
        print(f"❌ Ошибка генерации: {e}")
        return get_fallback_caption()
