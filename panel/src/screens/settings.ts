/**
 * Экран «Настройки» (§6): чтение/запись /api/config строгой полной
 * схемой (все 10 ключей, additionalProperties: false), валидация —
 * на сервере; здесь только граничные проверки для удобства.
 */

import { ApiError, apiGet, apiPost, type Config, type Health } from "../api";
import { logEvent } from "../events";
import { lang, setLang, t, type Lang } from "../i18n";
import { currentTheme, setTheme } from "../theme";
import {
  button,
  card,
  clear,
  emptyState,
  field,
  h,
  keyValue,
  loadingRow,
  pageHeader,
  select,
  slider,
  textInput,
  toast,
  toggle,
} from "../ui";
import type { Cleanup, ScreenFactory } from "../router";

interface State {
  base: Config;
  draft: Config;
}

function clone(config: Config): Config {
  return { ...config };
}

function isValid(draft: Config): boolean {
  return (
    Number.isFinite(draft.ollamaTimeoutMinutes) &&
    draft.ollamaTimeoutMinutes >= 1 &&
    draft.ollamaTimeoutMinutes <= 120 &&
    draft.voiceVolume >= 0 &&
    draft.voiceVolume <= 1
  );
}

function isDirty(state: State): boolean {
  return JSON.stringify(state.base) !== JSON.stringify(state.draft);
}

// Черновик переживает перерисовку экрана (смена языка, темы) — см. load().
let cachedState: State | null = null;

