/**
 * Экран «Чат» (этап 3 плана, §6): потоковый ответ по SSE
 * (`GET /api/chat/stream`). `EventSource` не умеет отправлять заголовки,
 * а контракт требует `X-ZERE-Token`, поэтому стрим читается через
 * `fetch` + `ReadableStream` (см. `api.ts`). Каждый диалог сохраняется
 * движком в истории — он появляется на экране «История».
 *
 * Состояние диалога живёт в модуле (`chatState`), а не внутри фабрики
 * экрана: роутер пересоздаёт экран на каждом переходе, и раньше диалог
 * сбрасывался при переключении вкладки (чат → «Подключение ИИ» → чат).
 * Ответ, начатый до ухода с экрана, тоже продолжает стримиться: вернувшись,
 * видно дописанный до конца ответ, а не пустой пузырь.
 */

import {
  ApiError,
  aiSupport,
  apiGet,
  apiPost,
  apiSse,
  type AiStatus,
  type VoiceModeState,
  type VoiceSettings,
} from "../api";
import { COMMAND_GROUPS, COMMAND_TOTAL, type CommandItem } from "../commands";
import { announceAssistantState, logEvent } from "../events";
import { t } from "../i18n";
import {
  badge,
  button,
  clear,
  emptyState,
  h,
  iconButton,
  pageHeader,
  textInput,
  toast,
} from "../ui";
import { registerChatPrefill } from "../palette";
import { slideToggle } from "../motion";
import { icon } from "../icons";
import { navigate, type Cleanup, type ScreenFactory } from "../router";

/** Открыта ли панель команд (запоминаем между заходами в чат). */
const COMMANDS_OPEN_KEY = "zere-chat-commands-open";

/** Три точки ожидания первого токена внутри строки загрузки. */
function typingDots(): HTMLElement {
  return h(
    "span",
    { class: "typing" },
    h("span", {}),
    h("span", {}),
    h("span", {}),
  );
}

function readCommandsOpen(): boolean {
  try {
    return window.localStorage.getItem(COMMANDS_OPEN_KEY) !== "0";
  } catch {
    return true; // приватный режим браузера — просто открыта по умолчанию
  }
}

interface Message {
  role: "user" | "assistant";
  text: string;
  error?: boolean;
}

interface ChatState {
  messages: Message[];
  draft: string;
  busy: boolean;
  /** Индекс пузыря, в который пишется текущий ответ (-1 — стрима нет). */
  streamingIndex: number;
  controller: AbortController | null;
}

/** Диалог переживает уход на другую вкладку и возврат в чат. */
const chatState: ChatState = {
  messages: [],
  draft: "",
  busy: false,
  streamingIndex: -1,
  controller: null,
};

/**
 * Голосовое в чате. Запись идёт на сервере (`POST /api/voice/listen` — та же
 * дорожка, что у «Теста микрофона» на экране «Голос»), а не через
 * `getUserMedia`: панель локальная, микрофон принадлежит машине ZERE, и
 * браузер не спрашивает разрешение.
 *
 * Оба поля живут в модуле, как и диалог: запись длится несколько секунд, и
 * переход на другую вкладку не должен её терять или оставлять кнопку в
 * состоянии «идёт запись» навсегда.
 */

/** `capabilities.sttTest` из `/api/voice`; null — ещё не спросили. */
let sttAvailable: boolean | null = null;

/** Идёт запись голосового. */
let recording = false;

/** Запись голосового: распознанный текст встаёт в поле ввода. */
async function recordVoice(immediate: boolean): Promise<void> {
  if (recording) return;

  recording = true;
  view?.sync();
  announceAssistantState("listening", t("ZERE слушает"));
  logEvent("Запись голосового из чата");

  let recognized = "";

  try {
    const result = await apiPost<{ text: string }>("/api/voice/listen", {});
    recognized = (result.text ?? "").trim();

    if (recognized) {
      // Дописываем к черновику: сказанное голосом не затирает набранное руками.
      chatState.draft = chatState.draft.trim()
        ? `${chatState.draft.trim()} ${recognized}`
        : recognized;
      // В тосте — начало фразы: длинная реплика целиком не читается, а
      // целиком она уже стоит в поле ввода перед глазами.
      const preview = recognized.length > 60 ? `${recognized.slice(0, 60)}…` : recognized;
      toast(t("Распознано: «{text}»", { text: preview }), "ok");
      logEvent(`Голосовое распознано: «${recognized.slice(0, 60)}»`);
    } else {
      toast(t("Микрофон ничего не распознал"), "warn");
      logEvent("Голосовое: микрофон ничего не распознал");
    }
  } catch (error) {
    const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
    toast(t("Не удалось записать голосовое: {message}", { message }), "danger");
    logEvent(`Ошибка записи голосового: ${message}`);
  } finally {
    recording = false;
    announceAssistantState("idle", t("ZERE готов"));
    view?.sync();
    view?.focusInput();
  }

  // Shift+клик по микрофону: распознанное уходит в чат без правки в поле.
  if (recognized && immediate) void send();
}

