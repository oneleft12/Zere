/**
 * Экран «Папки»: поиск по стандартным папкам, профилю и локальным дискам.
 *
 * Выдача ранжируется на сервере (точное имя → начало имени → часть → похоже),
 * а кнопка «Открыть» показывает папку в проводнике. Пустой запрос — стандартные
 * папки, чтобы экран не выглядел пустым при первом открытии.
 */

import {
  ApiError,
  apiGet,
  apiPost,
  type FolderInfo,
  type FolderList,
  type FolderOpenResult,
} from "../api";
import { logEvent } from "../events";
import { lang, t } from "../i18n";
import {
  badge,
  button,
  clear,
  emptyState,
  h,
  pageHeader,
  skeleton,
  textInput,
  toast,
} from "../ui";
import type { Cleanup, ScreenFactory } from "../router";

const SEARCH_DEBOUNCE_MS = 300;
const MAX_QUERY = 200;

const REASON_LABELS: Record<string, string> = {
  exact: "точное имя",
  prefix: "начало имени",
  words: "слова",
  substring: "часть имени",
  part: "часть имени",
  fuzzy: "похоже",
  path: "путь",
  alias: "стандартная папка",
  known: "стандартная папка",
};

export const foldersScreen: ScreenFactory = (container): Cleanup => {
  let query = "";
  let cancelled = false;
  let loading = false;
  let opening = false;
  let requestSeq = 0;
  let searchTimer = 0;

  const countLabel = h("span", { class: "history__count" });
  const errorBox = h("div", { class: "form-error", hidden: true });
  const notice = h("p", { class: "history__count", hidden: true });
  const list = h("div", { class: "table-wrap" });

  const searchInput = textInput({
    value: "",
    placeholder: t("Поиск папки по имени…"),
    onInput: (value) => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        const next = value.slice(0, MAX_QUERY).trim();
        if (next === query) return;
        query = next;
        void load();
      }, SEARCH_DEBOUNCE_MS);
    },
  });

  const refreshButton = button(t("Обновить"), () => void load(true), "primary", "refresh");

  container.appendChild(
    pageHeader(
      t("Папки"),
      t("Поиск по стандартным папкам, профилю и локальным дискам; открытие в проводнике"),
      [refreshButton],
    ),
  );

  container.appendChild(
    h(
      "div",
      { class: "history__toolbar" },
      h("div", { class: "history__search" }, searchInput),
      countLabel,
    ),
  );

  container.appendChild(errorBox);
  container.appendChild(notice);
  container.appendChild(list);

  void load();

  function updateControls(): void {
    refreshButton.disabled = loading;
  }

  // ── Загрузка ───────────────────────────────────────────────────

  async function load(refresh = false): Promise<void> {
    const current = ++requestSeq;
    loading = true;
    errorBox.hidden = true;
    updateControls();

    clear(list);
    list.appendChild(skeleton("table", 6));

    try {
      const params = new URLSearchParams();
      if (query) params.set("q", query);
      if (refresh) params.set("refresh", "1");
      const data = await apiGet<FolderList>(`/api/folders?${params.toString()}`);

      if (cancelled || current !== requestSeq) return;
      render(data);
    } catch (error) {
      if (cancelled || current !== requestSeq) return;

      const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
      errorBox.textContent = message;
      errorBox.hidden = false;
      countLabel.textContent = "";
      notice.hidden = true;
      clear(list);
      list.appendChild(
        emptyState({
          icon: "alert",
          title: t("Не удалось загрузить папки"),
          hint: message,
          action: { label: t("Повторить"), onClick: () => void load() },
        }),
      );
      toast(t("Ошибка загрузки папок"), "danger");
      logEvent(`Ошибка поиска папок: ${message}`);
    } finally {
      if (current === requestSeq) {
        loading = false;
        updateControls();
      }
    }
  }

  function render(data: FolderList): void {
    clear(list);
    notice.hidden = !data.truncated;

    if (data.truncated) {
      notice.textContent = t(
        "Поиск ограничен по времени и глубине — уточните запрос, если нужной папки нет.",
      );
    }

    if (data.items.length === 0) {
      list.appendChild(
        emptyState({
          icon: "folders",
          title: query ? t("Ничего не найдено") : t("Папок нет"),
          hint: query
            ? t("По запросу «{query}» совпадений нет.", { query })
            : t("Стандартные папки не найдены в профиле пользователя."),
        }),
      );
      countLabel.textContent = query ? t("найдено 0 по «{query}»", { query }) : "";
      return;
    }

    list.appendChild(buildTable(data.items));

    if (!query) {
      countLabel.textContent = t("стандартных папок: {count}", { count: data.total });
    } else if (data.total > data.items.length) {
      countLabel.textContent = t("показаны {shown} из {total} по «{query}»", {
        shown: data.items.length,
        total: data.total,
        query,
      });
    } else {
      countLabel.textContent = t("найдено {count} по «{query}»", {
        count: data.total,
        query,
      });
    }
  }

  function buildTable(items: FolderInfo[]): HTMLElement {
    const head = h(
      "thead",
      {},
      h(
        "tr",
        {},
        h("th", { text: t("Папка") }),
        h("th", { text: t("Путь") }),
        h("th", { text: t("Изменена") }),
        h("th", { text: t("Совпадение") }),
        h("th", { text: "" }),
      ),
    );

    const body = h(
      "tbody",
      {},
      ...items.map((item) =>
        h(
          "tr",
          {},
          h(
            "td",
            {},
            h("div", { class: "row-actions" }, h("span", { text: item.name })),
          ),
          h("td", { class: "table--mono", text: item.path, title: item.parent }),
          h("td", { text: formatModified(item.modified) }),
          h("td", {}, badge(t(REASON_LABELS[item.reason] ?? "совпадение"), reasonTone(item.reason))),
          h(
            "td",
            {},
            h(
              "div",
              { class: "row-actions" },
              button(t("Открыть"), () => void openFolder(item), "ghost", "external"),
            ),
          ),
        ),
      ),
    );

    return h("table", { class: "table" }, head, body);
  }

  // ── Открытие ───────────────────────────────────────────────────

  async function openFolder(item: FolderInfo): Promise<void> {
    if (opening) return;
    opening = true;

    try {
      const result = await apiPost<FolderOpenResult>("/api/folders/open", {
        path: item.path,
      });

      if (cancelled) return;

      if (result.opened) {
        toast(t("Открываю папку «{name}»", { name: item.name }), "ok");
        logEvent(`Папка открыта: ${item.path}`);
      } else {
        toast(result.message, "danger");
        logEvent(`Не удалось открыть папку: ${item.path}`);
      }
    } catch (error) {
      if (cancelled) return;

      const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
      toast(t("Не удалось открыть папку: {message}", { message }), "danger");
      logEvent(`Ошибка открытия папки: ${message}`);
    } finally {
      opening = false;
    }
  }

  return () => {
    cancelled = true;
    window.clearTimeout(searchTimer);
  };
};

function reasonTone(reason: string): "plain" | "accent" | "ok" | "warn" {
  if (reason === "exact") return "ok";
  if (reason === "prefix" || reason === "words") return "accent";
  if (reason === "fuzzy" || reason === "path") return "warn";
  return "plain";
}

function formatModified(value: string | null): string {
  if (!value) return "—";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";

  return date.toLocaleString(lang() === "en" ? "en-US" : "ru-RU", {
    dateStyle: "short",
    timeStyle: "short",
  });
}
