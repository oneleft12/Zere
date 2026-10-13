# Каталог малых LLM для слабого ПК (CPU-only / слабая iGPU, 4–16 ГБ RAM)

Дата сбора: **13 октября 2026**. Окно релизов: **январь 2025 – октябрь 2026**.
Все размеры Q4 — **с карточек Ollama** (`/library/<model>`, там указан blob `quantization` + size) либо с HuggingFace GGUF-репозиториев. Даты релиза — из официальных README/блогов/HF API.

**Легенда:** ✅ подтверждено источником · ⚠️ частично/косвенно · ❌ не подтверждено · — нет данных

**Важно про RAM:** разработчики почти никогда не публикуют требования к RAM. Везде, где указан «RAM ~», это **оценка = размер файла + 1–1,5 ГБ** (KV-кэш, оверхед рантайма), а не факт из источника.

---

## 1. Сводная таблица: ≤ 4B (влезают в 4–8 ГБ)

| Модель | `ollama pull` | Парам. | Релиз | Разработчик | Лицензия | Q4 на диске | RAM ~ | Русский | Tools / контекст |
|---|---|---|---|---|---|---|---|---|---|
| **Qwen3.5-0.8B** | `qwen3.5:0.8b` (Q8_0) / `:0.8b-q4_K_M` | 752M + 101M proj | 02.03.2026 | Alibaba Qwen | **Apache-2.0** | 1.2 ГБ (Q8_0); Q4_K_M ≈0.53 ГБ | ~1,5–2 ГБ | ⚠️ заявлено 201 язык, «русский» поимённо не назван | ✅ tools + thinking / **256K** (native 262 144) |
| **Qwen3.5-2B** | `qwen3.5:2b-q4_K_M` | 1.88B + 331M proj | 02.03.2026 | Alibaba Qwen | **Apache-2.0** | **1.9 ГБ** (1.3 + 0.671 proj) | ~3 ГБ | ❌ | ✅ tools + thinking / 256K |
| **Qwen3.5-4B** | `qwen3.5:4b-q4_K_M` | 4.21B + 334M proj | 02.03.2026 | Alibaba Qwen | **Apache-2.0** | **3.3 ГБ** (2.6 + 0.676 proj) | ~4 ГБ | ❌ | ✅ tools + thinking / 256K |
| **Gemma 4 E2B** | `gemma4:e2b` | 2.3B eff (5.1B с эмбеддингами), Q4-blob 4.65B | 02.04.2026 | Google DeepMind | **Apache-2.0** (смена с Gemma Terms) | **4.6 ГБ** (3.5 + 0.987 proj + 0.098 draft) | ~6–7 ГБ | ❌ в карточке не назван (MMMLU 67.4%) | ✅ tools + thinking + vision + **audio** / 128K |
| **Gemma 4 E4B** | `gemma4:e4b` | 4.5B eff (8B с эмбеддингами), Q4-blob 7.52B | 02.04.2026 | Google DeepMind | **Apache-2.0** | **6.6 ГБ** (5.5 + 0.992 proj) | ~8–9 ГБ | ❌ в карточке не назван. ⚠️ **лучший подтверждённый RU-замер среди малых**: MERA ruMMLU **0.7688** (bf16, GPU) | ✅ tools + thinking + vision + audio / 128K |
| **Gemma 3 1B** | `gemma3:1b` | 1.00B | 12.03.2025 | Google | Gemma Terms of Use | **0.806 ГБ** | ~1,5–2 ГБ | ⚠️ «140+ языков», поимённо нет | ❌ нет tools / 32K |
| **Gemma 3 4B** | `gemma3:4b` | 4B | 12.03.2025 | Google | Gemma Terms | ~2.5 ГБ | ~4 ГБ | ⚠️ «140+» | ❌ (vision есть) / 128K |
| **Gemma 3n E2B** | `gemma3n:e2b` | 2B eff (Q4-blob 4.46B) | 26.06.2025 | Google | Gemma Terms | **5.6 ГБ** | ~7 ГБ | ⚠️ «140+ языков» | ❌ нет tools / 32K |
| **Granite 4.0 350M** | `granite4:350m` | 350M | 02.10.2025 | IBM | **Apache-2.0** | **0.708 ГБ** | ~1,5 ГБ | ❌ (12 языков, без ru) | ✅ tools / 32K |
| **Granite 4.0 1B** | `granite4:1b` | 1.63B | 02.10.2025 | IBM | **Apache-2.0** | 3.3 ГБ — **в Ollama это BF16, не Q4!** | ~4 ГБ | ❌ | ✅ tools / 128K |
| **Granite 4.0 micro** | `granite4:3b` = `granite4:micro` | 3.4B | 02.10.2025 | IBM | **Apache-2.0** | **2.1 ГБ** | ~3,5 ГБ | ❌ | ✅ tools / 128K |
| **Granite 4.2 3B** | `granite4.2:3b` | 3.66B | ~сент. 2026 | IBM | **Apache-2.0** | **2.2 ГБ** | ~3,5 ГБ | ❌ | ✅ tools + **thinking** (`enable_thinking`, `reasoning_effort`) / 128K |
| **Llama 3.2 1B** | `llama3.2:1b` | 1.24B | 25.09.2024* | Meta | Llama 3.2 Community | **1.3 ГБ** (Q8_0) | ~2 ГБ | ❌ (en, de, fr, it, pt, hi, es, th) | ✅ tools / 128K |
| **Llama 3.2 3B** | `llama3.2:3b` | 3.21B | 25.09.2024* | Meta | Llama 3.2 Community | **2.0 ГБ** | ~3,5 ГБ | ❌ | ✅ tools / 128K |
| **Phi-4-mini-instruct** | `phi4-mini:3.8b` | 3.84B | 26.02.2025 | Microsoft | **MIT** | **2.5 ГБ** | ~3,5 ГБ | ✅ **ДА — «Russian» в официальном списке поддерживаемых языков** | ✅ tools / 128K |
| **Phi-4-mini-reasoning** | `phi4-mini-reasoning:3.8b` | 3.8B | апр. 2025 | Microsoft | **MIT** | **3.2 ГБ** | ~4,5 ГБ | ❌ | ❌ без tools / 128K |
| **Phi-4-mini-flash-reasoning** | ❌ нет тега в Ollama | 3.8B | 09.07.2025 | Microsoft | **MIT** | только HF (SambaY, нужны спец. ядра) | — | ❌ «English» | ❌ / 64K |
| **Ministral 3 3B** | `ministral-3:3b` | 3.85B | 02.12.2025 | Mistral AI | **Apache-2.0** | **3.0 ГБ** | ~4 ГБ | ❌ (11 языков, без ru) | ✅ tools + vision / 256K |
| **LFM2.5-1.2B-Thinking** | `lfm2.5-thinking:1.2b` | 1.17B | 05.01.2026 | Liquid AI | **LFM Open License v1.0** (Apache-2.0-подобная; коммерция бесплатна до $10M выручки) | **0.731 ГБ** | ~1,5 ГБ | ❌ (en, ar, zh, fr, de, ja, ko, es) | ✅ tools + thinking / 32 768 |
| **LFM2.5-8B-A1B** | `lfm2.5:8b` | 8B MoE (~1.5B active) | 2026 | Liquid AI | LFM Open License v1.0 | **5.2 ГБ** | ~6,5 ГБ | ❌ | ✅ tools + thinking / 125K |
| **LFM2-24B-A2B** | `lfm2:24b` | 24B MoE (2B active) | 20.01.2026 | Liquid AI | LFM Open License v1.0 | **14 ГБ** | ~16 ГБ (только 16 ГБ и то впритык) | ❌ | ✅ tools / 32K |
| **Nemotron 3 Nano 4B** | `nemotron-3-nano:4b` | 3.97B | ~март 2026 | NVIDIA | NVIDIA Open Model License | **2.8 ГБ** | ~4 ГБ | ❌ (en, de, es, fr, it, ja) | ✅ tools + thinking / **256K** |
| **SmolLM3-3B** | ❌ нет офиц. тега (community: `alibayram/smollm3`) | 3B | 08.07.2025 | Hugging Face | **Apache-2.0** | GGUF на HF (~2 ГБ Q4_K_M) | ~3,5 ГБ | ⚠️ **частично + официальные бенчмарки**: Belebele 47.44, Global-MMLU 36.51, Flores-200 47.13. Обучен на ru, но не в топ-6 языков | ✅ tools (BFCL **92.3**) / 64K, до 128K YaRN |
| **Falcon-H1-1.5B** | ❌ только community `sam860/falcon-h1` | 1.5B | май 2025 | TII | Falcon-LLM License | ❌ не снят | — | ✅ `ru` в списке языков карточки | ❌ не снят / 256K |
| **MiniCPM5-1B** | ❌ нет на Ollama | 1.08B | 21.05.2026 | OpenBMB | **Apache-2.0** | **0.69 ГБ** (GGUF) | ~1,7 ГБ | ❌ в карточке нет | ✅ XML tool calls / **131 072** |
| **MiniCPM5-2B** | ❌ нет на Ollama | 2.52B | 06.09.2026 | OpenBMB | **Apache-2.0** | **1.56 ГБ** (GGUF) | ~3 ГБ | ❌ | ✅ XML tool calls / **131 072** |
| **MiniCPM4-0.5B** | ❌ нет на Ollama | 433.9M | 06.06.2025 | OpenBMB | **Apache-2.0** | ❌ Q4 не снят | ~1 ГБ | ❌ (en/zh) | / 32 768 |
| **EXAONE 3.5 2.4B** | `exaone3.5:2.4b` | 2.4B | дек. 2024* | LG AI Research | ⚠️ **EXAONE License 1.1 — НЕКОММЕРЧЕСКАЯ** | ~1.6 ГБ | ~3 ГБ | ❌ | / 32K |
| **Hunyuan-0.5B-Instruct** | ❌ нет на Ollama | 539M | 30.07.2025 | Tencent | ⚠️ Tencent Hunyuan Community License (**не действует в EU/UK/Юж. Корее**) | INT4 ~0.4 ГБ | ~1 ГБ | ❌ | / 256K |
| **Hunyuan-1.8B-Instruct** | ❌ нет на Ollama | 1.791B | 30.07.2025 | Tencent | то же | ~1.2 ГБ | ~2,5 ГБ | ❌ | / 256K |
| **Hunyuan-4B-Instruct** | ❌ нет на Ollama | 4.222B | 30.07.2025 | Tencent | то же | INT4 ~2.5 ГБ | ~4 ГБ | ❌ | / **262 144** |
| **DeepSeek-R1-Distill-Qwen-1.5B** | `deepseek-r1:1.5b` | 1.5B (Ollama 1.78B) | 20.01.2025 | DeepSeek | **MIT** | **1.1 ГБ** | ~2,5 ГБ | ❌ | / 131 072 |
| **BitNet b1.58 2B4T** | ❌ нет в Ollama (поиск = 0) | ~2B (ternary −1/0/1) | апр. 2025 | Microsoft Research | **MIT** | GGUF на HF (bitnet.cpp); ~1300 МБ RAM | ~1,5 ГБ | ❌ English only | ❌ без tools / 4096 |
| **Kolibri-1** | ❌ только community `robit/kolibri-1:q4_k_m` | 78B MoE (3.46B active) | 03.10.2026 | Aleph Alpha | **Apache-2.0** | **65 ГБ** ❌ не влезает | — | ❌ только DE/EN | ✅ tools + thinking / 1M (нативно 262K) |
| **Apertus-8B** | ❌ только community `MichelRosselli/apertus` | 8B | 02.09.2025 | Swiss AI (ETH/EPFL) | **Apache-2.0** | ❌ не снят | ~6 ГБ | ⚠️ 1811 языков, рус. поимённо нет | ✅ tools / 65 536 |
| **GLM-4.7-Flash** | `glm-4.7-flash` | 31.2B MoE-lite | 19.01.2026 | Zhipu / Z.ai | **MIT** | **19 ГБ** ❌ не влезает | ~24 ГБ | ❌ | ✅ tools + thinking / 198K |
| **GLM-4-9B-0414** | `glm4:9b` | 9.40B | 07.04.2025 | Zhipu / Z.ai | **MIT** | **5.5 ГБ** (Q4_0) | ~7 ГБ | ❌ | ❌ нет tools / 128K |
| **InternLM2.5-1.8B** | `internlm2:1.8b` | 1.89B | 2024* | Shanghai AI Lab | Apache-2.0 | 1.1 ГБ (Q4_0) | ~2 ГБ | ❌ | / 32K |
| **MINISTRAL/Mistral Small 4** | ❌ нет в Ollama library | 119B MoE / 6.5B active | 16.03.2026 | Mistral AI | Apache-2.0 | не влезает в 16 ГБ | — | ❌ | / 256K |