/**
 * Режим голоса в шапке чата — тот же непрерывный слушатель, что включается
 * тумблером на экране «Голос» (`GET/POST /api/voice/mode`), но под рукой
 * там, где идёт диалог: слушать команды, не переключая экран.
 *
 * Кнопка не «немая»: в подписи — фаза цикла (ждёт слово-триггер, слушает
 * команду, формулирует ответ, озвучивает), поэтому видно, что микрофон жив.
 * Состояние в модуле: переживает переход по вкладкам, как диалог.
 */

/** Состояние режима; null — бэкенд его не отдаёт (старого образца). */
let voiceMode: VoiceModeState | null = null;

/** Переключение в полёте: кнопка не даёт нажать себя дважды. */
let voiceModeBusy = false;

/**
 * Поколение состояния: растёт на каждом переключении. Опрос, начатый до
 * нажатия, не должен перебить свежий ответ `POST` — его результат устарел.
 */
let voiceModeSeq = 0;

/** Опрос фазы режима, пока экран чата открыт. */
const MODE_POLL_MS = 2000;

/** Фаза цикла словами — формулировки те же, что на экране «Голос». */
function voiceModePhase(mode: VoiceModeState): string {
  switch (mode.state) {
    case "sleeping":
      return mode.wakeWordEnabled
        ? t("ждёт «{word}»", { word: mode.wakeWord })
        : t("слушает без триггера");
    case "listening":
      return t("слушает команду");
    case "processing":
      return t("формулирует ответ");
    case "speaking":
      return t("озвучивает ответ");
    case "error":
      return t("ошибка");
    default:
      return t("выключен");
  }
}

/** Подпись кнопки режима: включён — с фазой, выключен — просто имя. */
function voiceModeLabel(mode: VoiceModeState | null): string {
  if (mode?.enabled) return t("Режим голоса: {state}", { state: voiceModePhase(mode) });
  return t("Режим голоса");
}

/** Подсказка кнопки: что будет по нажатию и почему нельзя, если нельзя. */
function voiceModeHint(mode: VoiceModeState | null, busy: boolean): string {
  if (mode === null) {
    return t("Состояние режима недоступно: сервер не отдаёт /api/voice/mode");
  }
  if (!mode.available) {
    return t("Распознавание речи недоступно — режим голоса включить нельзя");
  }
  if (busy) return t("Переключаю режим голоса…");
  return mode.enabled
    ? t("Выключить режим голоса")
    : t("Включить режим голоса: слово-триггер → команда → ответ голосом");
}

/** Переключение режима: POST /api/voice/mode и честный результат в тосте. */
async function toggleVoiceMode(): Promise<void> {
  if (voiceMode === null || voiceModeBusy) return;

  const enable = !voiceMode.enabled;
  voiceModeBusy = true;
  voiceModeSeq += 1; // ответы опроса «до нажатия» больше не актуальны
  view?.sync();

  try {
    voiceMode = await apiPost<VoiceModeState>("/api/voice/mode", { enabled: enable });

    toast(
      enable ? t("Голосовой режим включён") : t("Голосовой режим выключен"),
      "ok",
    );
    logEvent(
      enable ? "Режим голоса включён из чата" : "Режим голоса выключен из чата",
    );
  } catch (error) {
    const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
    toast(t("Не удалось переключить режим: {message}", { message }), "danger");
    logEvent(`Ошибка переключения режима голоса: ${message}`);
  } finally {
    voiceModeBusy = false;
    view?.sync();
  }
}

/** Смонтированный экран: стрим пишет в него, только пока он на экране. */
interface ChatView {
  /** Полная перерисовка лога из состояния + синхронизация ввода и статуса. */
  sync(): void;
  /** Дописать текущий ответ в его пузырь, без полной перерисовки лога. */
  appendChunk(): void;
  /** Вернуть фокус в поле ввода. */
  focusInput(): void;
}

