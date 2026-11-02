"""YouTube и музыка: открыть сайт, включить трек, управлять плеером.

Два пути исполнения:

1. **Браузер ZERE (Playwright MCP).** Если плагин браузера включён, на
   странице выполняется короткий Playwright-код: поиск → первое видео →
   автовоспроизведение. Это единственный надёжный способ *включить* музыку:
   браузеры блокируют автозапуск со звуком без действия пользователя, а клик
   Playwright считается настоящим кликом.
2. **Браузер по умолчанию.** Плагин выключен или не запустился — открываем
   страницу YouTube (поиск) в обычном браузере. Музыку придётся включить
   вручную; об этом честно сказано в ответе.

Управление (пауза, следующий/предыдущий, «что играет») работает только через
первый путь: чужим браузером ZERE не управляет.
"""

from __future__ import annotations

import json
import os
import re
import webbrowser
from typing import Any, Callable, Optional, Protocol
from urllib.parse import quote_plus

from zere.core.logging.log_service import log_error
from zere.core.mcp.client import McpError, McpToolResult
from zere.tools.media.youtube_command import (
    DEFAULT_QUERY,
    NEXT,
    PAUSE,
    PREVIOUS,
    RESUME,
    STATUS,
)

YOUTUBE_URL = "https://www.youtube.com/"
SEARCH_URL = (
    "https://www.youtube.com/results?search_query={query}&sp=EgIQAQ%3D%3D"
)

#: Блок с результатом `browser_run_code_unsafe` в ответе Playwright MCP.
_RESULT_RE = re.compile(r"### Result\s*\n(.+?)(?:\n### |\Z)", re.DOTALL)
_ERROR_RE = re.compile(r"^###\s*Error\s*\n?", re.MULTILINE)


class CodeRunner(Protocol):
    """Драйвер браузера: выполняет Playwright-код на текущей странице."""

    @property
    def enabled(self) -> bool: ...

    def run_code(self, code: str) -> McpToolResult: ...


def open_in_browser(url: str) -> bool:
    """Открывает адрес браузером по умолчанию (True — получилось)."""
    try:
        if os.name == "nt":
            os.startfile(url)  # type: ignore[attr-defined]
            return True

        return webbrowser.open(url)
    except Exception as ex:  # noqa: BLE001 - нет браузера/ShellExecute
        log_error("YouTube", f"не удалось открыть {url}: {ex}")
        return False


def search_url(query: str) -> str:
    """Адрес поиска YouTube для запроса (кириллица и спецсимволы — в %-коды)."""
    return SEARCH_URL.format(query=quote_plus(query))


def _json_payload(result: McpToolResult) -> dict[str, Any]:
    """Достаёт JSON из ответа Playwright MCP.

    Сервер отвечает блоками `### Result` / `### Ran Playwright code`; нам
    нужен только первый. Если код вернул не объект или сервер прислал ошибку,
    отдаём словарь с `ok: False` и текстом причины.
    """
    text = result.text or ""

    if result.is_error:
        clean = _ERROR_RE.sub("", text).strip()
        return {"ok": False, "error": clean[:300]}

    match = _RESULT_RE.search(text)
    raw = match.group(1).strip() if match else text.strip()

    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {"ok": False, "error": raw[:300]}

    return payload if isinstance(payload, dict) else {"ok": False, "error": raw[:300]}


def _short(text: object, limit: int = 200) -> str:
    value = " ".join(str(text or "").split())

    return value[:limit].rstrip()


def _play_code(query: str) -> str:
    """Playwright-код: поиск → первое видео → микс → воспроизведение."""
    return (
        _PLAY_TEMPLATE.replace("__QUERY__", json.dumps(query, ensure_ascii=False))
    )


def _control_code(action: str) -> str:
    return _CONTROL_TEMPLATE.replace(
        "__ACTION__", json.dumps(action, ensure_ascii=False)
    )


_OPEN_CODE = """async (page) => {
  const out = { ok: false };
  try {
    await page.goto("https://www.youtube.com/", {
      waitUntil: "domcontentloaded",
      timeout: 45000,
    });
    out.ok = true;
    out.title = await page.title();
    out.url = page.url();
  } catch (error) {
    out.error = String(error).slice(0, 200);
  }
  return out;
}"""