\* — дата вне окна «2025–2026», но модель актуальна и активно используется как базовая.

### 1a. Япония / Корея / Индия / ЮВА (региональные малые модели)

| Модель | `ollama pull` | Парам. | Релиз | Лицензия | Q4 на диске | RAM ~ | Русский | Tools / контекст |
|---|---|---|---|---|---|---|---|---|
| **Sailor2-L-1B-Chat** | **`sailor2:1b`** (1.1 ГБ) / `sailor2:1b-chat-q4_K_M` (**739 МБ**) | 0.99B | 18.02.2025 | **Apache-2.0** | **0.739 ГБ** | ~1,5–2 ГБ | ❌ (en/zh + 13 языков ЮВА) | / 32 768 |
| **Sailor2-L-8B-Chat** | **`sailor2:8b`** = `:8b-chat-q4_K_M` (**5.2 ГБ**) | 8.55B | 18.02.2025 | **Apache-2.0** | **5.2 ГБ** | ~7–8 ГБ | ❌ | / 32K |
| **llm-jp-4-8b-instruct** | ❌ нет | 8.59B | 30.03.2026 | **Apache-2.0** | **5.30 ГБ** (mmnga-o) | ~7 ГБ | ❌ (ja/en, 13 языков заявлено) | ✅ tools (OpenAI Harmony) / **65 536** |
| **llm-jp-4.1-8b-thinking** | ❌ нет | 8.59B | 15.09.2026 | **Apache-2.0** | **5.50 ГБ** (офиц. GGUF) | ~7–8 ГБ | ❌ | ✅ / **65 536** |
| llm-jp-3.1-1.8b-instruct4 | ❌ нет | 1.87B | 27.05.2025 | Apache-2.0 | **1.16 ГБ** | ~2,5 ГБ | ❌ | ⚠️ не заявлен (сторонний FC-GGUF) / 4096 |
| **sarashina2.2-3b-instruct-v0.1** | ❌ нет | 3.36B | 26.02.2025 | **MIT** | **2.07 ГБ** | ~3,5 ГБ | ❌ | ❌ инструментов в шаблоне нет / 8192 |
| sarashina2.2-1b / 0.5b | ❌ нет | 1.41B / 0.79B | 26.02.2025 | **MIT** | **0.93 / 0.53 ГБ** | ~2 / ~1,5 ГБ | ❌ | ❌ / 8192 |
| CAT-Translate-1.4b | ❌ нет | 1.41B | 02.02.2026 | MIT | **0.93 ГБ** | ~2 ГБ | ❌ | только перевод |
| **kanana-2-3b-instruct** | ❌ нет | 3.51B | 24.07.2026 | Kanana Open License (`other`) | **2.16 ГБ** | ~4 ГБ | ❌ (KMMLU 47.92, HAE-RAE 80.66) | ✅ (vLLM `qwen3_coder`) / 32 768 |
| **kanana-2-1.3b-instruct** | ❌ нет | 1.29B | 24.07.2026 | Kanana Open License | **0.85 ГБ** | ~2 ГБ | ❌ | ✅ / 32 768, SWA 1024 (−72,7% KV) |
| kanana-1.5-8b-instruct-2505 | ❌ нет | 8.03B | 21.05.2025 | **Apache-2.0** | **4.92 ГБ** | ~7 ГБ | ❌ | ✅ FC заявлен / 32 768 |
| kanana-1.5-2.1b-instruct-2505 | ❌ нет | 2.32B | 21.05.2025 | **Apache-2.0** | **1.52 ГБ** | ~3 ГБ | ❌ | ✅ FC заявлен |
| kanana-nano-2.1b-instruct | ❌ нет | 2.09B | 26.02.2025 | ⚠️ **cc-by-nc-4.0 (НЕкоммерч.)** | **1.39 ГБ** | ~3 ГБ | ❌ | ❌ не подтверждено / 8192 |
| HyperCLOVAX-SEED-Text-Instruct-0.5B | ❌ нет | 0.57B | 22.04.2025 | HyperCLOVA X SEED License (royalty-free, **revocable**) | **0.37 ГБ** | ~1,5 ГБ | ❌ | роль `tool_list` в примере / 4K (config 8192) |
| HyperCLOVAX-SEED-Text-Instruct-1.5B | ❌ нет | 1.59B | 22.04.2025 | та же (**gated**) | **1.01 ГБ** | ~2,5 ГБ | ❌ | ctx не подтверждён (401) |
| Tri-7B (trillionlabs) | ❌ нет | 7.53B | 22.07.2025 | **Apache-2.0** | **4.63 ГБ** | ~7 ГБ | ❌ | ko/en/ja / 32 768 |
| Krutrim-2-instruct | ❌ нет | **12B** (база Mistral-NeMo) | 02.02.2025 | Krutrim Community License | **7.48 ГБ** | ~9–10 ГБ | ❌ (11 инд. языков) | ctx в config 1 024 000 (не проверено) |
| Krutrim-1-instruct | ❌ нет | 7.35B | 03.02.2025 | Krutrim Community License v1.0 | ❌ **GGUF нет** | — | ❌ | / 4096 |
| sarvam-1 | ❌ нет | 2.53B | 23.10.2024* | Sarvam non-commercial | **1.55 ГБ** | ~3 ГБ | ❌ | ⚠️ text-completion база, не чат / 8192 |
| sarvam-translate | ❌ нет | 4.30B | 07.06.2025 | **GPL-3.0** | **2.49 ГБ** | ~4 ГБ | ❌ | только перевод (база gemma-3-4b-it) |
| **Apertus-SEA-LION-v4-8B-IT** | ❌ нет | 8.05B | 05.02.2026 | **MIT** | офиц. GGUF-репо есть (размеры не сняты) | — | ❌ | ✅ tool calling заявлен / **65 536** |
| Gemma-SEA-LION-v4.5-E2B-IT | ❌ нет | 5.12B (E2B) | 18.05.2026 | MIT | **3.43 ГБ** + mmproj 0.99 | ~5 ГБ | ❌ | any-to-any VL |
| **typhoon2.5-qwen3-4b** | ❌ нет | 4.02B (база Qwen3-4B-2507) | 23.09.2025 | **Apache-2.0** | **2.50 ГБ** (офиц. GGUF) | ~4 ГБ | ❌ (тайский + en) | ✅ (vLLM `hermes`) / **256K** |
| plamo-3-610m-fin-instruct | ❌ нет | 0.89B | 24.09.2026 | ⚠️ **PLaMo Community License (некоммерч.)** | **0.57 ГБ** | ~1,5 ГБ | ❌ | / **262 144** |
| sbintuitions nest-ja-0.1b / 0.6b | ❌ нет | 0.11B / 0.61B | 03.02.2026 | MIT | `.nemo` 0.57 / 2.70 | — | — | ⚠️ **НЕ LLM — речевой SSL-энкодер (FastConformer)** |