let view: ChatView | null = null;

// Палитра (Ctrl+K) подставляет выбранную команду в тот же черновик:
// состояние диалога одно, независимо от того, откуда пришла команда.
registerChatPrefill((text) => {
  chatState.draft = text;
});

/** Отрисовка лога из состояния (общая для экрана и стрима). */
function renderLogInto(log: HTMLElement): void {
  clear(log);

  if (chatState.messages.length === 0) {
    log.appendChild(
      emptyState({
        icon: "chat",
        title: t("Начните диалог"),
        hint: t("Спросите ZERE о процессах, файлах или погоде — ответ придёт потоком и попадёт в историю."),
      }),
    );
    return;
  }

  chatState.messages.forEach((message, index) => {
    const streaming = chatState.busy && chatState.streamingIndex === index;

    const bubble = h("div", {
      class: [
        "msg",
        message.role === "user" ? "msg--user" : "msg--assistant",
        message.error ? "msg--error" : "",
        // Каретка у последней реплики: видно, что поток ещё пишет.
        streaming && message.text !== "" ? "msg--streaming" : "",
      ]
        .filter(Boolean)
        .join(" "),
      text: message.text,
    });

    // Пузырь ответа живёт до конца стрима: пока токенов нет — «Думаю…».
    if (streaming && message.text === "") {
      bubble.appendChild(
        h("div", { class: "loading-row" }, typingDots(), h("span", { text: t("Думаю…") })),
      );
    }

    log.appendChild(bubble);
  });

  log.scrollTop = log.scrollHeight;
}

/** Отправка запроса в чат — вне экрана: стрим переживает пересоздание вкладки. */
async function send(): Promise<void> {
  const text = chatState.draft.trim();
  if (chatState.busy || !text) return;

  chatState.messages.push({ role: "user", text });
  chatState.messages.push({ role: "assistant", text: "" });

  const index = chatState.messages.length - 1;
  const answer = chatState.messages[index];

  chatState.busy = true;
  chatState.streamingIndex = index;
  chatState.draft = "";
  view?.sync();

  // Ассистент ушёл думать: орб в статус-строке показывает это же состояние.
  announceAssistantState("thinking", t("ZERE думает"));
  logEvent(`Запрос в чат: ${text.slice(0, 60)}`);

  const controller = new AbortController();
  chatState.controller = controller;
  let firstToken = true;

  try {
    await apiSse(
      `/api/chat/stream?text=${encodeURIComponent(text)}`,
      {
        onToken: (chunk) => {
          if (firstToken) {
            firstToken = false;
            announceAssistantState("speaking", t("ZERE отвечает"));
          }
          answer.text += chunk;
          view?.appendChunk();
        },
        onDone: (full) => {
          if (full) answer.text = full; // авторитетный итог от сервера
        },
        onError: (code, message) => {
          answer.text = `${message} (${code})`;
          answer.error = true;
        },
      },
      controller.signal,
    );
  } catch (error) {
    const message =
      error instanceof ApiError ? error.message : t("Неизвестная ошибка");
    answer.text = message;
    answer.error = true;
    announceAssistantState("error", t("Ответ не получен"));
    toast(t("Не удалось получить ответ"), "danger");
    logEvent(`Ошибка чата: ${message}`);
  } finally {
    if (chatState.controller === controller) chatState.controller = null;
    chatState.busy = false;
    chatState.streamingIndex = -1;

    // Ответ закончился — ассистент снова в покое: причину сбоя несёт
    // сама реплика, а не вечный сигнал в статус-строке.
    announceAssistantState("idle", t("ZERE готов"));

    // Экран мог быть пересоздан (переход по вкладкам) или вообще не открыт:
    // состояние уже в модуле, поэтому рисуем только если чат на экране.
    view?.sync();
    view?.focusInput();
  }
}

