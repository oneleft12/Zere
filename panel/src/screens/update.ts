/**
 * Экран «Обновления» (docs/UPDATE.md): проверка и применение обновления
 * ZERE из GitHub — fast-forward текущей ветки.
 *
 * Сеть трогает только проверка (кнопка и автопроверка при старте панели);
 * «Обновить сейчас» — `git pull --ff-only` и, если менялся requirements.txt,
 * установка зависимостей Python. После успеха нужен перезапуск ZERE: панель
 * говорит об этом явно и процесс сама не перезапускает.
 */

import {
  ApiError,
  apiGet,
  apiPost,
  type UpdateCommit,
  type UpdateOutcome,
  type UpdateStatus,
} from "../api";
import { logEvent } from "../events";
import { t } from "../i18n";
import {
  badge,
  button,
  card,
  clear,
  emptyState,
  h,
  keyValue,
  loadingRow,
  pageHeader,
  statusPill,
  toast,
} from "../ui";
import type { Cleanup, ScreenFactory } from "../router";

export const updateScreen: ScreenFactory = (container): Cleanup => {
  let cancelled = false;
  let state: UpdateStatus | null = null;
  let working = false; // ожидание ответа check/apply — блокируем кнопки

  const checkButton = button(t("Проверить обновления"), () => void check());
  const applyButton = button(t("Обновить сейчас"), () => void apply(), "primary");

  const body = h("div", { class: "grid-12 fade-in" });

  container.appendChild(
    pageHeader(
      t("Обновления"),
      t("ZERE обновляется из GitHub быстрой перемоткой ветки: config/, zere.db и голосовые модели не перезаписываются"),
      [checkButton, applyButton],
    ),
  );
  container.appendChild(body);

  void load();

  // ── Загрузка и действия ─────────────────────────────────────────

  async function load(): Promise<void> {
    render();

    try {
      const status = await apiGet<UpdateStatus>("/api/update");
      if (cancelled) return;
      state = status;
    } catch (error) {
      if (cancelled) return;
      renderError(error);
      return;
    }

    render();
  }

  async function check(): Promise<void> {
    if (working) return;

    working = true;
    render();

    try {
      const status = await apiPost<UpdateStatus>("/api/update/check", {});
      if (cancelled) return;

      state = status;

      if (status.error) {
        toast(t("Проверка обновлений не удалась"), "warn");
        logEvent(`Проверка обновлений: ${status.error}`);
      } else if (status.updateAvailable) {
        toast(t("Доступно {count} новых коммитов", { count: status.behind }), "warn");
        logEvent(`Обновления: доступно ${status.behind} коммитов`);
      } else {
        toast(t("Установлена последняя версия ветки"), "ok");
        logEvent("Обновления: ветка актуальна");
      }
    } catch (error) {
      if (cancelled) return;
      toast(error instanceof ApiError ? error.message : t("Неизвестная ошибка"), "danger");
      await load();
    } finally {
      if (!cancelled) {
        working = false;
        render();
      }
    }
  }

  async function apply(): Promise<void> {
    if (working || !state?.canUpdate) return;

    working = true;
    render();

    try {
      const outcome = await apiPost<UpdateOutcome>("/api/update/apply", {
        installDependencies: true,
      });
      if (cancelled) return;

      toast(outcome.message, outcome.ok ? "ok" : "warn");
      logEvent(`Обновление: ${outcome.message}`);
    } catch (error) {
      if (cancelled) return;
      toast(error instanceof ApiError ? error.message : t("Неизвестная ошибка"), "danger");
    } finally {
      if (!cancelled) {
        working = false;
        await load();
      }
    }
  }

  // ── Отрисовка ──────────────────────────────────────────────────

  function render(): void {
    clear(body);

    if (state === null && !working) {
      body.appendChild(h("div", { class: "col-12" }, loadingRow(t("Чтение состояния обновления…"))));
      return;
    }

    const status = state;

    updateControls();

    if (working) {
      body.appendChild(
        h(
          "div",
          { class: "col-12" },
          loadingRow(
            status?.applying
              ? t("Обновление применяется: git pull и зависимости…")
              : t("Обращение к GitHub…"),
          ),
        ),
      );
    }

    if (status === null) return;

    body.appendChild(statusCard(status));
    body.appendChild(commitsCard(status));
    body.appendChild(outcomeCard(status.lastResult));
  }

  function statusCard(status: UpdateStatus): HTMLElement {
    const pills = h(
      "div",
      { class: "pill-row" },
      statusPill({
        label: t("Ветка"),
        value: `${status.remote}/${status.branch}`,
        state: "idle",
      }),
      statusPill({
        label: t("Установлено"),
        value: status.current ? status.current.short : "—",
        state: "ok",
      }),
      statusPill({
        label: t("Доступно"),
        value: status.updateAvailable
          ? t("+{count} коммитов", { count: status.behind })
          : t("нет обновлений"),
        state: status.updateAvailable ? "warn" : "ok",
      }),
      statusPill({
        label: t("Рабочая копия"),
        value: status.dirty ? t("есть правки") : t("чисто"),
        state: status.dirty ? "warn" : "ok",
      }),
      statusPill({
        label: t("Редакция"),
        value: status.edition,
        state: "idle",
      }),
    );

    const element = card(
      t("Состояние"),
      h(
        "div",
        { class: "update-section" },
        pills,
        keyValue([
          { key: t("Репозиторий"), value: status.remoteUrl ?? "—" },
          {
            key: t("Текущий коммит"),
            value: status.current
              ? `${status.current.short} · ${status.current.subject}`
              : "—",
          },
          {
            key: t("Удалённая ветка"),
            value: status.target
              ? `${status.target.short} · ${status.target.subject}`
              : "—",
          },
          {
            key: t("Проверено"),
            value: status.checkedAt ? formatStamp(status.checkedAt) : t("ещё не проверялось"),
          },
        ]),
      ),
    );
    element.classList.add("col-12");

    // Причина отказа и ошибка проверки — тем же блоком, что валидация форм.
    if (status.blockedReason || status.error) {
      element.appendChild(
        h("div", {
          class: "form-error",
          text: status.error ?? status.blockedReason ?? "",
        }),
      );
    }

    return element;
  }

  function commitsCard(status: UpdateStatus): HTMLElement {
    const element = card(t("Новые коммиты"), commitList(status.commits));
    element.classList.add("col-6");
    return element;
  }

  function commitList(commits: UpdateCommit[]): HTMLElement {
    if (commits.length === 0) {
      return emptyState({
        icon: "✅",
        title: t("Новых коммитов нет"),
        hint: t("Локальная ветка совпадает с удалённой."),
      });
    }

    return h(
      "div",
      { class: "logs-list" },
      ...commits.map((commit) =>
        h(
          "div",
          { class: "log-entry" },
          badge(commit.short, "accent"),
          h("span", { class: "log-entry__message", text: commit.subject }),
          h("span", { class: "log-entry__time", text: formatDate(commit.date) }),
        ),
      ),
    );
  }

  function outcomeCard(outcome: UpdateOutcome | null): HTMLElement {
    const element = card(t("Последнее обновление"));

    if (outcome === null) {
      element.appendChild(
        emptyState({
          icon: "🗒",
          title: t("Обновление ещё не запускалось"),
          hint: t("История обновлений не ведётся: показан результат последнего запуска."),
        }),
      );
    } else {
      element.appendChild(
        h(
          "div",
          { class: "update-section" },
          h(
            "div",
            { class: "pill-row" },
            badge(outcome.ok ? t("применено") : t("отклонено"), outcome.ok ? "ok" : "warn"),
            badge(`${outcome.pulled}`, "plain"),
            badge(t("зависимости: {value}", { value: outcome.dependencies }), "plain"),
          ),
          h("p", { class: "update-hint", text: outcome.message }),
          outcome.restartRequired
            ? h("p", {
                class: "update-hint",
                text: t(
                  "Код на диске новее запущенного: закройте и снова запустите ZERE, чтобы изменения вступили в силу.",
                ),
              })
            : null,
        ),
      );
    }

    element.classList.add("col-6");
    return element;
  }

  function renderError(error: unknown): void {
    clear(body);

    const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");

    body.appendChild(
      h(
        "div",
        { class: "col-12" },
        emptyState({
          icon: "⚠️",
          title: t("Не удалось получить состояние обновления"),
          hint: message,
          action: { label: t("Повторить"), onClick: () => void load() },
        }),
      ),
    );
  }

  function updateControls(): void {
    const busy = working || state?.applying === true || state?.checking === true;

    checkButton.disabled = busy;
    applyButton.disabled = busy || state?.canUpdate !== true;

    applyButton.title = state?.canUpdate
      ? t("git pull --ff-only текущей ветки")
      : (state?.blockedReason ?? t("Обновление сейчас недоступно"));
  }

  return () => {
    cancelled = true;
  };
};

function formatDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function formatStamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}
