# План: Web-панель настроек JARVIS

## Статус: ПЛАНИРОВАНИЕ

## Обзор
Веб-интерфейс для управления настройками JARVIS через браузер.
Локальный HTTP-сервер, открывается по адресу `http://localhost:8080`.

---

## Стек технологий

| Компонент | Технология |
|---|---|
| HTTP-сервер | `System.Net.HttpListener` (без доп. зависимостей) |
| Frontend | HTML + CSS + vanilla JS |
| API | JSON endpoints |
| Порт | 8080 (настраивается) |

---

## Структура

```
JARVIS.Web/
├── WebServer.cs           # HTTP-сервер
├── Api/
│   ├── SettingsApi.cs     # CRUD настроек
│   ├── PluginApi.cs       # Управление плагинами
│   └── PersonalityApi.cs  # Управление личностью
├── wwwroot/
│   ├── index.html         # Главная страница
│   ├── css/
│   │   └── style.css      # Стили
│   └── js/
│       └── app.js         # Клиентская логика
└── JARVIS.Web.csproj
```

---

## API Endpoints

### Настройки
- `GET /api/settings` — получить все настройки
- `POST /api/settings` — сохранить настройки

### Плагины
- `GET /api/plugins` — список плагинов
- `POST /api/plugins/reload` — перезагрузить плагины

### Личность
- `GET /api/personality` — текущая личность
- `GET /api/personality/styles` — доступные стили
- `POST /api/personality/set` — установить стиль

---

## UI Страницы

### 1. Главная (`/`)
- Текущая личность и стиль
- Быстрое переключение стиля
- Статус плагинов

### 2. Плагины (`/plugins`)
- Список загруженных плагинов
- Перезагрузка плагинов
- Информация о каждом плагине

### 3. Настройки (`/settings`)
- Конфигурация модели
- Язык
- Голос
- Debug режим

---

## Запуск

```csharp
// В Program.cs (опционально)
var webServer = new WebServer(jarvis.PluginManager, jarvis.Config);
_ = webServer.StartAsync(port: 8080);
Console.WriteLine("Web-панель: http://localhost:8080");
```

---

## Приоритет: НИЗКИЙ

Реализовать после стабилизации плагинной системы и консольной панели.