**Выводы по региональным моделям:**
- Уникальное сочетание «**ctx 65K + tool calling + Apache-2.0**»: `llm-jp-4-8b-instruct` (Q4 5.30 ГБ) и `llm-jp-4.1-8b-thinking` (5.50 ГБ). Реально на 16 ГБ, тесно на 8 ГБ.
- Лучший на 8 ГБ с tools и 32K: `kanana-2-3b-instruct` (2.16 ГБ), но лицензия Kanana Open, не Apache.
- Лучший на 4 ГБ с tools: `kanana-2-1.3b-instruct` (0.85 ГБ, SWA).
- **Единственное из всего этого блока, реально доступное в Ollama: `sailor2` (1b/8b/20b)** — но **без русского**, только языки ЮВА.
- **Русский язык: ни в одной карточке JP/KR/India/SEA не заявлен.**
- ⚠️ Не-LLM в подборке: `nest-ja-*` — речевой энкодер; `sarvam-translate`, `CAT-Translate`, `Chitranuvad` — только перевод; `plamo-3-nict-2b-base`, `Tri-*-Base` — только base.

---

## 2. Модели 7–9B, которые влезают в 8–16 ГБ при Q4

| Модель | `ollama pull` | Парам. | Релиз | Разработчик | Лицензия | Q4 на диске | RAM ~ | Русский | Tools / контекст |
|---|---|---|---|---|---|---|---|---|---|
| **Qwen3.5-9B** | `qwen3.5:9b-q4_K_M` | 8.95B + 456M proj | 02.03.2026 | Alibaba Qwen | **Apache-2.0** | **6.6 ГБ** (5.6 + 0.922 proj) | ~8 ГБ | ❌ | ✅ tools + thinking / **256K** |
| **LFM2.5-8B-A1B** | `lfm2.5:8b` | 8B MoE (~1.5B active) | 2026 | Liquid AI | LFM Open License v1.0 | **5.2 ГБ** | ~6,5 ГБ | ❌ | ✅ tools + thinking / 125K |
| **Granite 4.1 8B** | `granite4.1:8b` | 8B | 28.04.2026 | IBM | **Apache-2.0** | **5.3 ГБ** | ~6,5 ГБ | ❌ | ✅ tools / 128K (до 512K) |
| **Granite 4.2 8B** | `granite4.2:8b` | 8B | ~сент. 2026 | IBM | **Apache-2.0** | **5.3 ГБ** | ~6,5 ГБ | ❌ | ✅ tools + thinking / 128K |
| **Ministral 3 8B** | `ministral-3:8b` | 8B | 02.12.2025 | Mistral AI | **Apache-2.0** | **6.0 ГБ** | ~8 ГБ | ❌ | ✅ tools + vision / 256K |
| **DeepSeek-R1-Distill-Qwen-7B** | `deepseek-r1:7b` | 7.62B | 20.01.2025 | DeepSeek | **MIT** | **4.7 ГБ** | ~6,5 ГБ | ❌ | / 131 072 |
| **DeepSeek-R1-0528-Qwen3-8B** | `deepseek-r1:8b` | 8.19B | 29.05.2025 | DeepSeek | **MIT** | **5.2 ГБ** | ~7,5 ГБ | ❌ | ⚠️ карточка: «enhanced function calling» / 131 072 (YaRN ×4) |
| **DeepSeek-R1-Distill-Llama-8B** | `deepseek-r1:8b-llama-distill-q4_K_M` | 8.03B | 20.01.2025 | DeepSeek | **MIT** | **4.9 ГБ** | ~7 ГБ | ❌ | / 131 072 |
| **Nemotron Nano 2 9B** | ❌ только community `oamazonasgabriel/nemotron-nano-9b-v2` | 9B | 18.08.2025 | NVIDIA | NVIDIA Open Model License | ❌ не снят (bf16 24 ГБ) | — | ⚠️ ru в списке **входных** языков, но основная строка карточки: «English, German, Spanish, French, Italian, Japanese» — **самопротиворечие** | ✅ tools / 128K |
| **InternLM3-8B-Instruct** | ❌ нет на Ollama (404) | 8B | 13.01.2025 | Shanghai AI Lab | ❌ не проверено | **5.36 ГБ** (GGUF q4_k_m) | ~7 ГБ | ❌ | ❌ контекст не снят |
| **Intern-S1-mini** | ❌ нет на Ollama | 8.539B (VLM) | 18.08.2025 | Shanghai AI Lab | **Apache-2.0** | ⚠️ офиц. GGUF **только Q8_0 = 8.72 ГБ; Q4 НЕТ** | ~10 ГБ | ❌ | VLM |
| **MiniCPM4-8B** | ❌ нет на Ollama | 8.19B | 06.06.2025 | OpenBMB | Apache-2.0 | ~5 ГБ | ~6,5 ГБ | ❌ | / 32K+ |
| **MiniCPM4.1-8B** | ❌ нет на Ollama | 8.19B | сент. 2025 | OpenBMB | Apache-2.0 | **4.97 ГБ** | ~6,5 ГБ | ❌ | / 65 536 |
| **EXAONE 3.5 7.8B** | `exaone3.5:7.8b` | 7.8B | дек. 2024* | LG AI Research | ⚠️ **EXAONE 1.1 — НЕКОММЕРЧЕСКАЯ** | **4.8 ГБ** | ~6 ГБ | ❌ | / 32K |
| **Hunyuan-7B-Instruct** | ❌ нет на Ollama | 7B | 30.07.2025 | Tencent | ⚠️ Tencent Community License (не EU/UK/KR) | ~4.5 ГБ | ~6 ГБ | ❌ | / 256K |
| **TeleChat2-7B-32K** | ❌ нет на Ollama, GGUF-квантов нет | 7B | 12.02.2025 | China Telecom | ⚠️ кастомная «TeleChat社区许可», коммерция по заявке | ❌ нет Q4 | — | ❌ | ✅ Function Call в карточке / 32 768 |
| **Llama 4 Scout** | `llama4:16x17b` | 109B MoE (17B active) | 05.04.2025 | Meta | Llama 4 Community | **67 ГБ** ❌ | — | ❌ | ✅ vision+tools / 10M |
| **xLAM / Llama 4 small** | — | — | — | — | — | — | — | — | ❌ **Llama 4 «small» НЕ СУЩЕСТВУЕТ**. В линейке только Scout (109B) и Maverick (400B) — оба не влезают |