_PLAY_TEMPLATE = """async (page) => {
  const query = __QUERY__;
  const out = { ok: false, stage: "search", query: query };
  try {
    await page.goto(
      "https://www.youtube.com/results?search_query=" +
        encodeURIComponent(query) +
        "&sp=EgIQAQ%3D%3D",
      { waitUntil: "domcontentloaded", timeout: 45000 }
    );
    await page.waitForTimeout(2200);

    const consent = page.locator(
      'button:has-text("Accept all"), button:has-text("Принять все")'
    );
    if (await consent.count()) {
      await consent.first().click().catch(() => {});
      await page.waitForTimeout(1500);
    }

    const links = page.locator('a#video-title[href*="/watch"]');
    const total = await links.count();
    let href = "";
    for (let i = 0; i < Math.min(total, 10); i++) {
      const value = await links.nth(i).getAttribute("href");
      if (value && value.includes("v=")) {
        href = value;
        break;
      }
    }
    if (!href) {
      out.stage = "no-results";
      return out;
    }

    const id = new URL("https://www.youtube.com" + href).searchParams.get("v");
    if (!id) {
      out.stage = "no-results";
      return out;
    }
    out.id = id;

    await page.goto(
      "https://www.youtube.com/watch?v=" + id +
        "&list=RD" + id + "&start_radio=1",
      { waitUntil: "domcontentloaded", timeout: 45000 }
    );
    await page.waitForTimeout(3500);
    out.stage = "watch";

    if (!(await page.locator("video").count())) {
      out.stage = "no-video";
      return out;
    }

    const isPaused = () => page.evaluate(() => {
      const video = document.querySelector("video");
      return video ? video.paused : null;
    });

    if (await isPaused()) {
      await page.locator(".ytp-play-button").click({ timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(1500);
    }

    out.paused = await isPaused();
    out.track = await page.evaluate(() => {
      const title = document.querySelector(
        "h1.ytd-watch-metadata yt-formatted-string, #title h1 yt-formatted-string"
      );
      return title ? title.innerText.trim().slice(0, 160) : "";
    });
    out.url = page.url();
    out.ok = out.paused === false;
    out.stage = out.ok ? "playing" : "not-playing";
    return out;
  } catch (error) {
    out.stage = "error";
    out.error = String(error).slice(0, 200);
    return out;
  }
}"""

_CONTROL_TEMPLATE = """async (page) => {
  const action = __ACTION__;
  const out = { ok: false, action: action, stage: "no-video" };
  try {
    if (!(await page.locator("video").count())) {
      return out;
    }
    out.stage = "video";

    const isPaused = () => page.evaluate(() => {
      const video = document.querySelector("video");
      return video ? video.paused : null;
    });
    const trackName = () => page.evaluate(() => {
      const title = document.querySelector(
        "h1.ytd-watch-metadata yt-formatted-string, #title h1 yt-formatted-string"
      );
      return title ? title.innerText.trim().slice(0, 160) : "";
    });

    if (action === "pause") {
      await page.evaluate(() => {
        const video = document.querySelector("video");
        if (video) video.pause();
      });
      out.paused = await isPaused();
      out.ok = out.paused === true;
    } else if (action === "resume") {
      if (await isPaused()) {
        await page.locator(".ytp-play-button")
          .click({ timeout: 5000 })
          .catch(() => {});
        await page.waitForTimeout(1500);
      }
      out.paused = await isPaused();
      out.ok = out.paused === false;
    } else if (action === "next" || action === "previous") {
      const selector =
        action === "next" ? ".ytp-next-button" : ".ytp-prev-button";
      const button = page.locator(selector);
      if (!(await button.count())) {
        out.stage = "no-button";
        return out;
      }
      await button.first().click({ timeout: 5000 });
      await page.waitForTimeout(2500);
      out.track = await trackName();
      out.paused = await isPaused();
      out.ok = out.paused === false;
    } else if (action === "status") {
      out.track = await trackName();
      out.paused = await isPaused();
      out.currentTime = await page.evaluate(() => {
        const video = document.querySelector("video");
        return video ? video.currentTime : null;
      });
      out.ok = true;
    }

    if (!out.track && action !== "status") {
      out.track = await trackName();
    }
    return out;
  } catch (error) {
    out.stage = "error";
    out.error = String(error).slice(0, 200);
    return out;
  }
}"""


