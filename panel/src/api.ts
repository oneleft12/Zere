/**
 * API-клиент панели: токен из HTML (инжект сервером), нормализованные
 * ошибки контракта {code, message} (docs/api/openapi.yaml).
 */

export const TOKEN: string =
  document.querySelector<HTMLMetaElement>('meta[name="jarvis-token"]')?.content ?? "";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;

  try {
    response = await fetch(path, {
      method,
      headers: {
        "X-JARVIS-Token": TOKEN,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "NETWORK", "Панель недоступна — бэкенд не отвечает.");
  }

  const text = await response.text();

  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    const error = (data ?? {}) as { code?: string; message?: string };
    throw new ApiError(
      response.status,
      error.code ?? "INTERNAL",
      error.message ?? `Неожиданный ответ сервера (HTTP ${response.status}).`,
    );
  }

  return data as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>("GET", path);
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>("POST", path, body);
}

export function apiDelete<T>(path: string, body?: unknown): Promise<T> {
  return request<T>("DELETE", path, body);
}

// ── SSE (/api/chat/stream) ───────────────────────────────────────
// EventSource не умеет шлить заголовки, а контракт требует X-JARVIS-Token,
// поэтому стрим читаем через fetch + ReadableStream и парсим сами.

export interface SseHandlers {
  onToken?: (text: string) => void;
  onDone?: (answer: string) => void;
  onError?: (code: string, message: string) => void;
}

export async function apiSse(
  path: string,
  handlers: SseHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;

  try {
    response = await fetch(path, {
      method: "GET",
      headers: { "X-JARVIS-Token": TOKEN },
      signal,
    });
  } catch (error) {
    if ((error as Error)?.name === "AbortError") return; // ушли с экрана
    throw new ApiError(0, "NETWORK", "Панель недоступна — бэкенд не отвечает.");
  }

  if (!response.ok) {
    const text = await response.text();
    let data: unknown = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = null;
    }
    const error = (data ?? {}) as { code?: string; message?: string };
    throw new ApiError(
      response.status,
      error.code ?? "INTERNAL",
      error.message ?? `Неожиданный ответ сервера (HTTP ${response.status}).`,
    );
  }

  const reader = response.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      let index = buffer.indexOf("\n\n");
      while (index >= 0) {
        const block = buffer.slice(0, index);
        buffer = buffer.slice(index + 2);
        dispatchSseBlock(block, handlers);
        index = buffer.indexOf("\n\n");
      }
    }
  } catch (error) {
    if ((error as Error)?.name === "AbortError") return; // прервано читателем
    throw new ApiError(0, "NETWORK", "Поток ответа оборвался.");
  }
}

function dispatchSseBlock(block: string, handlers: SseHandlers): void {
  let event = "message";
  let data = "";

  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      data += line.slice("data:".length).trimStart();
    }
  }

  if (!data) return;

  let payload: unknown;
  try {
    payload = JSON.parse(data);
  } catch {
    return; // битое событие не роняет экран
  }

  const body = (payload ?? {}) as { text?: unknown; answer?: unknown; code?: unknown; message?: unknown };

  if (event === "token") handlers.onToken?.(String(body.text ?? ""));
  else if (event === "done") handlers.onDone?.(String(body.answer ?? ""));
  else if (event === "error") {
    handlers.onError?.(String(body.code ?? "INTERNAL"), String(body.message ?? "Ошибка потока."));
  }
}

// ── Типы контракта (из openapi.yaml) ─────────────────────────────

export interface Health {
  ollama: "ok" | "down";
  whisper: "ok" | "missing";
  tts: { engine: "pocket" | "piper"; status: "configured" };
  memory: { count: number };
  version: string;
  branch: string;
}

export interface Config {
  version: string;
  assistantName: string;
  language: string;
  model: string;
  voiceEnabled: boolean;
  voiceVolume: number;
  autoMemory: boolean;
  ollamaTimeoutMinutes: number;
  ttsEngine: "pocket" | "piper";
  voiceReferencePath: string;
}

export interface Personality {
  activeId: string;
  activeStyle: string;
  styles: string[];
}

export interface HistoryItem {
  id: number;
  userMessage: string;
  jarvisResponse: string;
  timestamp: string;
}

export interface HistoryPage {
  items: HistoryItem[];
  total: number;
}

export interface MemoryItem {
  id: number;
  key: string;
  value: string;
  category: string;
  createdAt: string;
}

export interface MemoryList {
  items: MemoryItem[];
}
