/**
 * Экран «Настройки» (§6): чтение/запись /api/config строгой полной
 * схемой (все 10 ключей, additionalProperties: false), валидация —
 * на сервере; здесь только граничные проверки для удобства.
 */

import {
  ApiError,
  apiGet,
  apiPost,
  type AutostartStatus,
  type Config,
  type Health,
} from "../api";
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
  skeleton,
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
  /** Автозапуск вместе с Windows; null — бэкенд не знает маршрута. */
  autostart: AutostartStatus | null;
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

  container.appendChild(skeleton("card", 4));

  const load = async (): Promise<void> => {
    if (cancelled) return;
    clear(container);
    container.appendChild(skeleton("card", 4));

    try {
      const [config, health, autostart] = await Promise.all([
        apiGet<Config>("/api/config"),
        apiGet<Health>("/api/health").catch(() => null),
        // Старая сборка (C#-редакция) маршрута не знает — карточку не
        // показываем, вместо «Маршрут не найден» на весь экран.
        apiGet<AutostartStatus>("/api/autostart").catch(() => null),
      ]);

      if (cancelled) return;

      if (cachedState && isDirty(cachedState)) {
        // Есть несохранённые правки: обновляем базу, черновик сохраняем.
        cachedState.base = config;
        cachedState.autostart = autostart;
      } else {
        cachedState = { base: config, draft: clone(config), autostart };
      }

      render(cachedState, health);
    } catch (error) {
      if (cancelled) return;
      clear(container);
      container.appendChild(
        emptyState({
          icon: "alert",
          title: t("Не удалось загрузить конфигурацию"),
          hint: error instanceof ApiError ? error.message : t("Неизвестная ошибка"),
          action: { label: t("Повторить"), onClick: () => void load() },
        }),
      );
    }
  };

  function render(state: State, health: Health | null): void {
    clear(container);

    const saveBtn = button(t("Сохранить"), () => void save(), "primary", "check");
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

    /**
     * Автозапуск применяется сразу, вне черновика конфигурации: его
     * состояние живёт в реестре Windows (HKCU\...\Run), а не в config.json.
     * После ответа карточка перерисовывается из настоящего состояния —
     * включённый переключатель никогда не врёт.
     */
    async function applyAutostart(target: HTMLInputElement, enabled: boolean): Promise<void> {
      target.disabled = true;

      try {
        state.autostart = await apiPost<AutostartStatus>("/api/autostart", { enabled });
        toast(t(enabled ? "Автозапуск включён" : "Автозапуск отключён"), "ok");
        logEvent(enabled ? "Автозапуск ZERE включён" : "Автозапуск ZERE отключён");
      } catch (error) {
        const message = error instanceof Error ? error.message : t("Неизвестная ошибка");
        toast(t("Не удалось изменить автозапуск: {message}", { message }), "danger");
        logEvent("Ошибка изменения автозапуска");
      }

      render(state, health);
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
          t("Язык ассистента"),
          select({
            value: d.language,
            options: [
              { value: "ru", label: t("русский") },
              { value: "en", label: t("английский") },
            ],
            onChange: (v) => {
              d.language = v;
              updateDirty();
            },
          }),
          t("Язык ответов ассистента: смена действует сразу, без перезапуска"),
        ),
        field(
          t("Модель Ollama"),
          textInput({
            value: d.model,
            mono: true,
            placeholder: "t-tech/T-lite-it-2.1:q4_K_M",
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
              { value: "silero", label: t("silero — русский голос: ударения, цифры и английские слова") },
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

    // ── Запуск вместе с Windows ──────────────────────────────────
    // Состояние читается из реестра (GET /api/autostart), переключатель
    // применяется сразу и не ждёт кнопки «Сохранить» — в config.json этого
    // ключа нет. Старая сборка (C#) маршрута не знает: state.autostart ===
    // null — карточки нет, остальные настройки работают как раньше.
    let autostartCard: HTMLElement | null = null;
    if (state.autostart) {
      const a = state.autostart;
      const autostartToggle = toggle({
        label: t("Запускать ZERE при входе в систему"),
        checked: a.enabled,
        onChange: (checked) => {
          if (autostartInput) void applyAutostart(autostartInput, checked);
        },
      });
      const autostartInput = autostartToggle.querySelector<HTMLInputElement>("input");
      if (autostartInput) autostartInput.disabled = !a.supported;

      const command = a.command || a.expectedCommand;
      const commandInput = textInput({ value: command, mono: true });
      commandInput.readOnly = true;

      const note = !a.supported
        ? t("Автозапуск вместе с Windows доступен только в Windows.")
        : a.reason
          ? a.reason
          : a.outdated
            ? t("В автозапуске записан старый путь — включите переключатель заново, чтобы обновить его.")
            : t("ZERE будет открываться при входе в систему. Отключение убирает запись — Windows больше не запускает приложение.");

      autostartCard = card(
        t("Запуск вместе с Windows"),
        h(
          "div",
          { class: "form-grid form-grid--single" },
          autostartToggle,
          command
            ? field(
                t("Команда запуска"),
                commandInput,
                t("Запись: {location} (только текущий пользователь, права администратора не нужны)", {
                  location: a.location,
                }),
              )
            : null,
          h("p", { class: "panel-note", text: note }),
        ),
      );
      autostartCard.classList.add("col-6");
    }

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
    if (autostartCard) grid.appendChild(autostartCard);
    grid.appendChild(aboutCard);

    updateDirty();
  }

  void load();

  return () => {
    cancelled = true;
  };
};