---

## 3. Русскоязычные модели (главный приоритет для ZERE)

| Модель | `ollama pull` | Парам. | Релиз | Разработчик | Лицензия | Q4 на диске | RAM ~ | Русский | Tools / контекст |
|---|---|---|---|---|---|---|---|---|---|
| **T-lite-it-2.1** | **`t-tech/T-lite-it-2.1`** (офиц. от разработчика!) | 8B (Qwen3-8B) | 22.12.2025 | Т-Технологии (Т-Банк) | **Apache-2.0** | **4.68 ГБ** (Q4_K_M, 5 027 750 240 Б) | ~6 ГБ | ✅ **RU Arena Hard 83.9** против 57.2 у Qwen3-8B — лучший instruction-following на 8B | ✅ tool calling заявлен (ruBFCL **56.5**, ACEBench 61.0, Tau2 26.8); `/tags` = tools+thinking / 32 768 (YaRN → 131 072) |
| **QVikhr-3-4B-Instruction** | ❌ нет на Ollama; GGUF `Vikhrmodels/QVikhr-3-4B-Instruction-GGUF` | 4B (Qwen3-4B) | 28.06.2025 | Vikhrmodels | **Apache-2.0** | **2.33 ГиБ** (Q4_K_M, 2 497 281 088 Б) | ~3,5 ГБ | ✅ ru+en | ✅ tool-call шаблон есть / 40 960 |
| **RuadaptQwen3-4B-Instruct** | ❌ нет на Ollama | 4B (Qwen3-4B-Instruct-2507) | 26.08.2025 | RefalMachine | **Apache-2.0** | **2.32 ГиБ** (Q4_K_M, 2 486 507 648 Б) | ~3,5 ГБ | ✅ свой RU-токенизатор (+48k токенов) → «до +100 % скорости генерации RU-текста» | ✅ шаблон Qwen3 / 262 144 |
| **YandexGPT-5-Lite-8B-instruct** | **`yandex/YandexGPT-5-Lite-8B-instruct-GGUF`** (офиц. от разработчика!) | 8B | 28.03.2025 | Яндекс | ⚠️ `other` / `yandexgpt-5-lite-8b` (не OSI) | **4.58 ГБ** (Q4_K_M, 4 920 741 184 Б; в репо **только Q4_K_M**) | ~6 ГБ | ✅ | ❌ **tool calling НЕ ПОДТВЕРЖДЁН**. ⚠️ нестандартный шаблон (одна реплика после «Ассистент:[SEP]»), авторы пишут, что интерактивный режим «только для ознакомления» / 32 768 |
| **GigaChat3.1-10B-A1.8B** («Lightning») | ❌ офиц. нет; community: `second_constantine/gigachat3.1` (tag `10b`, tools), `forzer/GigaChat3-10B-A1.8B`, `Bored/GigaChat3.1-10B-A1.8B-q4_K_M` | MoE 10B / 1.8B active | **21.03.2026** | Sber / ai-sage | **MIT** | **6.03 ГиБ** (q4_K_M, 6 474 702 976 Б) | ~7,5 ГБ | ✅ | ✅ function calling документирован (tool-call-parser `gigachat3`) / **262 144** |
| **GigaChat-20B-A3B-instruct-v1.5** | ❌ community `infidelis/GigaChat-20B-A3B-instruct-v1.5` | MoE 20B / 3B active | 30.01.2025 | Sber | **MIT** | **11.64 ГиБ** (q4_K_M) | ~13 ГБ (только 16 ГБ и с урезанием контекста) | ✅ | ✅ роль `available functions` в шаблоне / 131 072. MERA 0.513 |
| **QVikhr-3-8B** | ❌ нет на Ollama | 8B (Qwen3-8B) | 05.08.2025 | Vikhrmodels | Apache-2.0 | **4.68 ГиБ** (Q4_K_M) | ~6 ГБ | ✅ | ✅ / — |
| **Vistral-24B-Instruct** | ❌ | 24B | 28.09.2025 | Vikhrmodels | Apache-2.0 | ❌ не для слабого ПК | — | ✅ | — |
| **Vikhr-Nemo-12B-Instruct-R-21-09-24** | `rscr/vikhr_nemo_12b` (community, latest Q4_K_M, tools) | 12B | 20.09.2024* | Vikhrmodels | Apache-2.0 | **6.96 ГиБ** (Q4_K_M) | ~8,5 ГБ | ✅ | ✅ grounded-RAG через роль `documents` / до 128K |
| **Vikhr-YandexGPT-5-Lite-8B-it** | ❌ тега Ollama не найдено | 8B | 28.02.2025 | Vikhrmodels | ⚠️ other/yandexgpt-5-lite-8b-pretrain | — | — | ✅ | — |
| **saiga_gemma3_12b** | `OxW/Saiga_Gemma3_12B` (community: Q4_K_M/Q6_K/Q8_0) | 12B (Gemma-3-12B) | 20.04.2025 | IlyaGusev | ⚠️ `gemma` (Gemma Terms) | **6.80 ГиБ** (Q4_K_M) | ~8,5 ГБ | ✅ | / 131 072 |
| **saiga_yandexgpt_8b** | `OxW/Saiga_YandexGPT_8B` (community) | 8B | 04.03.2025 | IlyaGusev | ⚠️ other/yandexgpt-5-lite-8b-pretrain | — | — | ✅ | — |
| **T-lite-instruct-0.1** | ❌ | 8B (llama) | 16.07.2024* | Т-Банк | ❌ **лицензия на HF ОТСУТСТВУЕТ** (apache-2.0 заявляют лишь сторонние GGUF-загрузчики). HF-репо редиректит на `AnatoliiPotapov/T-lite-instruct-0.1` | — | — | ✅ | ❌ |
| **T-lite-it-1.0** | ❌ | Qwen2.5-7B | 10.12.2024* | Т-Банк | ❌ лицензия в карточке не указана | офиц. GGUF только Q8_0 | — | ✅ | ❌ **tool calling явно отсутствует** (сказано в карточке 2.1) |
| **T-pro-it-2.1** | ❌ | 32B | — | Т-Банк | — | **18.41 ГиБ** (Q4_K_M, 19 761 766 048 Б) | ❌ не для слабого ПК | ✅ | — |
| **T-Search** | ❌ | MoE 35B / 3B active | 13.07.2026 | Т-Банк | — | ❌ | — | ✅ | поисковый агент |
| **AliceAI-Foundation-80B-A3B-Base** | ❌ | MoE 80B / 3B active | 12.09.2026 | Яндекс | Apache-2.0 | ❌ | — | ✅ | — |

