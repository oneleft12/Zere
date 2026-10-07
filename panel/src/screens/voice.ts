/**
 * Экран «Голос» (этап 4, §6): настройки через POST /api/voice (строгое
 * подмножество ключей), честные capabilities реализации и тесты:
 * озвучка фразы, запись референса (ConfirmDialog — микрофон!), распознавание.
 * Громкость применяется сразу (liveVolumeApply), остальное — после рестарта.
 */

import {
  ApiError,
  apiGet,
  apiPost,
  type VoiceModeState,
  type VoiceSettings,
  type VoiceSettingsApplied,
} from "../api";
import { logEvent } from "../events";
import { t } from "../i18n";
import {
  badge,
  button,
  card,
  clear,
  confirmDialog,
  emptyState,
  field,
  h,
  keyValue,
  loadingRow,
  pageHeader,
  select,
  slider,
  statusPill,
  textInput,
  toast,
  toggle,
  type PillState,
} from "../ui";
import type { Cleanup, ScreenFactory } from "../router";

const MAX_TEST_TEXT = 500;

/** Опрос состояния голосового режима (фоновый цикл жив — 1 с, иначе тоже). */
const MODE_POLL_MS = 1000;

interface Draft {
  voiceEnabled: boolean;
  voiceVolume: number;
  ttsEngine: VoiceSettings["ttsEngine"];
  voiceReferencePath: string;
  audioProcessing: boolean;
}

function toDraft(settings: VoiceSettings): Draft {
  return {
    voiceEnabled: settings.voiceEnabled,
    voiceVolume: settings.voiceVolume,
    ttsEngine: settings.ttsEngine,
    voiceReferencePath: settings.voiceReferencePath,
    audioProcessing: settings.audioProcessing,
  };
}

function isDirty(base: VoiceSettings, draft: Draft): boolean {
  return (
    base.voiceEnabled !== draft.voiceEnabled ||
    base.voiceVolume !== draft.voiceVolume ||
    base.ttsEngine !== draft.ttsEngine ||
    base.voiceReferencePath !== draft.voiceReferencePath ||
    base.audioProcessing !== draft.audioProcessing
  );
}

