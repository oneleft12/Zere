/**
 * API-клиент панели: токен из HTML (инжект сервером), нормализованные
 * ошибки контракта {code, message} (docs/api/openapi.yaml).
 */

export const TOKEN: string =
  document.querySelector<HTMLMetaElement>('meta[name="zere-token"]')?.content ?? "";

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
        "X-ZERE-Token": TOKEN,
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

/**
 * Двухшаговое подтверждение опасного действия (P0-3): шаг 1 — POST {},
 * сервер выдаёт одноразовый ttlToken на 60 с; шаг 2 — {confirm, ttlToken}.
 * UI-подтверждение (ConfirmDialog) обязано быть ДО этого вызова.
 */
export async function apiConfirm<T>(path: string, confirm: "KILL" | "POWER"): Promise<T> {
  const pending = await apiPost<{ ttlToken: string }>(path, {});
  return apiPost<T>(path, { confirm, ttlToken: pending.ttlToken });
}

// ── SSE (/api/chat/stream) ───────────────────────────────────────
// EventSource не умеет шлить заголовки, а контракт требует X-ZERE-Token,
// поэтому стрим читаем через fetch + ReadableStream и парсим сами.

export interface SseHandlers {
  onToken?: (text: string) => void;
  onDone?: (answer: string) => void;
  onError?: (code: string, message: string) => void;
  /** Любое событие как есть — нужно для потоков с собственными именами
   *  (например, `progress` у загрузки локальной модели). */
  onEvent?: (event: string, data: unknown) => void;
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
      headers: { "X-ZERE-Token": TOKEN },
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

  handlers.onEvent?.(event, payload);
}

// ── Типы контракта (из openapi.yaml) ─────────────────────────────

export interface Health {
  ollama: "ok" | "down";
  whisper: "ok" | "missing";
  tts: { engine: "pocket" | "chattts"; status: "configured" };
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
  ttsEngine: "pocket" | "chattts";
  /** Движок STT: gigaam — GigaAM-v3 (основной), whisper — откат. */
  sttEngine: "gigaam" | "whisper";
  voiceReferencePath: string;
  /** keep_alive Ollama в секундах (-1 — бессрочно в памяти). */
  llmKeepAlive: number;
  /** Лимит ответа LLM в токенах в голосовом режиме. */
  llmMaxTokens: number;
  /** Таймаут запроса к Ollama в секундах. */
  llmTimeoutSeconds: number;
}

export interface Personality {
  activeId: string;
  activeStyle: string;
  styles: string[];
}

