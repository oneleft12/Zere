/**
 * Экран «Настройки» (§6): чтение/запись /api/config строгой полной
 * схемой (все 10 ключей, additionalProperties: false), валидация —
 * на сервере; здесь только граничные проверки для удобства.
 */

import { ApiError, apiGet, apiPost, type Config, type Health } from "../api";
import { logEvent } from "../events";
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

export const settingsScreen: ScreenFactory = (container): Cleanup => {
  let cancelled = false;

  container.appendChild(loadingRow("Загрузка конфигурации…"));

  const load = async (): Promise<void> => {
    if (cancelled) return;
    clear(container);
    container.appendChild(loadingRow("Загрузка конфигурации…"));

    try {
      const [config, health] = await Promise.all([
        apiGet<Config>("/api/config"),
        apiGet<Health>("/api/health").catch(() => null),
      ]);

      if (cancelled) return;
      render({ base: config, draft: clone(config) }, health);
    } catch (error) {
      if (cancelled) return;
      clear(container);
      container.appendChild(
        emptyState({
          icon: "⚠️",
          title: "Не удалось загрузить конфигурацию",
          hint: error instanceof ApiError ? error.message : "Неизвестная ошибка",
          action: { label: "Повторить", onClick: () => void load() },
        }),
      );
    }
  };

  function render(state: State, health: Health | null): void {
    clear(container);

    const saveBtn = button("Сохранить", () => void save(), "primary");
    const revertBtn = button("Отменить изменения", () => {
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

        toast("Конфигурация сохранена", "ok");
        logEvent("Настройки сохранены в config/config.json");
        render(state, health);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Неизвестная ошибка";
        errorBox.textContent = `Сервер отклонил конфигурацию: ${message}`;
        errorBox.hidden = false;
        toast("Ошибка сохранения настроек", "danger");
        logEvent("Ошибка сохранения настроек");
        saveBtn.disabled = false;
      }
    }

    const d = state.draft;

    container.append(
      pageHeader(
        "Настройки",
        "Конфигурация config/config.json — строгая схема, валидация на сервере",
        [revertBtn, saveBtn],
      ),
      errorBox,
    );

    const grid = h("div", { class: "grid-12 fade-in" });
    container.appendChild(grid);

    // ── Ассистент ────────────────────────────────────────────────
    const assistantCard = card(
      "Ассистент",
      h(
        "div",
        { class: "form-grid" },
        field(
          "Имя ассистента",
          textInput({
            value: d.assistantName,
            onInput: (v) => {
              d.assistantName = v;
              updateDirty();
            },
          }),
        ),
        field(
          "Язык",
          textInput({
            value: d.language,
            placeholder: "ru",
            onInput: (v) => {
              d.language = v;
              updateDirty();
            },
          }),
          "Двухбуквенный код: ru, en",
        ),
        field(
          "Модель Ollama",
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
          "Таймаут Ollama, мин",
          textInput({
            value: String(d.ollamaTimeoutMinutes),
            type: "number",
            onInput: (v) => {
              d.ollamaTimeoutMinutes = Number(v);
              updateDirty();
            },
          }),
          "От 1 до 120 минут",
        ),
      ),
    );
    assistantCard.classList.add("col-6");

    // ── Голос ────────────────────────────────────────────────────
    const voiceCard = card(
      "Голос",
      h(
        "div",
        { class: "form-grid form-grid--single" },
        toggle({
          label: "Голосовой вывод включён",
          checked: d.voiceEnabled,
          onChange: (v) => {
            d.voiceEnabled = v;
            updateDirty();
          },
        }),
        field(
          "Громкость",
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
          "TTS-движок",
          select({
            value: d.ttsEngine,
            options: [
              { value: "pocket", label: "pocket — клонирование голоса" },
              { value: "piper", label: "piper — быстрый, без клонирования" },
            ],
            onChange: (v) => {
              d.ttsEngine = v as Config["ttsEngine"];
              updateDirty();
            },
          }),
        ),
        field(
          "Референс голоса (WAV)",
          textInput({
            value: d.voiceReferencePath,
            mono: true,
            placeholder: "путь к WAV-референсу, пусто = встроенный голос",
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
      "Память",
      h(
        "div",
        { class: "form-grid form-grid--single" },
        toggle({
          label: "Автоизвлечение фактов из диалога",
          checked: d.autoMemory,
          onChange: (v) => {
            d.autoMemory = v;
            updateDirty();
          },
        }),
      ),
    );
    memoryCard.classList.add("col-6");

    // ── О программе ──────────────────────────────────────────────
    const aboutCard = card(
      "О программе",
      keyValue([
        { key: "Версия", value: health?.version ?? "—" },
        { key: "Ветка", value: health?.branch ?? "—" },
        { key: "Схема конфига", value: `v${d.version}` },
        { key: "Файл", value: "config/config.json" },
        { key: "API-контракт", value: "docs/api/openapi.yaml" },
      ]),
    );
    aboutCard.classList.add("col-6");

    grid.appendChild(assistantCard);
    grid.appendChild(voiceCard);
    grid.appendChild(memoryCard);
    grid.appendChild(aboutCard);

    updateDirty();
  }

  void load();

  return () => {
    cancelled = true;
  };
};