export const chatScreen: ScreenFactory = (container): Cleanup => {
  // Своя «живость» на монтаж: асинхронные обновления этого экрана (бейдж ИИ)
  // не должны трогать DOM после ухода на другую вкладку.
  let mounted = true;

  const log = h("div", { class: "chat__log", role: "log", ariaLabel: t("Диалог с ассистентом") });

  const statusKey = h("kbd", { text: "Enter" });
  const statusText = h("span", { class: "chat__hint", text: t("отправить") });
  const status = h("span", { class: "chat__state" }, statusKey, statusText);

  const sendButton = button(t("Отправить"), () => void send(), "primary", "send");

  // ── Голосовое: «Записать голосовое» → текст в поле ввода ─────────
  // Клик — запись и вставка распознанного в композер (видно, что услышано,
  // можно поправить); Shift+клик — сразу отправить. Подписи кнопки честные:
  // если STT нет, она выключена и объясняет причину, а не молчит.
  // ghost-иконка: в композере главное — «Отправить», микрофон рядом и тише.
  const micButton = iconButton("voice", t("Записать голосовое"));
  // Стабильный крючок: aria-label честно меняется по фазе («идёт запись»),
  // поэтому тестам и стилям нужен признак, который не зависит от подписи.
  micButton.classList.add("chat__mic");

  micButton.addEventListener("click", (event) => {
    void recordVoice((event as MouseEvent).shiftKey);
  });

  function micLabel(): string {
    if (sttAvailable === false) return t("Распознавание речи недоступно");
    return recording ? t("Идёт запись голосового…") : t("Записать голосовое");
  }

  function micHint(): string {
    if (sttAvailable === false) {
      return t("STT недоступен (capabilities.sttTest=false) — кнопка выключена");
    }
    if (sttAvailable === null) return t("Проверяю микрофон…");
    return t(
      "Запись ≈5 с с микрофона машины ZERE, затем распознавание; Shift+клик — отправить сразу",
    );
  }

  /** Доступность STT не угадываем, а спрашиваем у `/api/voice`. */
  async function refreshMic(): Promise<void> {
    try {
      const settings = await apiGet<VoiceSettings>("/api/voice");
      if (!mounted) return;
      sttAvailable = Boolean(settings.capabilities?.sttTest);
    } catch {
      // Голосовой модуль не подключён или бэкенд старее контракта:
      // кнопка выключена с причиной, сам чат работает как раньше.
      if (!mounted) return;
      sttAvailable = false;
    }

    view?.sync();
  }

  // ── Режим голоса в шапке чата (GET/POST /api/voice/mode) ────────
  // Тот же непрерывный слушатель, что включается на экране «Голос», но
  // под рукой в диалоге. Подпись кнопки несёт фазу цикла: включённый
  // режим видно, а не приходится верить на слово.
  const voiceModeButton = button(
    t("Режим голоса"),
    () => void toggleVoiceMode(),
    "default",
    "voice",
  );
  voiceModeButton.classList.add("chat__mode");
  const voiceModeButtonLabel = voiceModeButton.querySelector<HTMLElement>("span");

  let modeTimer: number | null = null;

  function stopModePoll(): void {
    if (modeTimer !== null) window.clearInterval(modeTimer);
    modeTimer = null;
  }

  /** Опрос фазы: состояние живёт на сервере, кнопка обязана его догнать. */
  async function pollVoiceMode(): Promise<void> {
    const seq = voiceModeSeq;

    try {
      const next = await apiGet<VoiceModeState>("/api/voice/mode");
      // Ответ мог прийти после переключения — тогда он уже не про то состояние.
      if (!mounted || seq !== voiceModeSeq) return;
      voiceMode = next;
    } catch (error) {
      if (!mounted || seq !== voiceModeSeq) return;

      // 404 — бэкенд старого образца: кнопки режима в чате просто нет,
      // и опрашивать больше нечего.
      if (error instanceof ApiError && error.status === 404) {
        voiceMode = null;
        stopModePoll();
        view?.sync();
        return;
      }

      // Прочие сбои (панель не ответила) состояние не выдумывают:
      // остаётся последнее известное.
    }

    view?.sync();
  }

  void pollVoiceMode();
  modeTimer = window.setInterval(() => void pollVoiceMode(), MODE_POLL_MS);

  const input = textInput({
    value: chatState.draft,
    placeholder: t("Спросите ZERE…"),
    onInput: (value) => {
      chatState.draft = value;
    },
  });

  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey) return;
    event.preventDefault();
    void send();
  });

  const composer = h(
    "form",
    {
      class: "chat__composer",
      onsubmit: (event: Event) => {
        event.preventDefault();
        void send();
      },
    },
    input,
    micButton,
    sendButton,
  );

  const providerBadge = badge(t("ИИ"), "plain");

  container.appendChild(
    pageHeader(
      t("Чат"),
      t("Ответ приходит потоком (SSE) и сразу сохраняется в истории диалогов"),
      // Режим голоса — первым действием: он про то, как говорить с ZERE,
      // а бейджи ИИ и стрима — про то, как приходит ответ.
      [voiceModeButton, providerBadge, badge(t("SSE-стрим"), "accent")],
    ),
  );

  // ── Кто отвечает: облачная модель или локальная (требование 1) ──
  // Если не настроено ни то, ни другое — подсказка и переход в «Подключение ИИ».
  const aiNotice = h("div", { class: "ai-notice", hidden: true });

  async function refreshProvider(): Promise<void> {
    try {
      // Бэкенд без /api/ai (старая сборка) или со старым кодом: бейджа нет,
      // подсказку не показываем — чат работает и без этой информации.
      const support = await aiSupport();
      if (!mounted || support !== "ready") {
        providerBadge.hidden = true;
        aiNotice.hidden = true;
        return;
      }

      const ai = await apiGet<AiStatus>("/api/ai");
      if (!mounted) return;

      providerBadge.textContent =
        ai.activeProvider === "cloud"
          ? t("Облачная модель")
          : ai.activeProvider === "local"
            ? t("Локальная модель")
            : t("ИИ не настроен");

      clear(aiNotice);

      if (!ai.ready) {
        aiNotice.appendChild(h("span", { text: ai.message }));
        aiNotice.appendChild(button(t("Настроить ИИ"), () => navigate("/ai"), "primary"));
        aiNotice.hidden = false;
      } else {
        aiNotice.hidden = true;
      }
    } catch {
      // Состояние ИИ — вспомогательное: без него чат всё равно работает.
    }
  }

  container.appendChild(aiNotice);
  void refreshProvider();
  void refreshMic();

  // ── Список доступных команд (единый каталог `commands.ts`) ──────
  // Команды вставляются в поле ввода нажатием: не нужно помнить точную
  // формулировку, а весь справочник живёт прямо во вкладке «Чат».
  const commandsEmpty = h("p", {
    class: "chat__commands-empty",
    text: t("Ничего не найдено — попробуйте другой запрос"),
    hidden: true,
  });
  const commandsGrid = h("div", { class: "chat__commands-grid" });

  function matches(item: CommandItem, query: string): boolean {
    if (query === "") return true;

    const haystack = `${item.command} ${t(item.hint)}`.toLowerCase();
    return haystack.includes(query);
  }

  function renderCommands(filter: string): void {
    const query = filter.trim().toLowerCase();
    clear(commandsGrid);

    let shown = 0;

    for (const group of COMMAND_GROUPS) {
      const items = group.items.filter((item) => matches(item, query));
      if (items.length === 0) continue;

      shown += items.length;
      commandsGrid.appendChild(
        h(
          "article",
          { class: "cmd-group" },
          h(
            "h3",
            { class: "cmd-group__title" },
            h("span", { text: t(group.title) }),
            group.note
              ? h("span", { class: "cmd-group__note", text: t(group.note) })
              : null,
          ),
          h(
            "ul",
            { class: "cmd-list" },
            ...items.map((item) =>
              h(
                "li",
                {},
                h(
                  "button",
                  {
                    class: "cmd",
                    type: "button",
                    title: t("Вставить в поле ввода"),
                    onclick: () => insertCommand(item.command),
                  },
                  h("code", { class: "cmd__text", text: item.command }),
                  h("span", { class: "cmd__hint", text: t(item.hint) }),
                ),
              ),
            ),
          ),
        ),
      );
    }

    commandsEmpty.hidden = shown > 0;
  }

  /** Подставляет команду в композер: остаётся дописать аргумент и нажать Enter. */
  function insertCommand(command: string): void {
    chatState.draft = command;
    input.value = command;
    input.focus();
    input.setSelectionRange(command.length, command.length);
  }

  const commandsChevron = h("span", { class: "chat__commands-chevron" });
  commandsChevron.appendChild(icon("chevronDown", { size: 16 }));

  const commandsHead = h(
    "button",
    {
      class: "chat__commands-head",
      type: "button",
      onclick: () => setCommandsOpen(!commandsOpen, true),
    },
    h("span", { class: "chat__commands-title", text: t("Команды ZERE") }),
    badge(String(COMMAND_TOTAL), "accent"),
    commandsChevron,
  );

  const commandsBody = h(
    "div",
    { class: "chat__commands-body", hidden: true },
    h("p", {
      class: "chat__commands-tip",
      text: t("Нажмите команду — она подставится в поле ввода"),
    }),
    h(
      "div",
      { class: "chat__commands-search" },
      textInput({
        value: "",
        placeholder: t("Поиск команды…"),
        onInput: (value) => renderCommands(value),
      }),
    ),
    commandsGrid,
    commandsEmpty,
  );

  const commandsPanel = h(
    "section",
    { class: "chat__commands" },
    commandsHead,
    commandsBody,
  );

  let commandsOpen = true;

  /**
   * Раскрытие анимируется по реальной высоте, а `hidden` ставится после
   * сворачивания: закрытая панель не остаётся в раскладке и не ловит фокус.
   */
  function setCommandsOpen(open: boolean, persist = false): void {
    commandsOpen = open;
    commandsHead.setAttribute("aria-expanded", String(open));

    if (open) {
      commandsBody.hidden = false;
      void slideToggle(commandsBody, true);
    } else if (!commandsBody.hidden) {
      void slideToggle(commandsBody, false).then(() => {
        // Пользователь мог успеть раскрыть панель обратно.
        if (!commandsOpen) commandsBody.hidden = true;
      });
    }

    if (!persist) return;

    try {
      window.localStorage.setItem(COMMANDS_OPEN_KEY, open ? "1" : "0");
    } catch {
      // Настройка необязательная: без localStorage панель просто не запомнится.
    }
  }

  renderCommands("");
  setCommandsOpen(readCommandsOpen());

  // Диалог и справочник команд — рядом: на широком экране список всех
  // команд виден сразу и не вытесняет чат за нижнюю границу окна, а на
  // узком панель встаёт под чат (см. `.chat__split`).
  container.appendChild(
    h(
      "div",
      { class: "chat__split" },
      h(
        "div",
        { class: "chat__main" },
        log,
        h("div", { class: "chat__foot" }, status),
        composer,
      ),
      commandsPanel,
    ),
  );

  // ── Рендер ─────────────────────────────────────────────────────

  const viewImpl: ChatView = {
    sync(): void {
      renderLogInto(log);
      input.value = chatState.draft;
      input.disabled = chatState.busy;
      sendButton.disabled = chatState.busy;

      micButton.disabled = recording || chatState.busy || sttAvailable === false;
      micButton.classList.toggle("btn--recording", recording);
      micButton.title = micHint();
      micButton.setAttribute("aria-label", micLabel());

      // Кнопка режима голоса: у бэкенда без /api/voice/mode её нет вовсе,
      // у бэкенда без STT — выключена и объясняет причину.
      voiceModeButton.hidden = voiceMode === null;
      voiceModeButton.disabled = voiceModeBusy || voiceMode?.available === false;
      voiceModeButton.classList.toggle("chat__mode--on", voiceMode?.enabled === true);
      voiceModeButton.setAttribute("aria-pressed", String(voiceMode?.enabled === true));
      voiceModeButton.title = voiceModeHint(voiceMode, voiceModeBusy);
      if (voiceModeButtonLabel) voiceModeButtonLabel.textContent = voiceModeLabel(voiceMode);

      // Строка состояния одна на все фазы: запись микрофона видно там же,
      // где «отправить» и «ZERE отвечает…».
      statusText.textContent = recording
        ? t("Слушаю микрофон…")
        : chatState.busy
          ? t("ZERE отвечает…")
          : t("отправить");
      statusKey.hidden = chatState.busy || recording;
    },

    appendChunk(): void {
      const index = chatState.streamingIndex;
      const message = chatState.messages[index];
      const bubble = log.querySelectorAll<HTMLElement>(".msg")[index];

      if (!message || !bubble) {
        renderLogInto(log);
        return;
      }

      // Пока идут токены, у реплики мигает каретка — поток виден, а не угадывается.
      bubble.textContent = message.text;
      bubble.classList.toggle("msg--error", Boolean(message.error));
      bubble.classList.toggle("msg--streaming", message.text !== "");
      log.scrollTop = log.scrollHeight;
    },

    focusInput(): void {
      input.focus();
    },
  };

  // Экран пересоздан (возврат на вкладку или смена языка) — показываем
  // накопленный диалог и, если стрим ещё идёт, продолжаем писать в него.
  view = viewImpl;
  viewImpl.sync();

  return () => {
    mounted = false;
    // Опрос фазы режима — ресурс экрана: ушли из чата, таймер погас.
    stopModePoll();
    // Стрим не обрываем: состояние живёт в модуле, а `view = null` просто
    // отключает запись в уже снесённый DOM.
    if (view === viewImpl) view = null;
  };
};