**Ключевые выводы по русским моделям:**
- В **официальной** библиотеке `ollama.com/library` русских LLM **нет** — всё в пользовательских namespace. Из них только `t-tech/T-lite-it-2.1` и `yandex/YandexGPT-5-Lite-8B-instruct-GGUF` — **от самих разработчиков**.
- **Лидер для ZERE: `t-tech/T-lite-it-2.1`** — официальный тег Ollama, tool calling заявлен, 4.68 ГБ Q4, Apache-2.0.
- **Лёгкий вариант 4–8 ГБ:** QVikhr-3-4B / RuadaptQwen3-4B (~2.3 ГиБ).
- **Лучший баланс для 16 ГБ:** GigaChat3.1-10B-A1.8B (MoE с 1.8B активных → быстрая на CPU, MIT, 262K контекст).
- **YandexGPT 5 Pro / 5.1 Pro — веса НЕ открыты.** **YaFSDP** — фреймворк шардированного параллелизма, **не модель**.
- **MERA** — это бенчмарк (mera.a-ai.ru), релизной модели «MERA-Qwen» **не существует**.
- **Saiga мертва с апреля 2025**; **«Ru-Llama»** как оформленное семейство с открытыми весами **не найдено**.
- **Замеров tok/s на CPU для русских моделей в источниках нет** — все метрики серверные (H100/vLLM).

---

