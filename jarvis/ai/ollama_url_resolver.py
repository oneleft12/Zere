"""Порт JARVIS.AI/OllamaUrlResolver.cs — поиск доступного адреса Ollama."""

from __future__ import annotations

from typing import Optional

import requests


class OllamaUrlResolver:
    """Аналог static class OllamaUrlResolver."""

    # C#: private static readonly string[] Candidates
    _candidates: list[str] = [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://host.docker.internal:11434",
    ]

    @staticmethod
    def resolve() -> Optional[str]:
        # Reuse a single HttpClient across all candidate checks to avoid socket exhaustion.
        # (в Python — одна сессия requests; Timeout = 2 секунды, как в C#)
        with requests.Session() as client:
            for url in OllamaUrlResolver._candidates:
                try:
                    # Construct full URL directly instead of using BaseAddress,
                    # because BaseAddress cannot be changed after the first request.
                    request_url = url + "/api/tags"
                    # C#: client.GetAsync(requestUrl).GetAwaiter().GetResult()
                    # — Resolve() вызывается из синхронного контекста (конструктора).
                    response = client.get(request_url, timeout=2)

                    if 200 <= response.status_code < 300:  # C#: response.IsSuccessStatusCode
                        return url
                except requests.exceptions.Timeout:
                    # Request timed out — candidate is not available, try next
                    # (C#: catch (TaskCanceledException))
                    continue
                except requests.exceptions.RequestException:
                    # Candidate URL is unreachable or returned an error — try next candidate
                    # (C#: catch (HttpRequestException))
                    continue

        return None
