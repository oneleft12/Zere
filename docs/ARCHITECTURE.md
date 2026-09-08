# Контекст для архитектора — JARVIS

## Обзор

**JARVIS** — персональный AI-ассистент для Windows на C# (.NET 10).  
Консольное приложение, работает с локальной LLM (Ollama), управляет компьютером через текстовые команды.

---

## Архитектурные паттерны

### 1. Pipeline Pattern (Цепочка обработчиков)
Каждая команда пользователя проходит через список обработчиков. Первый, кто вернул `true` в `CanHandle()`, обрабатывает команду.

```
User Input → MemoryHandler → MemoryQueryHandler → ConversationHandler 
         → ProcessHandler → WindowsHandler → FileHandler 
         → GameHandler → VolumeHandler → AIHandler (fallback)
```

### 2. Router Pattern (Маршрутизация)
Внутри обработчиков команды парсятся через `*CommandRouter` классы:
- `WindowsCommandRouter` → `WindowsCommandType` (Shutdown, Restart, Sleep)
- `FileCommandRouter` → `FileCommandType` (CreateFolder, CreateFile, FindFile, DeleteFile)
- `ProcessCommandRouter` → `ProcessCommandType` (List, Search, Kill)
- `VolumeCommandRouter` → `VolumeCommandType` (SetVolume, VolumeUp, VolumeDown, Mute, UnMute)

### 3. Repository Pattern (Доступ к данным)
SQLite база через репозитории:
- `MemoryRepository` — CRUD для воспоминаний (Key-Value)
- `ConversationRepository` — история диалогов

---

## Межпроектные зависимости

```
JARVIS.App
  └── JARVIS.Core
        ├── JARVIS.AI
        ├── JARVIS.Memory
        ├── JARVIS.Tools
        │     ├── Applications
        │     ├── Files
        │     ├── Gaming
        │     ├── Windows
        │     └── System
        └── JARVIS.Voice
              ├── Whisper (STT)
              └── Piper (TTS)
```

---

## Точки расширения

### Добавить новый обработчик:
1. Создать класс в `JARVIS.Core/Handlers/`
2. Реализовать `IJarvisHandler`
3. Зарегистрировать в `JarvisEngine.cs` (ipeline)

### Добавить новый тип команды:
1. Добавить значение в enum `*CommandType`
2. Обновить `*CommandRouter.Parse()`
3. Обработать в switch-case обработчика

### Добавить новый инструмент:
1. Создать класс в `JARVIS.Tools/`
2. Вызвать из соответствующего обработчика

---

## Ключевые интерфейсы

```csharp
// Единственный интерфейс обработчика
public interface IJarvisHandler
{
    bool CanHandle(string message);
    Task<string> HandleAsync(string message);
}
```

---

## Конфигурация

Все настройки в `config/config.json`:
- `model` — имя модели Ollama
- `voice.enabled` — включён ли голос
- `autoMemory` — автоизвлечение фактов
- `debugMode` — подробные логи

---

## Внешние зависимости

| Компонент | Зависимость | Назначение |
|---|---|---|
| Ollama | HTTP localhost:11434 | Генерация ответов LLM |
| SQLite | Microsoft.Data.Sqlite | Хранение данных |
| Whisper | ggml-base.bin | Распознавание речи |
| Piper | .onnx модели | Синтез речи |

---

## Паттерны данных

### Memory (воспоминания)
```json
{ "key": "имя", "value": "Dan", "category": "User" }
```

### Conversation (история)
```json
{ "userMessage": "привет", "jarvisResponse": "Здравствуйте!", "timestamp": "..." }
```

---

## Рекомендации по развитию

1. **Интерфейс** — добавить WPF/MAUI оболочку вместо консоли
2. **Плагины** — загрузка .dll из папки `plugins/`
3. **API** — REST API для интеграции с другими приложениями
4. **Мультиязычность** — переключение языка интерфейса
5. **Голос** — режим всегда слушающего (wake word detection)