class YouTubeService:
    """Команды YouTube: открыть, включить музыку, управлять воспроизведением."""

    def __init__(
        self,
        driver: Optional[CodeRunner] = None,
        open_url: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self._driver = driver
        self._open_url = open_url or open_in_browser

    # ── Публичные команды ───────────────────────────────────────────

    def open_youtube(self) -> str:
        """Открыть YouTube (в управляемом браузере или по умолчанию)."""
        if self._has_driver():
            try:
                payload = _json_payload(self._driver.run_code(_OPEN_CODE))
                if payload.get("ok"):
                    return "Открыл YouTube."
                log_error("YouTube", f"открытие: {payload.get('error', '')}")
            except Exception as ex:  # noqa: BLE001 - драйвер не должен ронять чат
                log_error("YouTube", f"открытие через Playwright: {ex}")

        if self._open_url(YOUTUBE_URL):
            return "Открыл YouTube в браузере по умолчанию."

        return "Не удалось открыть YouTube: браузер не найден."

    def play_music(self, query: str = "") -> str:
        """Найти видео по запросу и включить его (микс продолжит подбор)."""
        query = (query or "").strip() or DEFAULT_QUERY
        reason = ""

        if self._has_driver():
            try:
                payload = _json_payload(self._driver.run_code(_play_code(query)))
                answer = self._play_answer(payload, query)
                if answer is not None:
                    return answer
                reason = _short(payload.get("error") or payload.get("stage"))
            except McpError as ex:
                reason = _short(ex)
                log_error("YouTube", f"включение музыки: {ex}")
            except Exception as ex:  # noqa: BLE001
                reason = _short(ex)
                log_error("YouTube", f"включение музыки: {ex}")
        else:
            reason = "плагин браузера Playwright MCP выключен"

        if self._open_url(search_url(query)):
            suffix = f" ({reason})" if reason else ""
            return (
                f"Открыл YouTube с поиском «{query}». "
                f"Автовоспроизведение недоступно{suffix}."
            )

        return "Не удалось включить музыку: браузер недоступен."

    def control(self, action: str) -> str:
        """Пауза, продолжение, переключение трека и «что играет»."""
        if not self._has_driver():
            return (
                "Не могу управлять музыкой: браузером управляет плагин "
                "Playwright MCP, а он выключен."
            )

        try:
            payload = _json_payload(self._driver.run_code(_control_code(action)))
        except McpError as ex:
            return f"Не удалось управлять воспроизведением: {_short(ex)}."
        except Exception as ex:  # noqa: BLE001
            log_error("YouTube", f"управление {action}: {ex}")
            return f"Не удалось управлять воспроизведением: {_short(ex)}."

        return self._control_answer(action, payload)

    # ── Внутреннее ──────────────────────────────────────────────────

    def _has_driver(self) -> bool:
        return self._driver is not None and getattr(self._driver, "enabled", False)

    @staticmethod
    def _play_answer(payload: dict[str, Any], query: str) -> Optional[str]:
        """Ответ на включение музыки; `None` — не вышло, нужен откат."""
        stage = payload.get("stage")

        if payload.get("ok"):
            track = _short(payload.get("track") or payload.get("title"))
            return f"Включаю на YouTube: {track}." if track else "Включаю музыку на YouTube."

        if stage == "no-results":
            return f"На YouTube ничего не нашлось по запросу «{query}»."

        if stage == "no-video":
            return (
                f"Открыл видео по запросу «{query}», но плеер не появился. "
                "Попробуйте ещё раз."
            )

        if stage == "not-playing":
            return (
                f"Открыл видео по запросу «{query}», но воспроизведение не "
                "началось — нажмите Play в браузере."
            )

        return None

    @staticmethod
    def _control_answer(action: str, payload: dict[str, Any]) -> str:
        if not payload.get("ok"):
            stage = payload.get("stage")

            if stage == "no-video":
                return (
                    "Сейчас нечего менять: на странице YouTube нет видео. "
                    "Включите музыку командой «включи музыку»."
                )

            if stage == "no-button":
                return "У этого видео нет соседнего трека — включите микс."

            error = _short(payload.get("error"))

            return (
                f"Не удалось управлять воспроизведением: {error}."
                if error
                else "Не удалось управлять воспроизведением."
            )

        track = _short(payload.get("track"))
        paused = payload.get("paused")

        if action == PAUSE:
            return "Пауза." if paused else "Не удалось поставить на паузу."

        if action == RESUME:
            return "Продолжаю воспроизведение." if not paused else "Видео на паузе."

        if action == NEXT:
            return f"Следующий трек: {track}." if track else "Включаю следующий трек."

        if action == PREVIOUS:
            return f"Предыдущий трек: {track}." if track else "Включаю предыдущий трек."

        if action == STATUS:
            if not track:
                return "Сейчас ничего не играет."

            return (
                f"Сейчас на паузе: {track}."
                if paused
                else f"Сейчас играет: {track}."
            )

        return "Готово."


__all__ = [
    "YouTubeService",
    "CodeRunner",
    "open_in_browser",
    "search_url",
    "YOUTUBE_URL",
    "SEARCH_URL",
]