export const voiceScreen: ScreenFactory = (container): Cleanup => {
  let cancelled = false;
  // Опрос /api/voice/mode: переживает перерисовку экрана, гасится на уходе.
  let stopPoll: (() => void) | null = null;

  container.appendChild(loadingRow(t("Загрузка голосовых настроек…")));

  const load = async (): Promise<void> => {
    if (cancelled) return;
    clear(container);
    container.appendChild(loadingRow(t("Загрузка голосовых настроек…")));

    try {
      const [settings, mode] = await Promise.all([
        apiGet<VoiceSettings>("/api/voice"),
        // Старый бэкенд без /api/voice/mode не должен ронять экран:
        // карточка режима покажет «нет данных» и не включится.
        apiGet<VoiceModeState>("/api/voice/mode").catch(() => null),
      ]);

      if (cancelled) return;
      render(settings, toDraft(settings), mode);
    } catch (error) {
      if (cancelled) return;
      clear(container);
      container.appendChild(
        emptyState({
          icon: "⚠️",
          title: t("Не удалось загрузить голосовые настройки"),
          hint: error instanceof ApiError ? error.message : t("Неизвестная ошибка"),
          action: { label: t("Повторить"), onClick: () => void load() },
        }),
      );
    }
  };

  function render(base: VoiceSettings, draft: Draft, initialMode: VoiceModeState | null): void {
    // Новая отрисовка — новый опрос: таймер предыдущей гасим первым.
    stopPoll?.();
    stopPoll = null;

    clear(container);

    const saveBtn = button(t("Сохранить"), () => void save(), "primary");
    const revertBtn = button(t("Отменить изменения"), () => {
      render(base, toDraft(base), modeState);
      logEvent("Изменения голосовых настроек отброшены");
    });

    const errorBox = h("div", { class: "form-error", hidden: true });
    const testErrorBox = h("div", { class: "form-error", hidden: true });
    const testResult = h("p", { class: "panel-note", hidden: true });

    const updateDirty = (): void => {
      saveBtn.disabled = !isDirty(base, draft);
      revertBtn.disabled = !isDirty(base, draft);
    };

    async function save(): Promise<void> {
      if (!isDirty(base, draft)) return;

      saveBtn.disabled = true;

      try {
        const applied = await apiPost<VoiceSettingsApplied>("/api/voice", draft);

        if (cancelled) return;

        const next: VoiceSettings = {
          voiceEnabled: applied.voiceEnabled,
          voiceVolume: applied.voiceVolume,
          ttsEngine: applied.ttsEngine,
          voiceReferencePath: applied.voiceReferencePath,
          audioProcessing: applied.audioProcessing,
          capabilities: base.capabilities,
        };

        toast(
          applied.appliedOnRestart
            ? t("Сохранено — вступит в силу после перезапуска")
            : t("Применено сразу, без перезапуска"),
          applied.appliedOnRestart ? "warn" : "ok",
        );
        logEvent(
          applied.appliedOnRestart
            ? "Голосовые настройки сохранены (перезапуск требуется)"
            : "Громкость и DSP применены без перезапуска",
        );
        render(next, toDraft(next), modeState);
      } catch (error) {
        if (cancelled) return;

        const message = error instanceof Error ? error.message : t("Неизвестная ошибка");
        errorBox.textContent = t("Сервер отклонил настройки: {message}", { message });
        errorBox.hidden = false;
        toast(t("Ошибка сохранения голосовых настроек"), "danger");
        logEvent("Ошибка сохранения голоса");
        saveBtn.disabled = false;
      }
    }

    // ── Карточка настроек ────────────────────────────────────────
    const settingsCard = card(
      t("Голосовой вывод"),
      h(
        "div",
        { class: "form-grid form-grid--single" },
        toggle({
          label: t("Голосовой вывод включён"),
          checked: draft.voiceEnabled,
          onChange: (v) => {
            draft.voiceEnabled = v;
            updateDirty();
          },
        }),
        field(
          t("Громкость"),
          slider({
            value: draft.voiceVolume,
            min: 0,
            max: 1,
            step: 0.05,
            onChange: (v) => {
              draft.voiceVolume = v;
              updateDirty();
            },
          }),
          t("Применяется сразу, без перезапуска"),
        ),
        field(
          t("TTS-движок"),
          select({
            value: draft.ttsEngine,
            options: [
              { value: "pocket", label: t("pocket — клонирование голоса") },
              { value: "chattts", label: t("chattts — реалистичный голос, без клонирования") },
            ],
            onChange: (v) => {
              draft.ttsEngine = v as Draft["ttsEngine"];
              updateDirty();
            },
          }),
          t("Смена движка вступает в силу после перезапуска"),
        ),
        field(
          t("DSP-обработка озвучки (ChatTTS)"),
          toggle({
            label: t("EQ + мягкая компрессия + нормализация"),
            checked: draft.audioProcessing,
            onChange: (v) => {
              draft.audioProcessing = v;
              updateDirty();
            },
          }),
          t("Применяется сразу; выключено — «сырой» выход TTS без фильтров"),
        ),
        field(
          t("Референс голоса (WAV)"),
          textInput({
            value: draft.voiceReferencePath,
            mono: true,
            placeholder: t("путь к WAV-референсу, пусто = встроенный голос"),
            onInput: (v) => {
              draft.voiceReferencePath = v;
              updateDirty();
            },
          }),
        ),
      ),
    );
    settingsCard.classList.add("col-6");

    // ── Возможности реализации ──────────────────────────────────
    const caps = base.capabilities;
    const capsCard = card(
      t("Возможности реализации"),
      h(
        "div",
        { class: "pill-row" },
        badge(
          t("запись референса: {value}", { value: caps.recordReference ? t("есть") : t("нет") }),
          caps.recordReference ? "ok" : "warn",
        ),
        badge(
          t("PocketTTS: {value}", { value: caps.pocketCloning ? t("есть") : t("нет") }),
          caps.pocketCloning ? "ok" : "warn",
        ),
        badge(
          t("скорость речи: {value}", {
            value: caps.speechSpeedConfig ? t("задаётся") : t("фиксирована"),
          }),
          caps.speechSpeedConfig ? "ok" : "warn",
        ),
        badge(
          t("громкость сразу: {value}", { value: caps.liveVolumeApply ? t("да") : t("нет") }),
          caps.liveVolumeApply ? "ok" : "warn",
        ),
        badge(
          t("DSP-обработка: {value}", {
            value: base.audioProcessing ? t("включена") : t("выключена"),
          }),
          base.audioProcessing ? "ok" : "warn",
        ),
        badge(
          t("микрофон (STT): {value}", { value: caps.sttTest ? t("доступен") : t("нет") }),
          caps.sttTest ? "ok" : "warn",
        ),
      ),
      h("p", {
        class: "panel-note",
        text: t(
          "Значения честные для текущей реализации: C# умеет больше, "
            + "Python-порт отдаёт false там, где функции ещё нет — панель это показывает, "
            + "а не скрывает.",
        ),
      }),
      keyValue([
        { key: t("Референс"), value: base.voiceReferencePath || "—" },
        { key: t("Движок"), value: base.ttsEngine },
        {
          key: t("Обработка"),
          value: base.audioProcessing ? t("DSP включена") : t("DSP выключена"),
        },
      ]),
    );
    capsCard.classList.add("col-6");

    // ── Режим голоса (непрерывный слушатель, POST /api/voice/mode) ─
    let modeState = initialMode;
    let modeBusy = false;

    const modeErrorBox = h("div", { class: "form-error", hidden: true });
    const pillHost = h("div", {});
    const modeHint = h("p", { class: "panel-note" });
    const modeKvHost = h("div", {});
    let modeKvSignature = "";

    const modeToggle = toggle({
      label: t("Слушать постоянно"),
      checked: modeState?.enabled ?? false,
      onChange: (v) => void setMode(v),
    });
    const modeToggleInput = modeToggle.querySelector<HTMLInputElement>("input");

    function stateLabel(mode: VoiceModeState): string {
      switch (mode.state) {
        case "idle":
          return t("выключен");
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
        default:
          return t("ошибка");
      }
    }

    function pillTone(mode: VoiceModeState): PillState {
      if (mode.state === "error") return "danger";
      if (!mode.available) return "warn";
      if (mode.enabled) return "ok";
      return "idle";
    }

    function paintMode(): void {
      const mode = modeState;

      if (mode === null) {
        // Бэкенд без /api/voice/mode: честно показываем отсутствие данных.
        pillHost.replaceChildren(
          statusPill({ label: t("Состояние режима"), value: t("нет данных"), state: "idle" }),
        );
        modeHint.textContent = t(
          "Состояние режима недоступно: сервер не отдаёт /api/voice/mode.",
        );
        modeKvHost.replaceChildren();
        if (modeToggleInput) modeToggleInput.disabled = true;
        return;
      }

      pillHost.replaceChildren(
        statusPill({
          label: t("Состояние режима"),
          value: stateLabel(mode),
          state: pillTone(mode),
          live: mode.enabled,
        }),
      );

      if (modeToggleInput) {
        modeToggleInput.disabled = modeBusy || !mode.available;
        if (!modeBusy) modeToggleInput.checked = mode.enabled;
        modeToggle.title = mode.available
          ? ""
          : t("Распознавание речи недоступно — режим голоса включить нельзя");
      }

      modeHint.textContent = !mode.available
        ? t("STT недоступен: режим голоса включить нельзя, доступны только тесты.")
        : mode.wakeWordEnabled
          ? t("Скажите «{word}», затем команду; «выход» — выключить режим.", {
              word: mode.wakeWord,
            })
          : t("Слово-триггер выключено — говорите команду сразу; «выход» — выключить режим.");

      const signature = JSON.stringify([
        mode.lastUtterance,
        mode.lastAnswer,
        mode.lastError,
      ]);
      if (signature !== modeKvSignature) {
        modeKvSignature = signature;
        modeKvHost.replaceChildren(
          keyValue([
            { key: t("Последняя команда"), value: mode.lastUtterance || "—" },
            { key: t("Последний ответ"), value: mode.lastAnswer || "—" },
            { key: t("Ошибка режима"), value: mode.lastError ?? "—" },
          ]),
        );
      }
    }

    async function setMode(enable: boolean): Promise<void> {
      if (modeState === null || modeBusy) {
        paintMode(); // вернуть чекбокс в серверное состояние
        return;
      }

      modeBusy = true;
      modeErrorBox.hidden = true;
      paintMode();

      try {
        modeState = await apiPost<VoiceModeState>("/api/voice/mode", { enabled: enable });
        toast(
          enable ? t("Голосовой режим включён") : t("Голосовой режим выключен"),
          "ok",
        );
        logEvent(
          enable ? "Голосовой режим включён из панели" : "Голосовой режим выключен из панели",
        );
      } catch (error) {
        const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
        modeErrorBox.textContent = t("Не удалось переключить режим: {message}", { message });
        modeErrorBox.hidden = false;
        toast(t("Ошибка переключения голосового режима"), "danger");
        logEvent(`Ошибка переключения голосового режима: ${message}`);

        modeState = await apiGet<VoiceModeState>("/api/voice/mode").catch(() => modeState);
      } finally {
        modeBusy = false;
        paintMode();
      }
    }

    async function pollMode(): Promise<void> {
      if (cancelled || modeBusy) return;

      const next = await apiGet<VoiceModeState>("/api/voice/mode").catch(() => null);
      if (cancelled || modeBusy || next === null) return;

      modeState = next;
      paintMode();
    }

    const modeCard = card(
      t("Режим голоса"),
      h("div", { class: "form-grid form-grid--single" }, pillHost, modeToggle, modeHint),
      modeKvHost,
      modeErrorBox,
    );
    modeCard.classList.add("col-6");

    // Опрос статуса: пока экран открыт, таймер гасится cleanup/перерисовкой.
    paintMode();
    const modeTimer = setInterval(() => void pollMode(), MODE_POLL_MS);
    stopPoll = () => clearInterval(modeTimer);

    // ── Тесты ────────────────────────────────────────────────────
    let testText = t("Проверка голоса. Привет!");

    const testInput = textInput({
      value: testText,
      placeholder: t("Фраза для озвучки (до 500 символов)"),
      onInput: (v) => {
        testText = v;
      },
    });

    const speakBtn = button(t("Озвучить"), () => void speak(), "primary");

    const recordBtn = button(t("Записать референс (15 с)"), () => void recordReference(), "default");
    recordBtn.disabled = !caps.recordReference;
    if (!caps.recordReference) {
      recordBtn.title = t(
        "Эта реализация не записывает референс (capabilities.recordReference=false)",
      );
    }

    const listenBtn = button(t("Тест микрофона"), () => void listen());
    listenBtn.disabled = !caps.sttTest;
    if (!caps.sttTest) listenBtn.title = t("STT сейчас недоступен (capabilities.sttTest=false)");

    async function speak(): Promise<void> {
      testErrorBox.hidden = true;

      const text = testText.trim();
      if (!text) {
        testErrorBox.textContent = t("Введите фразу для озвучки.");
        testErrorBox.hidden = false;
        return;
      }
      if (text.length > MAX_TEST_TEXT) {
        testErrorBox.textContent = t("Фраза длиннее {max} символов.", { max: MAX_TEST_TEXT });
        testErrorBox.hidden = false;
        return;
      }

      speakBtn.disabled = true;

      try {
        await apiPost<{ status: "ok" }>("/api/voice/test", { text });

        if (cancelled) return;

        toast(t("Фраза озвучена"), "ok");
        logEvent(`Тест озвучки: «${text.slice(0, 40)}»`);
      } catch (error) {
        if (cancelled) return;

        const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
        testErrorBox.textContent = message;
        testErrorBox.hidden = false;
        toast(t("Тест озвучки не удался"), "danger");
        logEvent(`Ошибка теста озвучки: ${message}`);
      } finally {
        if (!cancelled) speakBtn.disabled = false;
      }
    }

    async function recordReference(): Promise<void> {
      testErrorBox.hidden = true;

      const confirmed = await confirmDialog({
        title: t("Записать референс голоса?"),
        message: t(
          "Микрофон запишет 15 секунд вашей речи для клонирования голоса. Говорите чётко и без шума.",
        ),
        confirmLabel: t("Начать запись"),
      });

      if (!confirmed) {
        toast(t("Запись референса отменена"), "plain");
        logEvent("Запись референса отклонена пользователем");
        return;
      }

      recordBtn.disabled = true;

      try {
        const result = await apiPost<{ voiceReferencePath: string }>("/api/voice/reference", {});

        if (cancelled) return;

        base = { ...base, voiceReferencePath: result.voiceReferencePath };
        toast(t("Референс записан и сохранён в конфигурации"), "ok");
        logEvent(`Референс голоса записан: ${result.voiceReferencePath}`);
        render(base, toDraft(base), modeState);
      } catch (error) {
        if (cancelled) return;

        const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
        testErrorBox.textContent = message;
        testErrorBox.hidden = false;
        toast(t("Запись референса не удалась"), "danger");
        logEvent(`Ошибка записи референса: ${message}`);
        recordBtn.disabled = !caps.recordReference;
      }
    }

    async function listen(): Promise<void> {
      testErrorBox.hidden = true;
      testResult.hidden = true;

      listenBtn.disabled = true;

      try {
        const result = await apiPost<{ text: string }>("/api/voice/listen", {});

        if (cancelled) return;

        testResult.textContent = result.text
          ? t("Распознано: «{text}»", { text: result.text })
          : t("Микрофон ничего не распознал.");
        testResult.hidden = false;
        toast(t("Распознавание выполнено"), "ok");
        logEvent(`Тест микрофона: «${result.text.slice(0, 60)}»`);
      } catch (error) {
        if (cancelled) return;

        const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
        testErrorBox.textContent = message;
        testErrorBox.hidden = false;
        toast(t("Тест микрофона не удался"), "danger");
        logEvent(`Ошибка теста микрофона: ${message}`);
      } finally {
        if (!cancelled) listenBtn.disabled = !caps.sttTest;
      }
    }

    const testCard = card(
      t("Тестирование"),
      h(
        "div",
        { class: "form-grid form-grid--single" },
        field(
          t("Фраза для озвучки"),
          testInput,
          t("Синтез через активный движок; при 503 в ответе указана причина"),
        ),
        h("div", { class: "row-actions" }, speakBtn, recordBtn, listenBtn),
        testErrorBox,
        testResult,
      ),
    );
    testCard.classList.add("col-6");

    // ── Сборка ───────────────────────────────────────────────────
    container.append(
      pageHeader(
        t("Голос"),
        t("Настройки voiceVolume/ttsEngine/… через POST /api/voice; тесты ходят в живой VoiceManager"),
        [revertBtn, saveBtn],
      ),
      errorBox,
    );

    const grid = h("div", { class: "grid-12 fade-in" });
    grid.appendChild(settingsCard);
    grid.appendChild(modeCard);
    grid.appendChild(capsCard);
    grid.appendChild(testCard);
    container.appendChild(grid);

    updateDirty();
  }

  void load();

  return () => {
    cancelled = true;
    stopPoll?.();
    stopPoll = null;
  };
};
