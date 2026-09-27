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