## 4. Ответы на конкретные вопросы задания

| Что спрашивали | Реальность |
|---|---|
| Qwen3.5 **0.5B / 1.7B** | ❌ **НЕ СУЩЕСТВУЕТ.** В Ollama у Qwen3.5 только `0.8b / 2b / 4b / 9b / 27b / 35b / 122b`. 1.7B — это **Qwen3**, не Qwen3.5. На HF релиз малых: **02.03.2026** |
| Qwen3.5 2B / 4B | ✅ Существуют. `qwen3.5:2b` (1.88B, 1.9 ГБ Q4), `qwen3.5:4b` (4.21B, 3.3 ГБ Q4), Apache-2.0, 256K, tools+thinking |
| Gemma 4 **E2B / E4B** | ✅ Существуют (02.04.2026, **Apache-2.0**). E2B 4.6 ГБ, E4B 6.6 ГБ Q4 |
| Gemma 4 **1B** | ❌ **НЕ СУЩЕСТВУЕТ.** В Gemma 4 только `e2b / e4b / 12b / 26b / 31b`. 1B есть в **Gemma 3** (`gemma3:1b`, 0.806 ГБ) |
| Llama 3.2 1B / 3B | ✅ `llama3.2:1b` 1.3 ГБ, `llama3.2:3b` 2.0 ГБ, tools, 128K. Русского в офиц. списке **нет** |
| Llama 4 **small** | ❌ **НЕ СУЩЕСТВУЕТ.** Только Scout (109B MoE, Q4 = 67 ГБ) и Maverick (400B) — не для слабого ПК |
| Phi-4-mini / Phi-4-mini-flash | ✅ Phi-4-mini `phi4-mini:3.8b` (2.5 ГБ, MIT, **русский официально поддержан**, tools, 128K). Flash-reasoning — только HF, **нет тега Ollama**, рус. нет |
| Phi-5 | ❌ **НЕ ПОДТВЕРЖДЕНО** — только вторичные блоги 2026, официального подтверждения Microsoft нет |
| SmolLM3 | ✅ 3B, 08.07.2025, Apache-2.0, tools (BFCL 92.3), **частичный русский + официальные бенчмарки** (Belebele 47.44). **Офиц. тега Ollama нет** |
| LFM2 (Liquid AI) | ✅ 350M/700M/1.2B (июль 2025) — **офиц. Ollama-тег `lfm2` содержит только `:24b`**. Лучший на CPU: **LFM2.5-1.2B-Thinking** (`lfm2.5-thinking:1.2b`, 0.731 ГБ, 116 tok/s decode на Ryzen AI 9 HX 370). Русского нет |
| Granite 4.0 **micro / tiny** | ✅ `granite4:micro` = `granite4:3b` (2.1 ГБ, Apache-2.0); `granite4:tiny-h` = `granite4:7b-a1b-h` (MoE 1B active). Русского нет |
| Ministral 3B | ✅ `ministral-3:3b`, 3.85B, 02.12.2025, **Apache-2.0**, 3.0 ГБ Q4, tools+vision, 256K. Русского нет |
| Nemotron Nano 2 / 3 | ✅ **Nemotron 3 Nano 4B** (`nemotron-3-nano:4b`, 2.8 ГБ, tools+thinking, 256K, NVIDIA Open Model License). Nemotron Nano 2 9B — только community-тег; Q4 не снят |
| BitNet b1.58 2B4T | ✅ Существует (апр. 2025, **MIT**), но **в Ollama его НЕТ** (поиск = 0). GGUF на HF, ~1300 МБ RAM, **36.94 tok/s** на Ryzen 9 7845HX (bitnet.cpp). English only, 4096 контекст |
| Kolibri (Aleph Alpha) | ✅ Существует (03.10.2026, **Apache-2.0**), но **78B MoE / 3.46B active, Q4 = 65 ГБ** → ❌ **не для слабого ПК**. Только DE/EN |
| Liquid AI **d1-3B** | ⚠️ Существует на HF (обновление 08.10.2026), LFM Open License, 16 языков. Decision-модель (1 forward pass). **Русский не подтверждён**, Q4-размер не снят |
| MiniCPM | ✅ MiniCPM4-0.5B/8B, 4.1-8B, **MiniCPM5-1B (0.69 ГБ Q4, 131K ctx), MiniCPM5-2B (1.56 ГБ Q4, 131K ctx)** — все Apache-2.0, **ни одной нет в Ollama** |
| GLM-4.x-9B / Air | ✅ `glm4:9b` (9.4B, Q4_0 5.5 ГБ, **MIT**, 128K, рус. нет). GLM-4.5-Air — 110.5B (12B active), ❌ не влезает. GLM-4.7-Flash — 19 ГБ Q4, ❌. **GLM-4.6 ретирид 16.06.2026** |
| EXAONE 3.5 / 4 | ✅ `exaone3.5:2.4b` и `:7.8b` есть в Ollama, но ⚠️ **НЕКОММЕРЧЕСКАЯ лицензия**. EXAONE 4.0-1.2B и 4.5-33B — **нет в Ollama** |
| Apertus | ✅ Apertus-8B (02.09.2025, Apache-2.0, 1811 языков, tools, 65K). **Офиц. тега Ollama нет** (community `MichelRosselli/apertus`) |
| Hunyuan 0.5B/1.8B/4B | ✅ Существуют (30.07.2025), но ⚠️ **Tencent Community License не действует в EU/UK/Южной Корее**, и **нет в Ollama**. 4B: 256K контекст |
| Falcon-H1 small | ✅ Falcon-H1-1.5B (май 2025, Falcon-LLM License, **`ru` в списке языков**, 256K). **33.7 tok/s decode на CPU M4 Max**. Офиц. тега Ollama нет |
| InternLM / Intern-S1-mini | ⚠️ InternLM3-8B-Instruct (13.01.2025, нет в Ollama, GGUF 5.36 ГБ). Intern-S1-mini (8.5B VLM, Apache-2.0, офиц. GGUF **только Q8_0 8.72 ГБ, Q4 нет**) |
| T-lite (T-Bank) | ✅ См. §3. Официальный тег **`t-tech/T-lite-it-2.1`** |
| YandexGPT 5 Lite | ✅ Официальный тег `yandex/YandexGPT-5-Lite-8B-instruct-GGUF`, Q4_K_M 4.58 ГБ. **Tool calling не подтверждён** |
| Vikhr | ✅ См. §3 (QVikhr-3-*, Vistral-24B, Vikhr-Nemo-12B) |
| Saiga | ⚠️ Последняя — `saiga_gemma3_12b` (20.04.2025). **Линия фактически остановлена** |

---

## 5. Русский язык — итоговая сводка по подтверждённому

