/**
 * Экран «Чат» (этап 3 плана, §6): потоковый ответ по SSE
 * (`GET /api/chat/stream`). `EventSource` не умеет отправлять заголовки,
 * а контракт требует `X-JARVIS-Token`, поэтому стрим читается через
 * `fetch` + `ReadableStream` (см. `api.ts`). Каждый диалог сохраняется
 * движком в истории — он появляется на экране «История».
 */

import { ApiError, apiSse } from "../api";
import { logEvent } from "../events";
import { badge, button, clear, emptyState, h, loadingRow, pageHeader, textInput, toast } from "../ui";
import type { Cleanup, ScreenFactory } from "../router";

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

  const log = h("div", { class: "chat__log", role: "log", ariaLabel: "Диалог с ассистентом" });

  const status = h("span", { class: "chat__hint", text: "Enter — отправить" });

  const sendButton = button("Отправить", () => void send(), "primary");

  const input = textInput({
    value: "",
    placeholder: "Спросите JARVIS…",
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

  container.appendChild(
    pageHeader(
      "Чат",
      "Ответ приходит потоком (SSE) и сразу сохраняется в истории диалогов",
      [badge("SSE-стрим", "accent")],
    ),
  );
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
          title: "Начните диалог",
          hint: "Спросите JARVIS о процессах, файлах или погоде — ответ придёт потоком и попадёт в историю.",
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
    status.textContent = value ? "JARVIS отвечает…" : "Enter — отправить";
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
    pendingEl.appendChild(loadingRow("Думаю…"));
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
        error instanceof ApiError ? error.message : "Неизвестная ошибка";
      answer.text = message;
      answer.error = true;
      toast("Не удалось получить ответ", "danger");
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
