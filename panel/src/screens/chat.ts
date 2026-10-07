/**
 * Экран «Чат» (этап 3 плана, §6): потоковый ответ по SSE
 * (`GET /api/chat/stream`). `EventSource` не умеет отправлять заголовки,
 * а контракт требует `X-ZERE-Token`, поэтому стрим читается через
 * `fetch` + `ReadableStream` (см. `api.ts`). Каждый диалог сохраняется
 * движком в истории — он появляется на экране «История».
 */

import { ApiError, aiSupport, apiGet, apiSse, type AiStatus } from "../api";
import { logEvent } from "../events";
import { t } from "../i18n";
import { badge, button, clear, emptyState, h, loadingRow, pageHeader, textInput, toast } from "../ui";
import { navigate, type Cleanup, type ScreenFactory } from "../router";

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

  container.appendChild(log);
  container.appendChild(h("div", { class: "chat__foot" }, status));
  container.appendChild(composer);

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