- ✅ **ДА (явно в официальном списке языков карточки):** **Phi-4-mini-instruct** (плюс ред-тиминг на русском), **Falcon-H1-1.5B/3B**, **Mistral Small 3.2**, Nemotron Nano 2 9B (⚠️ с самопротиворечием в карточке)
- ⚠️ **ЧАСТИЧНО (обучена + официальные бенчмарки, но не в топ-списке):** **SmolLM3-3B** (Belebele 47.44, Global-MMLU 36.51, Flores-200 47.13)
- ⚠️ **«140+/1000+ языков» без поимённого русского:** Gemma 3 1B/4B, Gemma 3n E2B/E4B, Gemma 4, Apertus-8B
- ❌ **НЕТ (офиц. список есть, русского нет):** Llama 3.2 1B/3B, Granite 4.0/4.1/4.2 (все размеры), Ministral 3, Mistral Small 4, **LFM2 и LFM2.5 (все)**, Nemotron 3 Nano 4B, BitNet b1.58 2B4T, Kolibri, Phi-4-mini-flash-reasoning
- ⚠️ **НЕ ПОДТВЕРЖДЕНО:** Qwen3.5 (только «201 язык»), d1-3B, MiniCPM, GLM, EXAONE, Hunyuan, InternLM, DeepSeek-R1-distill, Phi-4-mini-reasoning

**MERA (главный русский бенчмарк) — реально найденные сабмиты:**
- Llama-3.2-3B-Instruct: итог **0.324** (место 448), ruMMLU 0.419 — замер на H100+vLLM, **НЕ CPU**
- Gemma-4-E4B-it: мультимодальный борд **0.467** (место 3), WEIRD 0.662
- Независимый харнесс на MERA ruMMLU (14 012 вопросов, RTX PRO 6000): Gemma-4-12B fp8 **0.8103**, **Gemma-4-E4B bf16 0.7688**, Gemma-4-26B-A4B **0.7006**
- Qwen3.5-122B-A10B: Мульти 0.443 (место 4), Изображения 0.648 (1), Видео 0.727 (1)
- По Phi-4-mini, Gemma 3, Granite, SmolLM3, LFM2, Ministral, Nemotron, Falcon-H1, Apertus, Kolibri сабмитов в MERA **не найдено**

---

## 6. Реальная скорость на CPU (только подтверждённые замеры, с указанием железа)

| Модель | CPU tok/s (decode) | Железо / конфиг |
|---|---|---|
| **LFM2.5-1.2B** | **116** (вендор) / 70 | AMD Ryzen AI 9 HX 370, llama.cpp Q4_0, 856 МБ / Snapdragon Gen4 CPU |
| **LFM2-350M** | **103.1** (Q4_K_M) / 119.1 (Q8_0) | Apple M4, llama.cpp CPU, 4 P-ядра |
| **Llama 3.2 1B** | **68.1** / ~9–10 | Apple M1 Pro Q8_0 / Raspberry Pi 5 16GB Q4_K_M |
| **LFM2-700M** | **53.1** / 59.0 | Apple M4 |
| **BitNet b1.58 2B4T** | **36.94**, ~1300 МБ RAM, ~27 мДж/токен | bitnet.cpp, Ryzen 9 7845HX, 8 потоков, DDR5 |
| **LFM2-1.2B** | **34.6** / 37.3 | Apple M4 |
| **Falcon-H1-1.5B** | **33.7** (prefill 238, TTFT 1.11 с) / 6.6 | LiteRT-LM, M4 Max **CPU** / Intel Core i5-5300U |
| **Llama 3.2 3B** | **26.3** / ~5–6 | Apple M1 Pro Q8_0 / Raspberry Pi 5 |
| **Phi-4-mini-reasoning** | **19.7** decode | LiteRT int4, Mac Studio M4 Max CPU (XNNPACK) |
| **Qwen3.5-4B** | ⚠️ **107** (непроверенный community-замер, модель CPU не указана) | llama.cpp, CPU, 32 ГБ RAM, ctx 8192 |
| **Granite 4.0 micro** | 24.3 (Micro IQ4) / 17.6 (H-Micro) | Jensen Orin Nano 8GB — **НЕ CPU-only** |
| **Gemma 3 1B** | ~8–12 | Raspberry Pi 5 8/16 ГБ |
| **Phi-4-mini 3.8B** | **1.57** (llama.cpp) / 2.07 (Ollama) | Intel N5095 4C/4T Q4_K_M ← очень слабое железо |
| **Gemma 3 4B** | **1.62** / 1.99 | Intel N5095, 4 потока |

❌ **Нет ни одного CPU-замера:** Granite 4.1/4.2 (все), Ministral 3, Mistral Small 3.2/4, Nemotron (оба), Kolibri, Apertus, d1-3B, Gemma 3n E2B/E4B, Phi-4-mini-flash-reasoning, все русские модели.

---

## 7. Практические рекомендации для ZERE (CPU-only, 4–16 ГБ, ассистент + tool calling)

**Основной выбор (16 ГБ):**
1. **`t-tech/T-lite-it-2.1`** — 4.68 ГБ Q4, официальный тег Ollama от разработчика, **tool calling заявлен**, лучший RU instruction-following (RU Arena Hard 83.9), Apache-2.0
2. **`qwen3.5:4b-q4_K_M`** — 3.3 ГБ, Apache-2.0, tools+thinking, 256K контекст, свежайшая архитектура
3. **`gemma4:e2b`** — 4.6 ГБ, Apache-2.0, tools+vision+audio, 128K — если нужен мультимодальный ассистент

**Лёгкий вариант (4–8 ГБ):**
1. **QVikhr-3-4B-Instruction** или **RuadaptQwen3-4B-Instruct** — ~2.33 ГиБ Q4, Apache-2.0, русский
2. **`granite4.2:3b`** — 2.2 ГБ, Apache-2.0, tools+thinking (если русский не критичен)
3. **`lfm2.5-thinking:1.2b`** — 0.731 ГБ, 116 tok/s на CPU — **самая быстрая**, но русского нет
4. **`phi4-mini:3.8b`** — 2.5 ГБ, MIT, **русский официально**, tools, 128K — ⚠️ но на очень слабом CPU (N5095) всего ~1.6–2.1 tok/s

**Русский + маленький размер + tool calling + Apache-2.0 — идеальный кандидат:** ⚠️ **такого сочетания в природе нет.** Ближайшие компромиссы:
- русский + tools + Apache-2.0 + малый размер → **QVikhr-3-4B** (community GGUF, ~2.3 ГиБ)
- русский + tools + официальный Ollama-тег → **T-lite-it-2.1** (но 4.68 ГБ)
- русский + официально в карточке + MIT + tools → **Phi-4-mini-instruct** (2.5 ГБ, но медленная на 4-поточном CPU)

**Чего избегать:** EXAONE (некоммерческая лицензия), Hunyuan (лицензия не действует в EU), TeleChat (коммерция по заявке), Llama 4 (не влезает), Kolibri (65 ГБ).

