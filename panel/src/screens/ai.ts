/**
 * Экран «Подключение ИИ»: свой API-ключ или локальная модель.
 *
 * Логика полностью на бэкенде (docs/AI_PROVIDERS.md):
 * - ключ проверяется рабочим запросом к API перед сохранением;
 * - наружу отдаётся только маска вида `sk-...abcd` — полный ключ в
 *   клиентский код и в интерфейс не попадает (поле ввода всегда пустое);
 * - состояние (`/api/ai`) говорит, кто отвечает: облако, локальная модель
 *   или никто (тогда чат попросит всё настроить).
 */

import {
  ApiError,
  apiDelete,
  apiGet,
  apiPost,
  apiSse,
  aiSupport,
  type AiKeyTestResult,
  type AiLocalTestResult,
  type AiMode,
  type AiSettingsUpdate,
  type AiStatus,
} from "../api";
import { logEvent } from "../events";
import { t } from "../i18n";
import {
  badge,
  button,
  card,
  clear,
  emptyState,
  field,
  h,
  keyValue,
  skeleton,
  pageHeader,
  select,
  statusPill,
  textInput,
  toast,
} from "../ui";
import { navigate, type Cleanup, type ScreenFactory } from "../router";

interface Draft {
  mode: AiMode;
  cloudProvider: string;
  cloudBaseUrl: string;
  cloudModel: string;
  /** Введённый пользователем ключ; из состояния никогда не заполняется. */
  apiKey: string;
  localBaseUrl: string;
  localModel: string;
  /** Идёт загрузка модели — переживает перерисовку экрана. */
  pulling: boolean;
  pullPercent: number | null;
  pullDetail: string;
}

// Черновик переживает перерисовку (смена языка/темы, обновление статуса).
let cachedDraft: Draft | null = null;

/**
 * Поля, которые пользователь уже правил вручную и ещё не сохранил.
 *
 * Без этого любое обновление состояния (кнопка «Обновить состояние»,
 * «Проверить ключ», загрузка модели) пересобирало черновик из ответа
 * сервера и стирало введённое название модели или адрес — из-за этого
 * казалось, что «модель не сохраняется».
 */
type DraftField = "cloudBaseUrl" | "cloudModel" | "localBaseUrl" | "localModel";

const editedFields = new Set<DraftField>();

function markEdited(field: DraftField): void {
  editedFields.add(field);
}

function clearEdited(fields: readonly string[]): void {
  for (const field of fields) editedFields.delete(field as DraftField);
}

/** Свежий черновик из состояния сервера + несохранённые правки пользователя. */
function mergeDraft(status: AiStatus, previous: Draft | null): Draft {
  const next = draftFrom(status);
  if (!previous) return next;

  // Ключ из состояния не приходит (наружу отдаётся только маска) — введённый сохраняем.
  next.apiKey = previous.apiKey;

  if (editedFields.has("cloudBaseUrl")) next.cloudBaseUrl = previous.cloudBaseUrl;
  if (editedFields.has("cloudModel")) next.cloudModel = previous.cloudModel;
  if (editedFields.has("localBaseUrl")) next.localBaseUrl = previous.localBaseUrl;
  if (editedFields.has("localModel")) next.localModel = previous.localModel;

  return next;
}

function draftFrom(status: AiStatus): Draft {
  return {
    mode: status.mode,
    cloudProvider: status.cloud.provider,
    cloudBaseUrl: status.cloud.baseUrl,
    cloudModel: status.cloud.model,
    apiKey: "",
    localBaseUrl: status.local.baseUrl,
    localModel: status.local.model,
    pulling: false,
    pullPercent: null,
    pullDetail: "",
  };
}

function keyStatusLabel(status: AiStatus): string {
  if (!status.cloud.keySaved) return t("ключ не найден");
  if (status.cloud.keyStatus === "ok") return t("ключ сохранён и работает");
  if (status.cloud.keyStatus === "invalid") return t("ключ не работает");
  return t("ключ сохранён, не проверен");
}

function keyStatusTone(status: AiStatus): "ok" | "warn" | "danger" | "idle" {
  if (!status.cloud.keySaved) return "idle";
  if (status.cloud.keyStatus === "ok") return "ok";
  if (status.cloud.keyStatus === "invalid") return "danger";
  return "warn";
}

