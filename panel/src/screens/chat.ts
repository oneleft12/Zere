/**
 * Экран «Чат» (этап 3 плана, §6): потоковый ответ по SSE
 * (`GET /api/chat/stream`). `EventSource` не умеет отправлять заголовки,
 * а контракт требует `X-ZERE-Token`, поэтому стрим читается через
 * `fetch` + `ReadableStream` (см. `api.ts`). Каждый диалог сохраняется
 * движком в истории — он появляется на экране «История».
 */

import { ApiError, aiSupport, apiGet, apiSse, type AiStatus } from "../api";
import { COMMAND_GROUPS, COMMAND_TOTAL, type CommandItem } from "../commands";
import { logEvent } from "../events";
import { t } from "../i18n";
import { badge, button, clear, emptyState, h, loadingRow, pageHeader, textInput, toast } from "../ui";
import { navigate, type Cleanup, type ScreenFactory } from "../router";

/** Открыта ли панель команд (запоминаем между заходами в чат). */
const COMMANDS_OPEN_KEY = "zere-chat-commands-open";

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

export const chatScreen: ScreenFactory = (container): Cleanup => {
  const messages: Message[] = [];
  let draft = "";
  let busy = false;
  let cancelled = false;
  let controller: AbortController | null = null;
  let pendingEl: HTMLElement | null = null;

  const log = h("div", { class: "chat__log", role: "log", ariaLabel: t("Диалог с ассистентом") });

  const status = h("span", { class: "chat__hint", text: t("Enter — отправить") });

  const sendButton = button(t("Отправить"), () => void send(), "primary");

  const input = textInput({
    value: "",
    placeholder: t("Спросите ZERE…"),
    onInput: (value) => {
      draft = value;
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
    sendButton,
  );

  const providerBadge = badge(t("ИИ"), "plain");

  container.appendChild(
    pageHeader(
      t("Чат"),
      t("Ответ приходит потоком (SSE) и сразу сохраняется в истории диалогов"),
      [providerBadge, badge(t("SSE-стрим"), "accent")],
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
      if (cancelled || support !== "ready") {
        providerBadge.hidden = true;
        aiNotice.hidden = true;
        return;
      }

      const ai = await apiGet<AiStatus>("/api/ai");
      if (cancelled) return;

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
    draft = command;
    input.value = command;
    input.focus();
    input.setSelectionRange(command.length, command.length);
  }

  const commandsChevron = h("span", { class: "chat__commands-chevron" });

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

  function setCommandsOpen(open: boolean, persist = false): void {
    commandsOpen = open;
    commandsBody.hidden = !open;
    commandsChevron.textContent = open ? "▾" : "▸";
    commandsHead.setAttribute("aria-expanded", String(open));

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

  renderLog();
  setBusy(false);

  // ── Рендер ─────────────────────────────────────────────────────

  function renderLog(): void {
    clear(log);

    if (messages.length === 0) {
      log.appendChild(
        emptyState({
          icon: "💬",
          title: t("Начните диалог"),
          hint: t("Спросите ZERE о процессах, файлах или погоде — ответ придёт потоком и попадёт в историю."),
        }),
      );
      return;
    }

    for (const message of messages) {
      log.appendChild(
        h(
          "div",
          {
            class: [
              "msg",
              message.role === "user" ? "msg--user" : "msg--assistant",
              message.error ? "msg--error" : "",
            ]
              .filter(Boolean)
              .join(" "),
          },
          message.text,
        ),
      );
    }

    pendingEl = null;
    scrollToEnd();
  }

  function scrollToEnd(): void {
    log.scrollTop = log.scrollHeight;
  }

  function setBusy(value: boolean): void {
    busy = value;
    input.disabled = value;
    sendButton.disabled = value;
    status.textContent = value ? t("ZERE отвечает…") : t("Enter — отправить");
  }

  // ── Отправка ───────────────────────────────────────────────────

  async function send(): Promise<void> {
    const text = draft.trim();
    if (busy || !text) return;

    messages.push({ role: "user", text });
    messages.push({ role: "assistant", text: "" });
    const answer = messages[messages.length - 1];

    renderLog();
    // Пузырь ответа живёт до конца стрима — дописываем токены в него,
    // а не перерисовываем лог на каждое событие.
    pendingEl = log.lastElementChild as HTMLElement;
    pendingEl.appendChild(loadingRow(t("Думаю…")));
    setBusy(true);

    draft = "";
    input.value = "";
    controller = new AbortController();
    logEvent(`Запрос в чат: ${text.slice(0, 60)}`);

    try {
      await apiSse(
        `/api/chat/stream?text=${encodeURIComponent(text)}`,
        {
          onToken: (chunk) => {
            if (cancelled || !pendingEl) return;
            answer.text += chunk;
            pendingEl.textContent = answer.text;
            scrollToEnd();
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
      if (cancelled) return;

      const message =
        error instanceof ApiError ? error.message : t("Неизвестная ошибка");
      answer.text = message;
      answer.error = true;
      toast(t("Не удалось получить ответ"), "danger");
      logEvent(`Ошибка чата: ${message}`);
    } finally {
      controller = null;

      if (cancelled) return;

      renderLog();
      setBusy(false);
      input.focus();
    }
  }

  return () => {
    cancelled = true;
    controller?.abort();
  };
};