export const settingsScreen: ScreenFactory = (container): Cleanup => {
  let cancelled = false;

  container.appendChild(loadingRow(t("Загрузка конфигурации…")));

  const load = async (): Promise<void> => {
    if (cancelled) return;
    clear(container);
    container.appendChild(loadingRow(t("Загрузка конфигурации…")));

    try {
      const [config, health] = await Promise.all([
        apiGet<Config>("/api/config"),
        apiGet<Health>("/api/health").catch(() => null),
      ]);

      if (cancelled) return;

      if (cachedState && isDirty(cachedState)) {
        // Есть несохранённые правки: обновляем базу, черновик сохраняем.
        cachedState.base = config;
      } else {
        cachedState = { base: config, draft: clone(config) };
      }

      render(cachedState, health);
    } catch (error) {
      if (cancelled) return;
      clear(container);
      container.appendChild(
        emptyState({
          icon: "⚠️",
          title: t("Не удалось загрузить конфигурацию"),
          hint: error instanceof ApiError ? error.message : t("Неизвестная ошибка"),
          action: { label: t("Повторить"), onClick: () => void load() },
        }),
      );
    }
  };

  function render(state: State, health: Health | null): void {
    clear(container);

    const saveBtn = button(t("Сохранить"), () => void save(), "primary");
    const revertBtn = button(t("Отменить изменения"), () => {
      state.draft = clone(state.base);
      render(state, health);
      logEvent("Изменения настроек отброшены");
    });

    const errorBox = h("div", { class: "form-error", hidden: true });

    const updateDirty = (): void => {
      saveBtn.disabled = !isDirty(state) || !isValid(state.draft);
      revertBtn.disabled = !isDirty(state);
    };

    async function save(): Promise<void> {
      if (!isDirty(state) || !isValid(state.draft)) return;

      saveBtn.disabled = true;

      try {
        const saved = await apiPost<Config>("/api/config", state.draft);
        state.base = saved;
        state.draft = clone(saved);

        toast(t("Конфигурация сохранена"), "ok");
        logEvent("Настройки сохранены в config/config.json");
        render(state, health);
      } catch (error) {
        const message = error instanceof Error ? error.message : t("Неизвестная ошибка");
        errorBox.textContent = t("Сервер отклонил конфигурацию: {message}", { message });
        errorBox.hidden = false;
        toast(t("Ошибка сохранения настроек"), "danger");
        logEvent("Ошибка сохранения настроек");
        saveBtn.disabled = false;
      }
    }

    const d = state.draft;

    container.append(
      pageHeader(
        t("Настройки"),
        t("Конфигурация config/config.json — строгая схема, валидация на сервере"),
        [revertBtn, saveBtn],
      ),
      errorBox,
    );

    const grid = h("div", { class: "grid-12 fade-in" });
    container.appendChild(grid);

    // ── Ассистент ────────────────────────────────────────────────
    const assistantCard = card(
      t("Ассистент"),
      h(
        "div",
        { class: "form-grid" },
        field(
          t("Имя ассистента"),
          textInput({
            value: d.assistantName,
            onInput: (v) => {
              d.assistantName = v;
              updateDirty();
            },
          }),
        ),
        field(
          t("Язык"),
          textInput({
            value: d.language,
            placeholder: "ru",
            onInput: (v) => {
              d.language = v;
              updateDirty();
            },
          }),
          t("Двухбуквенный код: ru, en"),
        ),
        field(
          t("Модель Ollama"),
          textInput({
            value: d.model,
            mono: true,
            placeholder: "qwen3.5:2b",
            onInput: (v) => {
              d.model = v;
              updateDirty();
            },
          }),
        ),
        field(
          t("Таймаут Ollama, мин"),
          textInput({
            value: String(d.ollamaTimeoutMinutes),
            type: "number",
            onInput: (v) => {
              d.ollamaTimeoutMinutes = Number(v);
              updateDirty();
            },
          }),
          t("От 1 до 120 минут"),
        ),
      ),
    );
    assistantCard.classList.add("col-6");

    // ── Голос ────────────────────────────────────────────────────
    const voiceCard = card(
      t("Голос"),
      h(
        "div",
        { class: "form-grid form-grid--single" },
        toggle({
          label: t("Голосовой вывод включён"),
          checked: d.voiceEnabled,
          onChange: (v) => {
            d.voiceEnabled = v;
            updateDirty();
          },
        }),
        field(
          t("Громкость"),
          slider({
            value: d.voiceVolume,
            min: 0,
            max: 1,
            step: 0.05,
            onChange: (v) => {
              d.voiceVolume = v;
              updateDirty();
            },
          }),
        ),
        field(
          t("TTS-движок"),
          select({
            value: d.ttsEngine,
            options: [
              { value: "pocket", label: t("pocket — клонирование голоса") },
              { value: "piper", label: t("piper — быстрый, без клонирования") },
            ],
            onChange: (v) => {
              d.ttsEngine = v as Config["ttsEngine"];
              updateDirty();
            },
          }),
        ),
        field(
          t("Референс голоса (WAV)"),
          textInput({
            value: d.voiceReferencePath,
            mono: true,
            placeholder: t("путь к WAV-референсу, пусто = встроенный голос"),
            onInput: (v) => {
              d.voiceReferencePath = v;
              updateDirty();
            },
          }),
        ),
      ),
    );
    voiceCard.classList.add("col-6");

    // ── Память ───────────────────────────────────────────────────
    const memoryCard = card(
      t("Память"),
      h(
        "div",
        { class: "form-grid form-grid--single" },
        toggle({
          label: t("Автоизвлечение фактов из диалога"),
          checked: d.autoMemory,
          onChange: (v) => {
            d.autoMemory = v;
            updateDirty();
          },
        }),
      ),
    );
    memoryCard.classList.add("col-6");

    // ── Оформление (этап 5: светлая тема, язык интерфейса) ───────
    const appearanceCard = card(
      t("Оформление"),
      h(
        "div",
        { class: "form-grid form-grid--single" },
        toggle({
          label: t("Светлая тема"),
          checked: currentTheme() === "light",
          onChange: (v) => {
            setTheme(v ? "light" : "dark");
            logEvent(`Тема переключена: ${v ? "светлая" : "тёмная"}`);
          },
        }),
        field(
          t("Язык интерфейса"),
          select({
            value: lang(),
            options: [
              { value: "ru", label: "Русский" },
              { value: "en", label: "English" },
            ],
            // Смена языка перерисовывает экран (main.ts слушает onLangChange).
            onChange: (v) => setLang(v as Lang),
          }),
          t("Смена применяется сразу"),
        ),
        h("p", {
          class: "panel-note",
          text: t("Тёмная тема — по умолчанию. CSS-анимации автоматически "
            + "сокращаются при системной настройке «уменьшить движение»."),
        }),
      ),
    );
    appearanceCard.classList.add("col-6");

    // ── О программе ──────────────────────────────────────────────
    const aboutCard = card(
      t("О программе"),
      keyValue([
        { key: t("Версия"), value: health?.version ?? "—" },
        { key: t("Ветка"), value: health?.branch ?? "—" },
        { key: t("Схема конфига"), value: `v${d.version}` },
        { key: t("Файл"), value: "config/config.json" },
        { key: t("API-контракт"), value: "docs/api/openapi.yaml" },
      ]),
    );
    aboutCard.classList.add("col-6");

    grid.appendChild(assistantCard);
    grid.appendChild(voiceCard);
    grid.appendChild(memoryCard);
    grid.appendChild(appearanceCard);
    grid.appendChild(aboutCard);

    updateDirty();
  }

  void load();

  return () => {
    cancelled = true;
  };
};