export interface HistoryItem {
  id: number;
  userMessage: string;
  zereResponse: string;
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

// ── Этап 4: процессы/питание, приложения, логи, плагины, голос ───

export interface ProcessInfo {
  pid: number;
  name: string;
  memoryMb: number;
  responding: boolean;
  protected: boolean;
}

export interface ProcessList {
  items: ProcessInfo[];
}

export interface KillPending {
  status: "pending";
  pid: number;
  name: string;
  ttlToken: string;
  expiresInSeconds: number;
}

export interface KillResult {
  status: "killed";
  pid: number;
  name: string;
}

export type PowerAction = "shutdown" | "restart" | "sleep";

export interface PowerPending {
  status: "pending";
  action: PowerAction;
  ttlToken: string;
  expiresInSeconds: number;
}

export interface PowerResult {
  status: "executed" | "failed";
  action: PowerAction;
}

export interface AppInfo {
  name: string;
  executablePath: string;
  source: string;
  category: string;
  priority: number;
  aliases: string[];
  lastSeen: string;
}

export interface AppList {
  items: AppInfo[];
  total: number;
}

export interface AppReindexResponse {
  count: number;
  durationMs: number;
}

export type LogLevel = "info" | "warn" | "error";

export interface LogEntry {
  time: string;
  level: LogLevel;
  message: string;
  source: string | null;
}

export interface LogList {
  items: LogEntry[];
  total: number;
}

export type PluginType = "Personality" | "CommandHandler" | "MemoryProvider" | "VoiceEngine" | "Other";

export interface Plugin {
  id: string;
  name: string;
  description: string;
  version: string;
  author: string;
  type: PluginType;
}

export interface PluginList {
  items: Plugin[];
  handlersConnected: boolean;
  commandHandlersCount: number;
  activePersonality: { id: string; style: string } | null;
}

export interface VoiceCapabilities {
  recordReference: boolean;
  pocketCloning: boolean;
  speechSpeedConfig: boolean;
  liveVolumeApply: boolean;
  sttTest: boolean;
}

export interface VoiceSettings {
  voiceEnabled: boolean;
  voiceVolume: number;
  ttsEngine: "pocket" | "chattts";
  voiceReferencePath: string;
  /** DSP-обработка озвучки ChatTTS: применяется сразу, без перезапуска. */
  audioProcessing: boolean;
  capabilities: VoiceCapabilities;
}

export interface VoiceSettingsApplied {
  voiceEnabled: boolean;
  voiceVolume: number;
  ttsEngine: "pocket" | "chattts";
  voiceReferencePath: string;
  audioProcessing: boolean;
  appliedOnRestart: boolean;
}

/** Фазы непрерывного голосового режима (GET/POST /api/voice/mode). */
export type VoiceModeStateValue =
  | "idle"
  | "sleeping"
  | "listening"
  | "processing"
  | "speaking"
  | "error";

export interface VoiceModeState {
  /** Фоновый цикл «wake word → команда → ответ → озвучка» запущен. */
  enabled: boolean;
  state: VoiceModeStateValue;
  /** STT готов — режим можно включить (иначе POST → 503). */
  available: boolean;
  wakeWordEnabled: boolean;
  wakeWord: string;
  /** Движок триггера: onnx-kws — своя ONNX-модель, whisper — VAD + STT. */
  wakeEngine?: string;
  lastUtterance: string;
  lastAnswer: string;
  lastError: string | null;
  /**
   * Счётчик обработанных голосовых реплик: после каждой +1. По нему чат
   * дописывает пару «услышано / ответ» в диалог. Необязателен: у процесса
   * старше этой сборки поля нет — тогда чат ведёт себя как раньше
   * (реплики видны в «Истории» и на экране «Голос»).
   */
  turn?: number;
}

// ── Обновление из GitHub (docs/UPDATE.md) ────────────────────────

export interface UpdateCommit {
  hash: string;
  short: string;
  subject: string;
  author: string;
  /** ISO 8601 (git %aI). */
  date: string;
}

export type UpdateDependencies = "not-needed" | "updated" | "skipped" | "failed";

export interface UpdateOutcome {
  ok: boolean;
  message: string;
  fromHash: string | null;
  toHash: string | null;
  pulled: number;
  dependencies: UpdateDependencies;
  restartRequired: boolean;
  finishedAt: string;
}

export interface UpdateStatus {
  edition: "python";
  available: boolean;
  branch: string;
  remote: string;
  remoteUrl: string | null;
  current: UpdateCommit | null;
  target: UpdateCommit | null;
  behind: number;
  ahead: number;
  commits: UpdateCommit[];
  dirty: boolean;
  updateAvailable: boolean;
  canUpdate: boolean;
  blockedReason: string | null;
  checking: boolean;
  applying: boolean;
  checkedAt: string | null;
  error: string | null;
  lastResult: UpdateOutcome | null;
}

// ── ИИ: облачный ключ или локальная модель (docs/AI_PROVIDERS.md) ──

/** Режим выбора провайдера: авто → ключ, иначе локальная модель. */
export type AiMode = "auto" | "cloud" | "local";

/** Кто отвечает на запросы прямо сейчас. */
export type AiActiveProvider = "cloud" | "local" | "none";

export interface AiProviderPreset {
  id: string;
  label: string;
  baseUrl: string;
  model: string;
  /** Где взять ключ; пусто у пресета «custom». */
  docsUrl: string;
}

export interface AiLocalModelOption {
  id: string;
  label: string;
  tier: "tiny" | "light" | "medium";
  sizeHint: string;
}

export interface AiInstallHint {
  title: string;
  steps: string[];
  command: string;
  downloadUrl: string;
  model: string;
}

export interface AiCloudStatus {
  provider: string;
  baseUrl: string;
  model: string;
  keySaved: boolean;
  keySource: "none" | "user" | "owner";
  /** Только маска вида sk-...abcd — полный ключ остаётся на бэкенде. */
  keyMask: string;
  keyStatus: "unknown" | "ok" | "invalid";
  keyCheckedAt: string | null;
}

export interface AiLocalStatus {
  baseUrl: string;
  model: string;
  suggestions: AiLocalModelOption[];
  server: "up" | "down" | "unknown";
  /** "ollama" — нативный API, "openai" — /v1, "" — сервер не найден. */
  api: string;
  resolvedBaseUrl: string;
  models: string[];
  modelInstalled: boolean;
  status: "available" | "model-missing" | "server-down";
  statusText: string;
  detail: string;
  canPull: boolean;
  installHint: AiInstallHint | null;
}

export interface AiStatus {
  mode: AiMode;
  activeProvider: AiActiveProvider;
  ready: boolean;
  /** Готовая строка состояния для дашборда и статус-строки. */
  summary: string;
  message: string;
  cloud: AiCloudStatus;
  local: AiLocalStatus;
  presets: AiProviderPreset[];
  settingsPath: string;
}

export interface AiSettingsUpdate {
  mode?: AiMode;
  cloudProvider?: string;
  cloudBaseUrl?: string;
  cloudModel?: string;
  localBaseUrl?: string;
  localModel?: string;
}

export interface AiKeyRequest extends AiSettingsUpdate {
  apiKey: string;
  /** false — сохранить без проверки (по умолчанию ключ проверяется). */
  validate?: boolean;
}

export interface AiKeyTestRequest extends AiSettingsUpdate {
  apiKey?: string;
}

export interface AiKeyTestResult {
  ok: boolean;
  message: string;
  models: string[];
  checkedWith: "models" | "chat";
  keyMask: string;
}

export interface AiLocalTestResult {
  ok: boolean;
  message: string;
  server: "up" | "down";
  models: string[];
}

// ── Поддержка настройки ИИ запущенным бэкендом ─────────────────────
// Фронтенд (panel/dist) общий для двух редакций и обновляется сразу после
// git pull, а серверу для новых маршрутов нужен перезапуск. Чтобы экран не
// показывал «Маршрут не найден», возможности бэкенда определяются один раз
// и интерфейс честно объясняет ситуацию.

export type AiSupport = "ready" | "restart-required" | "unsupported" | "unknown";

let supportProbe: Promise<AiSupport> | null = null;

/**
 * Что умеет запущенный бэкенд:
 * - `ready` — маршрут `/api/ai` есть, настройка ИИ работает;
 * - `restart-required` — `/api/ai` нет, но `/api/update` есть: сервер ZERE
 *   старее панели (dist обновился, процесс не перезапускали);
 * - `unsupported` — нет ни `/api/ai`, ни `/api/update`: сборка панели
 *   старше сервера (или очень старая версия) — настройка ключа недоступна,
 *   работает только локальная модель (Ollama);
 * - `unknown` — бэкенд не ответил (сеть/ошибка): ничего не скрываем.
 */
export function aiSupport(refresh = false): Promise<AiSupport> {
  if (refresh || supportProbe === null) supportProbe = probeAiSupport();
  return supportProbe;
}

async function probeAiSupport(): Promise<AiSupport> {
  try {
    await apiGet<AiStatus>("/api/ai");
    return "ready";
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404) return "unknown";
  }

  try {
    await apiGet<UpdateStatus>("/api/update");
    return "restart-required";
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return "unsupported";
    return "unknown";
  }
}
