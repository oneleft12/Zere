# Контекст для архитектора — ZERE

## Обзор

**ZERE** — персональный AI-ассистент для Windows на C# (.NET 10).  
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

### 4. Plugin Pattern (Плагинная система)
Разные реализации одного функционала загружаются как плагины:
- **IPlugin** — базовый интерфейс
- **IPersonalityPlugin** — плагины личности (System Prompt + параметры)
- **ICommandHandlerPlugin** — плагины обработчиков команд
- Внешние плагины загружаются из `./plugins/*.dll`
- Встроенные плагины загружаются из сборки

---

## Межпроектные зависимости

```
ZERE.App
  └── ZERE.Core
        ├── ZERE.AI
        ├── ZERE.Memory
        ├── ZERE.Tools
        │     ├── Applications
        │     ├── Files
        │     ├── Gaming
        │     ├── Windows
        │     └── System
        └── ZERE.Voice
              ├── Whisper (STT)
              └── Piper (TTS)

ZERE.Core/Plugins/
  ├── Interfaces/
  │   ├── IPlugin.cs
  │   ├── IPersonalityPlugin.cs
  │   └── ICommandHandlerPlugin.cs
  ├── BasePlugin.cs
  ├── PluginManager.cs
  ├── PluginConfig.cs
  ├── BuiltIn/
  │   └── Personality/
  │       └── PersonalityPlugin.cs
  └── Settings/
      └── SettingsMenu.cs

./plugins/  (внешние плагины)
  └── *.dll
```

---

## Точки расширения

### Добавить новый обработчик:
1. Создать класс в `ZERE.Core/Handlers/`
2. Реализовать `IZereHandler`
3. Зарегистрировать в `ZereEngine.cs` (pipeline)

### Добавить новый тип команды:
1. Добавить значение в enum `*CommandType`
2. Обновить `*CommandRouter.Parse()`
3. Обработать в switch-case обработчика

### Добавить новый инструмент:
1. Создать класс в `ZERE.Tools/`
2. Вызвать из соответствующего обработчика

### Добавить плагин личности:
1. Создать .dll проект
2. Реализовать `IPersonalityPlugin`
3. Положить .dll в `./plugins/`
4. Перезагрузить плагины через настройки

### Добавить плагин обработчика команд:
1. Создать .dll проект
2. Реализовать `ICommandHandlerPlugin`
3. Положить .dll в `./plugins/`
4. Плагин автоматически добавится в pipeline

---

## Ключевые интерфейсы

```csharp
// Интерфейс обработчика
public interface IZereHandler
{
    bool CanHandle(string message);
    Task<string> HandleAsync(string message);
}

// Интерфейс плагина
public interface IPlugin
{
    string Id { get; }
    string Name { get; }
    string Description { get; }
    string Version { get; }
    PluginType Type { get; }
    void Initialize();
    void Dispose();
}

// Интерфейс плагина личности
public interface IPersonalityPlugin : IPlugin
{
    string SystemPrompt { get; }
    float Temperature { get; }
    PersonalityStyle Style { get; }
    string[] GetAvailableStyles();
    void SetStyle(string styleName);
}

// Интерфейс плагина обработчика команд
public interface ICommandHandlerPlugin : IPlugin
{
    string[] SupportedCommands { get; }
    bool CanHandle(string message);
    Task<string> HandleAsync(string message);
}
```

---

## Конфигурация

### config/config.json
- `model` — имя модели Ollama
- `voice.enabled` — включён ли голос
- `autoMemory` — автоизвлечение фактов
- `debugMode` — подробные логи

### config/plugins.json
- `ActivePersonalityId` — ID активного плагина личности
- `PluginSettings` — пользовательские настройки плагинов

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
{ "userMessage": "привет", "zereResponse": "Здравствуйте!", "timestamp": "..." }
```

---

## Рекомендации по развитию

1. **Web-панель** — HTTP-интерфейс для настроек (план: `docs/WEB_PANEL_PLAN.md`)
2. **API** — REST API для интеграции с другими приложениями
3. **Мультиязычность** — переключение языка интерфейса
4. **Голос** — режим всегда слушающего (wake word detection)
5. **GUI** — WPF/MAUI оболочка вместо консоли