---

## 8. Что осталось НЕ подтверждённым

1. **RAM-требования** — разработчики их почти не публикуют; в отчёте это оценка (Q4-файл + 1–1.5 ГБ), а не факт.
2. **Русский язык** — поимённо подтверждён только у Phi-4-mini, Falcon-H1, Mistral Small 3.2 (+ частично SmolLM3, спорно Nemotron Nano 2 9B). Для большинства — «не подтверждено».
3. **CPU tok/s** — нет замеров для Granite 4.1/4.2, Ministral 3, Nemotron, Kolibri, Apertus, d1-3B, Gemma 3n, и **для всех русских моделей**.
4. **Японские, корейские, индийские, SEA-модели** (llm-jp-4-8b, sarashina2.2, HyperCLOVA X SEED, sarvam-30b/105b, SEA-LION, Typhoon) — даты из HF API собраны, но лицензии/размеры/контекст **не проверены**.
5. **Точные даты релиза** Granite 4.2 и Nemotron 3 Nano 4B (Ollama даёт только «месяцев назад»).
6. **Phi-5** — существование только по вторичным блогам.

---

## 9. Источники

**Ollama (размеры, теги, контекст, capabilities, лицензии, даты):**
- https://ollama.com/library/qwen3.5 · /qwen3.5:0.8b · /qwen3.5:2b · /qwen3.5:4b · /qwen3.5:9b · /qwen3.5/tags
- https://ollama.com/library/gemma4 · /gemma4:e2b · /gemma4:e4b · /gemma4/tags
- https://ollama.com/library/gemma3 · /gemma3:1b · /gemma3n · /gemma3n:e2b
- https://ollama.com/library/llama3.2 · /llama3.2:1b · /llama3.2:3b · /llama3.2/tags · /llama4
- https://ollama.com/library/phi4-mini · /phi4-mini:3.8b · /phi4-mini/tags
- https://ollama.com/library/granite4 · /granite4:1b · /granite4:3b · /granite4/tags · /granite4.2 · /granite4.2:3b · /granite4.2/tags
- https://ollama.com/library/ministral-3 · /ministral-3:3b · /ministral-3/tags
- https://ollama.com/library/lfm2 · /lfm2.5 · /lfm2.5-thinking · /lfm2.5-thinking:1.2b · /lfm2.5/tags
- https://ollama.com/library/nemotron-3-nano · /nemotron-3-nano:4b · /nemotron-3-nano/tags · /nemotron-3.5-lightning
- https://ollama.com/library/glm4 · /glm4:9b · https://ollama.com/library/exaone3.5 · /functiongemma · /translategemma · /internlm2 · /qwen3 · /deepseek-r1
- https://ollama.com/search?q=bitnet · ?q=hunyuan · ?q=lfm2.5 · ?q=llama4 · ?q=smollm3 · ?q=gpt-oss · ?q=kolibri

**HuggingFace (карточки, лицензии, языки, бенчмарки, размеры):**
- https://huggingface.co/Qwen/Qwen3.5-4B/raw/main/README.md · /Qwen3.5-0.8B
- https://huggingface.co/microsoft/Phi-4-mini-instruct/raw/main/README.md · /Phi-4-mini-flash-reasoning
- https://huggingface.co/microsoft/bitnet-b1.58-2B-4T/raw/main/README.md · /bitnet-b1.58-2B-4T-gguf
- https://huggingface.co/HuggingFaceTB/SmolLM3-3B/raw/main/README.md
- https://huggingface.co/LiquidAI/LFM2-1.2B · /LFM2-350M-GGUF · /d1-3B
- https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-9B-v2/raw/main/README.md
- https://huggingface.co/Aleph-Alpha/Kolibri-1 · /Kolibri-1/raw/main/README.md
- https://huggingface.co/swiss-ai/Apertus-8B-Instruct-2509/raw/main/README.md
- https://huggingface.co/tiiuae/Falcon-H1-1.5B-Instruct/raw/main/README.md
- https://huggingface.co/t-bank-ai/T-lite-instruct-0.1 · /AnatoliiPotapov/T-lite-instruct-0.1
- https://huggingface.co/yandex/YandexGPT-5-Lite-8B-instruct-GGUF
- https://huggingface.co/ai-sage/GigaChat3.1-10B-A1.8B-GGUF
- https://huggingface.co/Vikhrmodels/QVikhr-3-4B-Instruction-GGUF
- https://huggingface.co/RefalMachine/RuadaptQwen3-4B-Instruct

**Блоги и релизы:**
- https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/ (Gemma 4, 02.04.2026)
- https://arstechnica.com/ai/2026/04/google-announces-gemma-4-open-ai-models-switches-to-apache-2-0-license/
- https://machineherald.io/article/2026-04/03-google-releases-gemma-4-under-apache-20-license...
- https://ai.google.dev/gemma/docs/releases · /gemma/docs/core/model_card_4 · /gemma/apache_2
- https://github.com/QwenLM/Qwen3.5 (news: 02.03.2026 — релиз 9B/4B/2B/0.8B)
- https://qwen.ai/blog?id=qwen3.5
- https://mistral.ai/news/mistral-3/ (02.12.2025) · https://mistral.ai/news/ministraux/ (2024)
- https://www.liquid.ai/blog/liquid-foundation-models-v2-our-second-series-of-generative-ai-models (LFM2, 10.07.2025)
- https://www.liquid.ai/blog/introducing-lfm2-5-the-next-generation-of-on-device-ai (LFM2.5)
- https://aleph-alpha.com/en/blog/kolibri-has-landed-a-sovereign-open-weight-model/ (03.10.2026)
- https://azure.microsoft.com/en-us/blog/reasoning-reimagined-introducing-phi-4-mini-flash-reasoning/
- https://www.ibm.com/think/tutorials/building-a-filenet-troubleshooter-with-ibm-granite-and-ollama
- https://www.microsoft.com/en-us/research/publication/bitnet-a4-8-4-bit-activations-for-1-bit-llms

**MERA (русский бенчмарк):**
- https://mera.a-ai.ru/en/text/leaderboard · /en/text/submits/12022 (Llama-3.2-3B) · /en/multi/submits/455 (Gemma-4-E4B)
- https://daniel.csylabs.com/en/2026-07-07-open-models-blackwell-nvfp4-en (ruMMLU харнесс)
- https://github.com/MERA-Evaluation/MERA · https://arxiv.org/abs/2401.04531

**Русскоязычные обзоры:**
- https://habr.com/ru/companies/paybeam/articles/1027242/ («Локальные LLM на слабом железе», 25.04.2026)

**Файлы детальных отчётов в рабочей области:**
- `docs/research/RU_SLM_CPU_2025-2026.md` — русские модели (полная версия)
- `docs/SLM_RESEARCH_2026-10.md` — азиатские модели (полная версия)
