"""Порт JARVIS.AI/OllamaClient.cs — синхронный клиент Ollama на requests.

Стриминг /api/generate разбирается построчно (NDJSON) через итератор iter_lines();
публичный generate() возвращает полный ответ строкой — как GenerateAsync в C#.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections import OrderedDict
from typing import Optional

import requests

from jarvis.ai.models.ollama_stream_chunk import OllamaStreamChunk
from jarvis.ai.ollama_url_resolver import OllamaUrlResolver
from jarvis.ai.system_prompt import SystemPrompt
from jarvis.core.logging.log_service import log_error

# Префиксы ответов, которые НЕ кэшируются (это тексты ошибок, не ответы модели)
_ERROR_PREFIXES = (
    "Не удалось подключиться",
    "Ollama не отвечает",
    "Ollama не найдена",
    "Ошибка AI",
    "Нет ответа",
)


class OllamaClient:
    """Аналог OllamaClient : IDisposable — вместо Dispose() метод close()."""

    def __init__(self, model: str = "qwen3.5:2b", timeout_minutes: int = 10) -> None:
        self._model = model
        # C#: _httpClient.Timeout = TimeSpan.FromMinutes(timeoutMinutes);
        # requests: единый таймаут (connect/read) в секундах.
        self._timeout: int = timeout_minutes * 60
        self._session = requests.Session()

        # Кэш ответов по хешу запроса (ROADMAP 1.3): prompt уже содержит
        # память/историю (PromptBuilder), поэтому идентичный prompt при
        # идентичных system/temperature/model → идентичный ответ.
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._cache_limit = 64

        self._resolved_url: Optional[str] = OllamaUrlResolver.resolve()

        if self._resolved_url is not None:
            if not self._resolved_url.endswith("/"):
                self._resolved_url += "/"
            # C#: _httpClient.BaseAddress = new Uri(_resolvedUrl);
            # в requests базовый адрес лишь хранится для сборки URL запроса.

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Аналог GenerateAsync(string prompt, string? systemPrompt = null, float? temperature = null)."""
        # Кэш раньше проверки URL: кэшированный ответ не требует Ollama
        # (кэш заполняется только успешными ответами, см. _store_in_cache).
        cache_key = self._make_cache_key(prompt, system_prompt, temperature)
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache.move_to_end(cache_key)
            return cached

        if self._resolved_url is None:
            return "Ollama не найдена. Запустите Ollama и перезапустите JARVIS."

        max_retries = 2
        attempt = 0

        # C#: for (int attempt = 0; ; attempt++)
        while True:
            try:
                effective_prompt = (
                    f"{system_prompt}\n\nПользователь: {prompt}"
                    if system_prompt is not None
                    else f"{SystemPrompt.Jarvis}\n\nПользователь: {prompt}"
                )

                request = {
                    "model": self._model,
                    "prompt": effective_prompt,
                    "stream": True,
                    # C#: options = temperature.HasValue ? new { temperature = temperature.Value } : null
                    "options": {"temperature": temperature} if temperature is not None else None,
                }

                # C#: new StringContent(JsonSerializer.Serialize(request), Encoding.UTF8, "application/json")
                body = json.dumps(request, separators=(",", ":"))
                headers = {"Content-Type": "application/json; charset=utf-8"}

                # C#: await _httpClient.PostAsync("/api/generate", content)
                response = self._session.post(
                    self._resolved_url + "api/generate",
                    data=body.encode("utf-8"),
                    headers=headers,
                    timeout=self._timeout,
                    stream=True,
                )
                try:
                    response.raise_for_status()  # C#: httpResponse.EnsureSuccessStatusCode()
                    result = self._read_stream(response)
                finally:
                    response.close()

                if not result or result.isspace():  # string.IsNullOrWhiteSpace(result)
                    print("[Ollama] Пустой ответ от модели.", file=sys.stderr)

                # C#: return IsNullOrWhiteSpace(result) ? "Нет ответа от модели." : result.Trim();
                if not result or result.isspace():
                    return "Нет ответа от модели."
                answer = result.strip()
                self._store_in_cache(cache_key, answer)
                return answer
            except requests.exceptions.Timeout:
                # C#: catch (TaskCanceledException) — таймаут HttpClient
                print(f"[Ollama] Таймаут при генерации. Модель: '{self._model}'", file=sys.stderr)
                log_error("OllamaClient", f"Таймаут генерации, модель '{self._model}'")
                return f"Ollama не отвечает (таймаут). Проверьте модель '{self._model}': ollama pull {self._model}"
            except (
                requests.exceptions.MissingSchema,
                requests.exceptions.InvalidSchema,
                requests.exceptions.InvalidURL,
            ) as ex:
                # C#: catch (InvalidOperationException) — неверный/отсутствующий адрес запроса
                print(f"[Ollama] Неверное состояние запроса: {ex}", file=sys.stderr)
                return f"Ошибка AI: {ex}"
            except requests.exceptions.RequestException as ex:
                # C#: catch (HttpRequestException) when (attempt < maxRetries)
                if attempt < max_retries:
                    print(
                        f"[Ollama] HTTP ошибка (попытка {attempt + 1}/{max_retries + 1}): {ex}",
                        file=sys.stderr,
                    )
                    time.sleep(1)  # C#: await Task.Delay(1000)
                    attempt += 1
                    continue
                # C#: catch (HttpRequestException) — ретраи исчерпаны
                print(
                    f"[Ollama] Ошибка HTTP после {max_retries + 1} попыток: {ex}",
                    file=sys.stderr,
                )
                log_error("OllamaClient", f"HTTP после {max_retries + 1} попыток: {ex}")
                return f"Не удалось подключиться к Ollama: {ex}"
            except Exception as ex:
                # C#: catch (Exception ex)
                print(f"[Ollama] Непредвиденная ошибка: {ex}", file=sys.stderr)
                log_error("OllamaClient", f"Непредвиденная ошибка: {ex}")
                return f"Ошибка AI: {ex}"

    def _make_cache_key(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: Optional[float],
    ) -> str:
        """Хеш запроса: модель + system + temperature + prompt (context/память внутри prompt)."""
        raw = "\x00".join(
            (
                self._model,
                system_prompt or "",
                "none" if temperature is None else repr(temperature),
                prompt,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _store_in_cache(self, key: str, answer: str) -> None:
        """Кэширует только осмысленные ответы (не тексты ошибок), с лимитом FIFO."""
        if answer.startswith(_ERROR_PREFIXES):
            return
        self._cache[key] = answer
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_limit:
            self._cache.popitem(last=False)

    @staticmethod
    def _read_stream(response: requests.Response) -> str:
        """Аналог ReadStreamAsync: построчный разбор NDJSON в StringBuilder."""
        sb: list[str] = []

        for line in response.iter_lines():  # C#: StreamReader.ReadLine()
            if not line:  # C#: string.IsNullOrEmpty(line)
                continue

            try:
                data = json.loads(line)
                # Десериализация в OllamaStreamChunk: не-объект (в т.ч. null) —
                # в C# это либо json == null, либо JsonException.
                if not isinstance(data, dict):
                    continue
                raw_response = data.get("response")
                raw_done = data.get("done", False)
                if raw_response is not None and not isinstance(raw_response, str):
                    raise ValueError("response: ожидался string")
                if not isinstance(raw_done, bool):
                    raise ValueError("done: ожидался bool")
            except ValueError:
                # Skip malformed JSON
                continue

            chunk = OllamaStreamChunk(response=raw_response, done=raw_done)

            if chunk.response:  # C#: if (!string.IsNullOrEmpty(json.response))
                sb.append(chunk.response)

            if chunk.done:  # C#: if (json.done) return sb.ToString();
                return "".join(sb)

        return "".join(sb)

    def close(self) -> None:
        """Аналог IDisposable.Dispose() (C#: _httpClient.Dispose())."""
        self._session.close()