function localStatusTone(status: AiStatus): "ok" | "warn" | "danger" {
  if (status.local.status === "available") return "ok";
  if (status.local.status === "model-missing") return "warn";
  return "danger";
}

export const aiScreen: ScreenFactory = (container): Cleanup => {
  let cancelled = false;
  let pulling = false;
  let progressBar: HTMLElement | null = null;
  let progressText: HTMLElement | null = null;

  container.appendChild(skeleton("card", 3));

  // ── Загрузка состояния ─────────────────────────────────────────

  async function load(): Promise<void> {
    if (cancelled) return;

    try {
      const status = await apiGet<AiStatus>("/api/ai");
      if (cancelled) return;

      // Черновик сохраняем, если пользователь что-то печатал: иначе
      // введённый ключ и название модели пропадали бы при обновлении статуса.
      cachedDraft = mergeDraft(status, cachedDraft);
      render(status);
    } catch (error) {
      if (cancelled) return;
      clear(container);

      // Маршрута может не быть вовсе: панель обновилась, а сервер ZERE
      // остался старым. Вместо «Маршрут не найден» объясняем, что делать.
      const support = await aiSupport();
      if (cancelled) return;

      if (support === "restart-required") {
        container.appendChild(
          emptyState({
            icon: "refresh",
            title: t("Нужен перезапуск ZERE"),
            hint: t("Панель обновилась, а сервер ZERE работает со старым кодом: закройте и снова запустите ZERE — настройка ИИ появится."),
            action: { label: t("Повторить"), onClick: () => void load() },
          }),
        );
        return;
      }

      if (support === "unsupported") {
        container.appendChild(
          emptyState({
            icon: "info",
            title: t("В этой редакции настраивается только локальная модель"),
            hint: t("Эта сборка панели новее сервера ZERE: перезапустите ZERE, чтобы включить настройку ключа. Локальная модель (Ollama) продолжает работать — её состояние видно на главной странице."),
            action: { label: t("На главную страницу"), onClick: () => navigate("/") },
          }),
        );
        return;
      }

      container.appendChild(
        emptyState({
          icon: "alert",
          title: t("Не удалось получить состояние ИИ"),
          hint: error instanceof ApiError ? error.message : t("Неизвестная ошибка"),
          action: { label: t("Повторить"), onClick: () => void load() },
        }),
      );
    }
  }

  function showError(errorBox: HTMLElement, error: unknown, prefix: string): void {
    const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
    errorBox.textContent = `${prefix}: ${message}`;
    errorBox.hidden = false;
    toast(message, "danger");
    logEvent(`${prefix}: ${message}`);
  }

  // ── Действия ───────────────────────────────────────────────────

  async function saveSettings(
    draft: Draft,
    patch: AiSettingsUpdate,
    errorBox: HTMLElement,
    successMessage: string,
  ): Promise<void> {
    try {
      const status = await apiPost<AiStatus>("/api/ai/settings", patch);
      // Настройки приняты сервером: эти поля больше не «не сохранены».
      clearEdited(Object.keys(patch));
      Object.assign(draft, draftFrom(status), { apiKey: draft.apiKey });
      toast(successMessage, "ok");
      logEvent(successMessage);
      render(status);
    } catch (error) {
      showError(errorBox, error, t("Сервер отклонил настройки ИИ"));
    }
  }

  async function testKey(draft: Draft, errorBox: HTMLElement): Promise<void> {
    errorBox.hidden = true;

    const body: Record<string, unknown> = {
      cloudProvider: draft.cloudProvider,
      cloudBaseUrl: draft.cloudBaseUrl,
      cloudModel: draft.cloudModel,
    };
    if (draft.apiKey.trim()) body.apiKey = draft.apiKey.trim();

    try {
      const result = await apiPost<AiKeyTestResult>("/api/ai/key/test", body);
      toast(`${t("Ключ рабочий")}: ${result.message}`, "ok");
      logEvent(`Проверка ключа: ок (${result.checkedWith})`);
      await load();
    } catch (error) {
      showError(errorBox, error, t("Ключ не прошёл проверку"));
    }
  }

  async function saveKey(draft: Draft, status: AiStatus, errorBox: HTMLElement): Promise<void> {
    errorBox.hidden = true;

    // Поле ключа пустое, а ключ уже сохранён: пользователь правит только
    // модель или адрес. Раньше здесь была ошибка «Введите API-ключ.», и
    // название модели не сохранялось.
    if (!draft.apiKey.trim()) {
      if (status.cloud.keySaved) {
        await saveSettings(
          draft,
          {
            cloudProvider: draft.cloudProvider,
            cloudBaseUrl: draft.cloudBaseUrl,
            cloudModel: draft.cloudModel,
          },
          errorBox,
          t("Облачная модель сохранена"),
        );
        return;
      }

      errorBox.textContent = t("Введите API-ключ.");
      errorBox.hidden = false;
      return;
    }

    try {
      const status = await apiPost<AiStatus>("/api/ai/key", {
        apiKey: draft.apiKey.trim(),
        cloudProvider: draft.cloudProvider,
        cloudBaseUrl: draft.cloudBaseUrl,
        cloudModel: draft.cloudModel,
      });
      // Ключ ушёл на бэкенд: поле ввода очищаем, в интерфейсе — только маска.
      draft.apiKey = "";
      clearEdited(["cloudBaseUrl", "cloudModel"]);
      Object.assign(draft, draftFrom(status));
      toast(t("API-ключ сохранён"), "ok");
      logEvent("API-ключ проверен и сохранён на бэкенде");
      render(status);
    } catch (error) {
      showError(errorBox, error, t("Ключ не сохранён"));
    }
  }

  async function deleteKey(draft: Draft, errorBox: HTMLElement): Promise<void> {
    errorBox.hidden = true;

    try {
      const status = await apiDelete<AiStatus>("/api/ai/key");
      draft.apiKey = "";
      clearEdited(["cloudBaseUrl", "cloudModel"]);
      Object.assign(draft, draftFrom(status));
      toast(t("API-ключ удалён"), "ok");
      logEvent("API-ключ удалён");
      render(status);
    } catch (error) {
      showError(errorBox, error, t("Не удалось удалить ключ"));
    }
  }

  async function testLocal(draft: Draft, errorBox: HTMLElement): Promise<void> {
    errorBox.hidden = true;

    try {
      const result = await apiPost<AiLocalTestResult>("/api/ai/local/test", {
        localBaseUrl: draft.localBaseUrl,
        localModel: draft.localModel,
      });
      toast(result.message, "ok");
      logEvent(`Проверка локальной модели: ${result.message}`);
      await load();
    } catch (error) {
      showError(errorBox, error, t("Локальная модель не ответила"));
    }
  }

  async function pullModel(draft: Draft, errorBox: HTMLElement, model: string): Promise<void> {
    if (pulling) return;

    pulling = true;
    draft.pulling = true;
    draft.pullPercent = null;
    draft.pullDetail = t("Готовлю загрузку…");
    errorBox.hidden = true;
    renderProgress();
    logEvent(`Загрузка локальной модели: ${model}`);

    try {
      await apiSse(`/api/ai/local/pull?model=${encodeURIComponent(model)}`, {
        onEvent: (event, data) => {
          const body = (data ?? {}) as {
            percent?: number | null;
            detail?: string;
            message?: string;
            code?: string;
          };

          if (event === "progress") {
            draft.pullPercent = typeof body.percent === "number" ? body.percent : null;
            draft.pullDetail = body.detail ?? "";
            renderProgress();
          } else if (event === "error") {
            errorBox.textContent = `${t("Загрузка не удалась")}: ${body.message ?? body.code ?? ""}`;
            errorBox.hidden = false;
            toast(body.message ?? t("Загрузка не удалась"), "danger");
          }
        },
      });
    } catch (error) {
      showError(errorBox, error, t("Загрузка не удалась"));
    } finally {
      pulling = false;
      draft.pulling = false;
      await load();
    }
  }

  // ── Рендер ─────────────────────────────────────────────────────

  function renderProgress(): void {
    const draft = cachedDraft;
    if (!draft) return;

    if (progressBar) {
      progressBar.style.width = `${draft.pullPercent ?? 0}%`;
    }
    if (progressText) {
      progressText.textContent =
        draft.pullPercent === null
          ? draft.pullDetail
          : `${draft.pullDetail} — ${draft.pullPercent}%`;
    }
  }

  function render(status: AiStatus): void {
    if (cancelled) return;

    const draft = cachedDraft ?? draftFrom(status);
    cachedDraft = draft;

    clear(container);
    progressBar = null;
    progressText = null;

    const refreshBtn = button(t("Обновить состояние"), () => void load(), "default", "refresh");
    const errorBox = h("div", { class: "form-error", hidden: true });

    container.append(
      pageHeader(
        t("Подключение ИИ"),
        t("Свой API-ключ или локальная модель — что использовать для ответов"),
        [refreshBtn],
      ),
      errorBox,
    );

    const grid = h("div", { class: "grid-12 fade-in" });
    container.appendChild(grid);

    // ── Состояние подключения (требование 1) ─────────────────────
    const statusCard = card(
      t("Состояние подключения"),
      h(
        "div",
        { class: "ai-status" },
        statusPill({
          label: t("ИИ"),
          value: status.summary,
          state: status.activeProvider === "none" ? "danger" : "ok",
        }),
        h("p", { class: "panel-note", text: status.message }),
        keyValue([
          { key: t("Режим"), value: modeLabel(status.mode) },
          { key: t("Отвечает"), value: activeLabel(status.activeProvider) },
          { key: t("Файл настроек"), value: status.settingsPath },
        ]),
      ),
    );
    statusCard.classList.add("col-12");

    // ── Режим (требование 10) ────────────────────────────────────
    const modeCard = card(
      t("Как использовать ИИ"),
      h(
        "div",
        { class: "form-grid form-grid--single" },
        field(
          t("Режим"),
          select({
            value: draft.mode,
            options: [
              { value: "auto", label: t("Авто — сначала API-ключ, иначе локальная модель") },
              { value: "cloud", label: t("Использовать свой API-ключ") },
              { value: "local", label: t("Использовать локальную модель") },
            ],
            onChange: (value) => {
              draft.mode = value as AiMode;
              void saveSettings(draft, { mode: draft.mode }, errorBox, t("Режим ИИ сохранён"));
            },
          }),
        ),
        h("p", {
          class: "panel-note",
          text: t("«Авто» удобен по умолчанию: ключ есть — идём в облако, нет — считаем локально."),
        }),
      ),
    );
    modeCard.classList.add("col-12");

    grid.append(statusCard, modeCard, cloudCard(status, draft, errorBox), localCard(status, draft, errorBox));

    // ── Блок «локальная модель не найдена» (требование 8) ────────
    if (status.local.installHint && status.local.status !== "available") {
      const hintCard = installHintCard(status, draft, errorBox);
      grid.appendChild(hintCard);
    }
  }

  function modeLabel(mode: AiMode): string {
    if (mode === "cloud") return t("только облачный ключ");
    if (mode === "local") return t("только локальная модель");
    return t("авто");
  }

  function activeLabel(active: AiStatus["activeProvider"]): string {
    if (active === "cloud") return t("облачная модель");
    if (active === "local") return t("локальная модель");
    return t("никто — ИИ не настроен");
  }

  // ── Облачная модель ───────────────────────────────────────────

  function cloudCard(status: AiStatus, draft: Draft, errorBox: HTMLElement): HTMLElement {
    const presets = status.presets;
    const preset = presets.find((item) => item.id === draft.cloudProvider);

    const docsHint = preset?.docsUrl
      ? h(
          "span",
          { class: "field__hint" },
          t("Ключ можно получить здесь: "),
          h("a", { href: preset.docsUrl, text: preset.docsUrl }),
        )
      : undefined;

    const keyInput = textInput({
      value: draft.apiKey,
      type: "password",
      mono: true,
      placeholder: status.cloud.keySaved ? status.cloud.keyMask : "sk-…",
      onInput: (value) => {
        draft.apiKey = value;
      },
    });

    const keyState = statusPill({
      label: t("Ключ"),
      value: keyStatusLabel(status),
      state: keyStatusTone(status),
    });

    const testKeyButton = button(t("Проверить ключ"), () => void testKey(draft, errorBox), "default", "shield");
    const saveKeyButton = button(
      t("Сохранить ключ"),
      () => void saveKey(draft, status, errorBox),
      "primary",
    );
    // Отдельная кнопка для модели и адреса: их сохранение не должно
    // требовать повторного ввода ключа (раньше без ключа правка пропадала).
    const saveModelButton = button(t("Сохранить адрес и модель"), () =>
      void saveSettings(
        draft,
        {
          cloudProvider: draft.cloudProvider,
          cloudBaseUrl: draft.cloudBaseUrl,
          cloudModel: draft.cloudModel,
        },
        errorBox,
        t("Облачная модель сохранена"),
      ),
    );
    const deleteKeyButton = button(
      t("Удалить ключ"),
      () => void deleteKey(draft, errorBox),
      "danger",
    );
    // «Удалить ключ» активна только когда ключ пользователя действительно есть.
    deleteKeyButton.disabled = !status.cloud.keySaved;

    const section = h(
      "section",
      { class: "card col-6" },
      h("h3", { class: "card__title", text: t("Свой API-ключ (облачная модель)") }),
      h(
        "div",
        { class: "form-grid" },
        field(
          t("Провайдер"),
          select({
            value: draft.cloudProvider,
            options: presets.map((item) => ({ value: item.id, label: item.label })),
            onChange: (value) => {
              const next = presets.find((item) => item.id === value);
              draft.cloudProvider = value;
              if (next && next.baseUrl) {
                draft.cloudBaseUrl = next.baseUrl;
                draft.cloudModel = next.model;
              }
              void saveSettings(
                draft,
                {
                  cloudProvider: draft.cloudProvider,
                  ...(next && next.baseUrl
                    ? { cloudBaseUrl: next.baseUrl, cloudModel: next.model }
                    : {}),
                },
                errorBox,
                t("Провайдер сохранён"),
              );
            },
          }),
        ),
        field(
          t("Base URL"),
          textInput({
            value: draft.cloudBaseUrl,
            mono: true,
            placeholder: "https://api.openai.com/v1",
            onInput: (value) => {
              draft.cloudBaseUrl = value;
              markEdited("cloudBaseUrl");
            },
          }),
        ),
        field(
          t("Модель"),
          textInput({
            value: draft.cloudModel,
            mono: true,
            placeholder: "gpt-4o-mini",
            onInput: (value) => {
              draft.cloudModel = value;
              markEdited("cloudModel");
            },
          }),
          t("Название модели сохраняется кнопкой «Сохранить адрес и модель» — ключ заново вводить не нужно"),
        ),
        field(t("API-ключ"), keyInput, t("Ключ хранится только на бэкенде и никогда не выводится целиком")),
        docsHint ?? null,
      ),
      h(
        "div",
        { class: "pill-row" },
        testKeyButton,
        saveKeyButton,
        saveModelButton,
        deleteKeyButton,
      ),
      h(
        "div",
        { class: "ai-status" },
        keyState,
        keyValue([
          { key: t("Маска"), value: status.cloud.keyMask || "—" },
          { key: t("Источник"), value: keySourceLabel(status.cloud.keySource) },
          { key: t("Проверен"), value: status.cloud.keyCheckedAt ?? "—" },
        ]),
        status.cloud.keySource === "owner"
          ? h("p", {
              class: "panel-note",
              text: t("Используется ключ владельца из переменных окружения сервера — его нельзя удалить из панели."),
            })
          : null,
        h("p", {
          class: "panel-note",
          text: t("Проверка ключа — рабочий запрос: список моделей, при необходимости минимальный запрос к чату."),
        }),
      ),
    );

    return section;
  }

  function keySourceLabel(source: AiStatus["cloud"]["keySource"]): string {
    if (source === "user") return t("свой ключ (config/ai.json)");
    if (source === "owner") return t("ключ владельца (окружение сервера)");
    return t("нет");
  }

  // ── Локальная модель ──────────────────────────────────────────

  function localCard(status: AiStatus, draft: Draft, errorBox: HTMLElement): HTMLElement {
    const suggestions = status.local.suggestions;
    const modelsText =
      status.local.models.length > 0 ? status.local.models.slice(0, 5).join(", ") : "—";

    // Прогресс-бар живёт до перерисовки: ссылки нужны для обновления без
    // полного render() на каждое SSE-событие.
    progressBar = h("div", { class: "progress__bar" });
    progressText = h("div", { class: "progress__text", text: draft.pullDetail });

    const pullButton = button(
      t("Скачать модель"),
      () => void pullModel(draft, errorBox, draft.localModel),
      "primary",
    );
    pullButton.disabled = !status.local.canPull || draft.pulling;

    const progress = h(
      "div",
      { class: "progress-block", hidden: !draft.pulling },
      progressBar,
      progressText,
    );

    if (draft.pulling) {
      window.requestAnimationFrame(() => renderProgress());
    }

    const section = h(
      "section",
      { class: "card col-6" },
      h("h3", { class: "card__title", text: t("Локальная модель (Ollama или свой сервер)") }),
      h(
        "div",
        { class: "form-grid" },
        field(
          t("Адрес локального сервера"),
          textInput({
            value: draft.localBaseUrl,
            mono: true,
            placeholder: "http://127.0.0.1:11434/v1",
            onInput: (value) => {
              draft.localBaseUrl = value;
              markEdited("localBaseUrl");
            },
          }),
          t("Ollama по умолчанию: http://127.0.0.1:11434/v1"),
        ),
        field(
          t("Модель"),
          textInput({
            value: draft.localModel,
            mono: true,
            placeholder: "t-tech/T-lite-it-2.1:q4_K_M",
            onInput: (value) => {
              draft.localModel = value;
              markEdited("localModel");
            },
          }),
        ),
        field(
          t("Лёгкая модель для слабого ПК"),
          select({
            value: draft.localModel,
            options: [
              { value: draft.localModel, label: t("оставить текущую: {model}", { model: draft.localModel }) },
              ...suggestions.map((item) => ({
                value: item.id,
                label: `${item.label} · ${item.sizeHint}`,
              })),
            ],
            onChange: (value) => {
              if (value === draft.localModel) return;
              draft.localModel = value;
              void saveSettings(
                draft,
                { localModel: value },
                errorBox,
                t("Локальная модель сохранена"),
              );
            },
          }),
          t("По умолчанию предлагаются модели 0.5B–3B: тяжёлые не нужны слабому ПК"),
        ),
      ),
      h(
        "div",
        { class: "pill-row" },
        button(t("Проверить локальную модель"), () => void testLocal(draft, errorBox), "default", "shield"),
        button(
          t("Сохранить адрес и модель"),
          () =>
            void saveSettings(
              draft,
              { localBaseUrl: draft.localBaseUrl, localModel: draft.localModel },
              errorBox,
              t("Настройки локальной модели сохранены"),
            ),
        ),
        pullButton,
      ),
      progress,
      h(
        "div",
        { class: "ai-status" },
        statusPill({ label: t("Сервер"), value: status.local.statusText, state: localStatusTone(status) }),
        keyValue([
          { key: t("Сервер"), value: status.local.server === "up" ? t("запущен") : t("не запущен") },
          { key: t("API"), value: status.local.api || "—" },
          {
            key: t("Нужная модель"),
            value: status.local.modelInstalled ? t("загружена") : t("не загружена"),
          },
          { key: t("Найдено моделей"), value: modelsText },
        ]),
        h("p", { class: "panel-note", text: status.local.detail }),
      ),
    );

    return section;
  }

  // ── Инструкция по установке (требование 8) ────────────────────

  function installHintCard(status: AiStatus, draft: Draft, errorBox: HTMLElement): HTMLElement {
    const hint = status.local.installHint;
    if (!hint) return h("section", { class: "card col-12" });

    const steps = h("ol", { class: "hint-steps" });
    for (const step of hint.steps) {
      steps.appendChild(h("li", { text: step }));
    }

    const copyButton = button(
      t("Скопировать команду"),
      () => {
        void copyText(hint.command);
      },
      "default",
      "copy",
    );

    return h(
      "section",
      { class: "card col-12 card--warn" },
      h("h3", { class: "card__title", text: t(hint.title) }),
      steps,
      h(
        "div",
        { class: "code-line" },
        h("code", { text: hint.command }),
        copyButton,
      ),
      h(
        "div",
        { class: "pill-row" },
        h("a", { class: "btn", href: hint.downloadUrl, text: t("Скачать Ollama") }),
        button(t("Проверить локальную модель"), () => void testLocal(draft, errorBox)),
        button(t("Скачать модель"), () => void pullModel(draft, errorBox, hint.model), "primary", "update"),
      ),
      h("p", {
        class: "panel-note",
        text: t("Кнопка «Скачать модель» работает, если Ollama уже запущена — прогресс появится выше."),
      }),
      badge(t("Для слабых ПК: 0.5B–1.5B, для средних: 3B–4B"), "warn"),
    );
  }

  async function copyText(text: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      toast(t("Команда скопирована"), "ok");
    } catch {
      toast(t("Скопируйте команду вручную"), "warn");
    }
  }

  void load();

  return () => {
    cancelled = true;
  };
};
