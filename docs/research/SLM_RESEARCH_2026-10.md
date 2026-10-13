# Малые локальные LLM для слабых ПК (CPU/weak iGPU, 4–16 ГБ RAM), вып. Jan 2025 – Oct 2026

Дата отчёта: 13.10.2026. Все факты — из источников ниже. «НЕ ПОДТВЕРЖДЕНО» = не найдено подтверждения в источниках.
RAM = оценка (файл Q4 + 1–1.5 ГБ на KV-кэш/оверхед); если указан источник — это факт из источника.

## Сводная таблица

| Модель | Ollama-тег | Параметры | Дата релиза | Разработчик | Лицензия | Q4 размер GB / RAM | Русский | Tool calling / контекст | Как ассистент ПК |
|---|---|---|---|---|---|---|---|---|---|
| Qwen3.5-0.8B | `qwen3.5:0.8b` (Q4-тега НЕТ; дефолт Q8_0) | 752M (LLM) + 101M projector | 02.03.2026 (HF 28.02.2026) | Alibaba / Qwen | Apache-2.0 | Ollama Q8_0 1.2 ГБ (модель 812 МБ + projector 207 МБ); GGUF Q4_K_M 0.53 ГБ / ~1.5 ГБ | 201 язык заявлено, русский явно не назван → НЕ ПОДТВЕРЖДЕНО | tools+thinking / 256K | Edge/очень слабый ПК; слабое следование инструкциям |
| Qwen3.5-2B | `qwen3.5:2b`, `qwen3.5:2b-q4_K_M` | 1.88B (LLM) + 331M projector | 02.03.2026 (HF 28.02.2026) | Alibaba / Qwen | Apache-2.0 | Ollama q4_K_M 1.9 ГБ (1.3 + 0.671); GGUF Q4_K_M 1.28 ГБ / ~2.5 ГБ | см. выше | tools+thinking / 256K | Чат/суммаризация |
| Qwen3.5-4B | `qwen3.5:4b`, `qwen3.5:4b-q4_K_M` | 4.21B (LLM) + 334M projector | 02.03.2026 (HF 27.02.2026) | Alibaba / Qwen | Apache-2.0 | Ollama q4_K_M 3.3 ГБ (2.6 + 0.676); GGUF Q4_K_M 2.74 ГБ / ~4 ГБ | см. выше | tools+thinking / 256K | Лучший баланс; 107 tok/s CPU (llamabench, непровер.) |
| Qwen3.5-9B | `qwen3.5:9b`, `qwen3.5:9b-q4_K_M` | 8.95B (LLM) + 456M projector | 02.03.2026 | Alibaba / Qwen | Apache-2.0 | Ollama q4_K_M 6.6 ГБ (5.6 + 0.922) / ~8 ГБ | см. выше | tools+thinking / 256K | Для 16 ГБ RAM |
| Qwen3.5-0.5B / 1.7B | НЕТ (404) | — | — | — | — | — | — | — | Таких размеров НЕ существует |
| MiniCPM4-0.5B | нет на Ollama | 433.9M | 05–06.06.2025 | OpenBMB | Apache-2.0 | GGUF от сообщества; Q4 не проверен | en/zh → НЕ ПОДТВЕРЖДЕНО | tool use? / 32 768 | Очень слабая |
| MiniCPM4-8B | нет на Ollama | 8.19B | 06.06.2025 | OpenBMB | Apache-2.0 | ~5 ГБ (Q4) / ~6.5 ГБ | НЕ ПОДТВЕРЖДЕНО | 32K+ | 8B класс |
| MiniCPM4.1-8B | нет на Ollama | 8.19B | 02–05.09.2025 | OpenBMB | Apache-2.0 | Q4_K_M 4.97 ГБ / ~6.5 ГБ | НЕ ПОДТВЕРЖДЕНО | 65 536 | 8B класс, fusion thinking |
| MiniCPM5-1B | нет на Ollama | 1.08B | 21.05.2026 | OpenBMB | Apache-2.0 | Q4_K_M 0.69 ГБ / ~1.7 ГБ | нет в карточке → НЕ ПОДТВЕРЖДЕНО | XML tool calls (SGLang) / 131 072 | SOTA 1B, Think/No-Think |
| MiniCPM5-2B | нет на Ollama | 2.52B | 06.09.2026 | OpenBMB | Apache-2.0 | Q4_K_M 1.56 ГБ / ~3 ГБ | НЕ ПОДТВЕРЖДЕНО | XML tool calls / 131 072 | SOTA 2B, локальный ассистент/агент |
| GLM-4-9B-0414 | `glm4:9b` (5.5 ГБ, 128K) | 9.40B | 07.04.2025 | Z.ai (Zhipu) | MIT | ~5.5 ГБ (Ollama) / ~7 ГБ | НЕ ПОДТВЕРЖДЕНО | 128K | 9B класс |
| GLM-4.5-Air | нет на Ollama | 110.5B (12B active) | 20.07.2025 (анонс 28.07) | Z.ai | MIT | ~65 ГБ — НЕ для слабого ПК | НЕ ПОДТВЕРЖДЕНО | tools / 128K | Не подходит |
| GLM-4.7-Flash | `glm-4.7-flash` (q4_K_M 19 ГБ) | 31.2B MoE-lite | 19.01.2026 | Z.ai | MIT | 19 ГБ / ~24 ГБ | НЕ ПОДТВЕРЖДЕНО | tools+thinking / 198K | Только 32 ГБ RAM |
| GLM-4.6 | РЕТИРИД 16.06.2026, тегов нет | — | 29.09.2025 | Z.ai | — | — | — | — | — |
| GLM-5 / 5.1 / 5.2 / 5.3 / 5.3-Flash | только cloud (5.2/5.3/5.3-flash) | 756B / 18B active (Flash) | 11.02.2026 / 03.04 / 16.06 / 25.08.2026 | Z.ai | НЕ ПРОВЕРЕНО | — | — | 1M (Flash) | Не для локального ПК |
| EXAONE 3.5 2.4B | `exaone3.5:2.4b` | 2.4B | дек. 2024 (вне окна) | LG AI Research | EXAONE AI Model License 1.1 — NC (некоммерч.) | 1.6 ГБ / ~3 ГБ | НЕ ПОДТВЕРЖДЕНО (en/ko) | 32K | Ок для слабого ПК, но лицензия NC |
| EXAONE 3.5 7.8B | `exaone3.5:7.8b` (latest) | 7.8B | дек. 2024 | LG AI Research | EXAONE License 1.1 — NC | 4.8 ГБ / ~6 ГБ | НЕ ПОДТВЕРЖДЕНО | 32K | 8B класс |
| EXAONE 4.0 1.2B | нет на Ollama | 1.279B | 11.07.2025 | LG AI Research | EXAONE (other, NC) | нет офиц. GGUF-проверки; ~1 ГБ | en/ko/es → НЕ ПОДТВЕРЖДЕНО | гибридное reasoning / НЕ ПРОВЕРЕНО | On-device |
| EXAONE 4.5 33B | нет на Ollama | 34.35B (VLM) | 04.04.2026 (блог 09.04.2026) | LG AI Research | EXAONE AI Model License 1.2 — NC | Q4_K_M 20.05 ГБ + mmproj 2.58 ГБ | нет (en/ko/es/de/ja/vi) | VLM / НЕ ПРОВЕРЕНО | Не для слабого ПК |
| Hunyuan-0.5B-Instruct | нет на Ollama | 539M | 30.07.2025 | Tencent | Tencent Hunyuan Community License (не EU/UK/KR) | ~0.4 ГБ (INT4) / ~1 ГБ | НЕ ПОДТВЕРЖДЕНО | 256K (семейство) | Edge |
| Hunyuan-1.8B-Instruct | нет на Ollama | 1.791B | 30.07.2025 | Tencent | то же | ~1.2 ГБ / ~2.5 ГБ | НЕ ПОДТВЕРЖДЕНО | 256K | Слабый ПК |
| Hunyuan-4B-Instruct | нет на Ollama | 4.222B | 30.07.2025 | Tencent | то же (в LICENSE: release 04.08.2025) | ~2.5 ГБ (INT4) / ~4 ГБ | НЕ ПОДТВЕРЖДЕНО | 262 144 (256K) | Хороший кандидат, но лицензия ограничена территорией |
| Hunyuan-7B-Instruct | нет на Ollama | 7B | 30.07.2025 | Tencent | то же | ~4.5 ГБ / ~6 ГБ | НЕ ПОДТВЕРЖДЕНО | 256K | 8B класс |
| Hunyuan-A13B-Instruct | нет на Ollama | 13B (MoE) | 25.06.2025 | Tencent | то же | GGUF есть (размер не снят) | НЕ ПОДТВЕРЖДЕНО | 256K | 16 ГБ+ |
| InternLM3-8B-Instruct | нет на Ollama (internlm3 → 404) | 8B | 13.01.2025 | Shanghai AI Lab | НЕ ПРОВЕРЕНО | GGUF q4_k_m 5.36 ГБ / ~7 ГБ | НЕ ПОДТВЕРЖДЕНО | tools / НЕ ПРОВЕРЕНО | 8B класс |
| Intern-S1-mini | нет на Ollama | 8.539B (VLM) | 18.08.2025 | Shanghai AI Lab | Apache-2.0 | офиц. GGUF только Q8_0 8.72 ГБ (Q4 НЕТ) / ~10 ГБ | НЕ ПОДТВЕРЖДЕНО | VLM / НЕ ПРОВЕРЕНО | 16 ГБ RAM |
| Intern-Decision-0.8B / 2B / 4B | нет на Ollama | 853M / — / — | 26.09.2026 | Shanghai AI Lab | Apache-2.0 (0.8B; база Qwen3.5-0.8B) | не снято | НЕ ПОДТВЕРЖДЕНО | decision-making / НЕ ПРОВЕРЕНО | Специализир. |
| InternLM2.5-1.8B | `internlm2:1.8b` | 1.89B | 2024 (2 года назад) | Shanghai AI Lab | Apache-2.0 | Ollama Q4_0 1.1 ГБ / ~2 ГБ | НЕ ПОДТВЕРЖДЕНО | 32K | Вне окна дат |
| DeepSeek-R1-Distill 1.5B | `deepseek-r1:1.5b` | 1.5B | янв. 2025 | DeepSeek | MIT (проверить) | 1.1 ГБ / ~2 ГБ | НЕ ПОДТВЕРЖДЕНО | tools+thinking / 128K | Reasoning, «болтлив» |
| DeepSeek-R1-Distill 7B / 8B | `deepseek-r1:7b` / `:8b` | 7B / 8B | янв. 2025 | DeepSeek | MIT | 4.7 ГБ / 5.2 ГБ | НЕ ПОДТВЕРЖДЕНО | 128K | 8B класс |
| Kimi (малые) | `kimi-k2`, `kimi-k3`, `kimi-k2.6`, `kimi-k2.7-code` (все огромные) | нет <10B текстовых | K2.6 14.04.2026, K3 13.06.2026 | Moonshot AI | НЕ ПРОВЕРЕНО | — | — | — | Малых текстовых НЕТ |
| Yi-1.5-6B/9B | `yi` (есть на Ollama) | 6B / 9B | 2024 | 01.AI | НЕ ПРОВЕРЕНО | ~4/5.5 ГБ | НЕ ПОДТВЕРЖДЕНО | — | Новых релизов 2025–2026 нет |

## Соседние (проверено, доступны на Ollama)
- `qwen3:0.6b` 523 МБ, `qwen3:1.7b` 1.4 ГБ, `qwen3:4b` 2.5 ГБ (40K, у 4b 256K), tools+thinking — https://ollama.com/library/qwen3
- `qwen3.6` — только 27b/35b (18–24 ГБ), для слабого ПК НЕ подходит — https://ollama.com/library/qwen3.6
- `gemma3n:e2b` 5.6 ГБ, `:e4b` 7.5 ГБ, 32K — https://ollama.com/library/gemma3n
- `phi4-mini`, `granite4`, `granite4.1/4.2`, `aya` — есть на Ollama (размеры не сняты)
- `glm-ocr` — 1.6–2.2 ГБ, 128K, Text+Image (8 месяцев назад) — https://ollama.com/library/glm-ocr

## ЯВНО НЕ ПОДТВЕРЖДЕНО / НЕ ПРОВЕРЕНО
1. **Русский язык**: ни одна из перечисленных моделей не заявляет русский явно. Qwen3.5 — «201 язык» (без перечисления). MiniCPM — только en/zh. EXAONE — en/ko/es(+/de/ja/vi). Hunyuan/InternLM — zh/en. Единственные фактические данные по русскому: MERA (русский бенчмарк) — субмит Qwen3.5-122B-A10B (11.05.2026): Мульти 0.443 (место 4), Изображения 0.648 (1), Видео 0.727 (1). Результатов MERA для 0.8B/2B/4B/9B НЕ найдено. Сторонний квант cyankiwi/MiniCPM5-1B-AWQ-INT4 указывает языки EN ZH HI AR RU JA KO NL FR ES (не официально).
2. **RAM**: официальных требований не публикуется; в таблице — оценка (Q4 + 1–1.5 ГБ). НЕ факт из источника.
3. **Baichuan, TeleChat, Yi (2025–2026), Sarvam, Krutrim, японские (llm-jp, sarashina, nest-ja), корейские (HyperCLOVA X SEED, Kanana)** — исследование ещё идёт (делегировано), предварительно из HF API: sarvam-30b и sarvam-105b от 03.03.2026 (GGUF 20–23.03.2026), sarvam-m 20.05.2025, sarvam-1 23.10.2024; krutrim-ai-labs/Krutrim-2-instruct 02.02.2025, Chitrapathak-1/2 и Chitranuvad 11.03.2026; llm-jp-4-8b-instruct 30.03.2026, llm-jp-4.1-8b-thinking 15.09.2026; sarashina2.2-0.5b/1b/3b 03.03.2025; sbintuitions/nest-ja-0.1b и 0.6b 03.02.2026. Лицензии/размеры/контекст — не сняты.
4. **LM Studio**: подтверждено существование `lmstudio-community/Qwen3.5-4B-GGUF` (02.03.2026) и `bartowski/Qwen_Qwen3.5-4B-GGUF`, размеры не сняты.
5. **Скорость CPU**: только один непроверенный замер — Qwen3.5-4B Q4_K_M, llama.cpp, CPU, 32 ГБ RAM, ctx 8192, FA off, без speculative decoding: 107 tok/s decode, 4165 tok/s prefill, TTFT 127 мс. Модель CPU не указана → цифра нерепрезентативна.
6. Контекст Qwen3.5 подтверждён 262144 из config.json (text_config) для Qwen3.5-2B и страниц Ollama (256K); для 0.8B/4B/9B — только страницы Ollama.
7. Tool calling EXAONE 4.0/4.5, GLM-4.9B-0414, InternLM3, Hunyuan — НЕ ПРОВЕРЕНО.

## Источники
- Ollama qwen3.5: https://ollama.com/library/qwen3.5 · https://ollama.com/library/qwen3.5/tags · https://ollama.com/library/qwen3.5:0.8b · :2b · :4b · :2b-q4_K_M · :4b-q4_K_M · :9b-q4_K_M
- Qwen3.5 release news + 201 languages: https://github.com/QwenLM/Qwen3.5 (README, News 2026-03-02, 2026-02-16, строка «201 languages and dialects»)
- Qwen3.5 HF: https://huggingface.co/api/models/Qwen/Qwen3.5-2B (createdAt 2026-02-28, license apache-2.0) · https://huggingface.co/Qwen/Qwen3.5-2B/raw/main/config.json (max_position_embeddings 262144) · https://huggingface.co/api/models?author=Qwen&search=Qwen3.5 (список размеров: нет 0.5B/1.7B)
- GGUF Qwen3.5: https://huggingface.co/api/models/unsloth/Qwen3.5-4B-GGUF?blobs=true · /Qwen3.5-2B-GGUF · /Qwen3.5-0.8B-GGUF · https://huggingface.co/lmstudio-community/Qwen3.5-4B-GGUF
- CPU-замер: https://llamabench.ai/r/1083
- MERA (русский): https://mera.a-ai.ru/ru/multi/submits/460
- MiniCPM4/4.1/5: https://huggingface.co/openbmb/MiniCPM4-0.5B · /MiniCPM4-8B · /MiniCPM4.1-8B · /MiniCPM5-1B · /MiniCPM5-2B · GGUF: https://huggingface.co/api/models/openbmb/MiniCPM5-1B-GGUF?blobs=true · /MiniCPM5-2B-GGUF · /MiniCPM4.1-8B-GGUF · https://github.com/OpenBMB/MiniCPM · https://huggingface.co/cyankiwi/MiniCPM5-1B-AWQ-INT4
- GLM: https://ollama.com/library/glm4 · https://ollama.com/library/glm-4.6 · https://ollama.com/library/glm-4.7-flash · https://ollama.com/library/glm-5.2 · https://ollama.com/library/glm-5.3-flash · https://huggingface.co/api/models/zai-org/GLM-4.5-Air · /GLM-4-9B-0414 · /GLM-4.7-Flash · https://huggingface.co/api/models?author=zai-org&sort=createdAt
- EXAONE: https://ollama.com/library/exaone3.5 · https://ollama.com/library/exaone-deep · https://huggingface.co/api/models/LGAI-EXAONE/EXAONE-4.0-1.2B · /EXAONE-4.5-33B · https://huggingface.co/LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct/raw/main/LICENSE · https://huggingface.co/LGAI-EXAONE/EXAONE-4.5-33B/raw/main/LICENSE · https://huggingface.co/api/models/LGAI-EXAONE/EXAONE-4.5-33B-GGUF?blobs=true · https://www.lgresearch.ai/blog/view?seq=641 · https://huggingface.co/api/models?author=LGAI-EXAONE&sort=createdAt
- Hunyuan: https://huggingface.co/api/models?search=Hunyuan&author=tencent · https://huggingface.co/tencent/Hunyuan-4B-Instruct/raw/main/config.json · https://huggingface.co/tencent/Hunyuan-4B-Instruct/raw/main/LICENSE · https://huggingface.co/api/models/tencent/Hunyuan-0.5B-Instruct · /Hunyuan-1.8B-Instruct · /Hunyuan-4B-Instruct
- InternLM: https://ollama.com/library/internlm2 · https://ollama.com/library/internlm2:1.8b · https://huggingface.co/api/models/internlm/Intern-S1-mini · /Intern-Decision-0.8B · https://huggingface.co/api/models/internlm/Intern-S1-mini-GGUF?blobs=true · /internlm3-8b-instruct-gguf?blobs=true · https://huggingface.co/api/models?search=internlm3
- Kimi: https://huggingface.co/api/models?author=moonshotai&sort=createdAt · https://ollama.com/library/kimi-k2
- DeepSeek-R1: https://ollama.com/library/deepseek-r1
- Yi: https://huggingface.co/api/models?author=01-ai&sort=createdAt
- Прочее Ollama: https://ollama.com/library/qwen3 · /qwen3.6 · /gemma3n · /deepseek-r1 · /glm-ocr

---

# Дополнение A: DeepSeek / Baichuan / TeleChat / Yi / Kimi (проверено 13.10.2026)

| Модель | Ollama-тег | Параметры | Дата | Лицензия | Q4 GB / RAM | Русский | Tool/контекст |
|---|---|---|---|---|---|---|---|
| DeepSeek-R1-Distill-Qwen-1.5B | `deepseek-r1:1.5b` | 1.5B (Ollama 1.78B) | HF 20.01.2025 | MIT | 1.1 ГБ / ~2.5 ГБ | НЕ ПОДТВЕРЖДЕНО | tool-calling не заявлен / 131072 |
| DeepSeek-R1-Distill-Qwen-7B | `deepseek-r1:7b` | 7.62B | 20.01.2025 | MIT | 4.7 ГБ / ~6.5 ГБ | НЕ ПОДТВЕРЖДЕНО | 131072 |
| DeepSeek-R1-Distill-Llama-8B | `deepseek-r1:8b-llama-distill-q4_K_M` | 8.03B | 20.01.2025 | MIT | 4.9 ГБ / ~7 ГБ | НЕ ПОДТВЕРЖДЕНО | 131072 |
| DeepSeek-R1-0528-Qwen3-8B | `deepseek-r1:8b` (=эта модель) и `deepseek-r1:8b-0528-qwen3-q4_K_M` | 8.19B | HF 29.05.2025 | MIT | 5.2 ГБ / ~7.5 ГБ | НЕ ПОДТВЕРЖДЕНО | **карточка: enhanced support for function calling** / 131072 (YaRN ×4) |
| DeepSeek-OCR | `deepseek-ocr:3b` = 6.7 ГБ F16 (Q4-тега НЕТ) | 3.34B VLM/OCR | 17.10.2025 | MIT | GGUF Q8_0 3.13 ГБ + mmproj 0.45 ГБ | НЕ ПОДТВЕРЖДЕНО | max_tokens 8192 |
| DeepSeek-OCR-2 | нет на Ollama (404) | 3.39B | 27.01.2026 | **apache-2.0** | GGUF Q4_K_M 1.95 ГБ (sabafallah) | карточка: `language: multilingual` | — |
| DeepSeek-V4-Flash | — | **284B total / 13B active** (MoE), 1M ctx | 22.04.2026 | MIT | НЕ для 4–16 ГБ | — | — |
| DeepSeek-V4.1-Flash | — | **552B backbone / 8B prefill–16B decode**, 1M ctx | 10.09.2026 | MIT | НЕ для 4–16 ГБ | — | — |
| Baichuan-M2-32B | нет на Ollama | 32B (база Qwen2.5-32B), мед. | 10.08.2025 | apache-2.0 | офиц. GGUF Q4_K_M 21.89 ГБ | НЕ ПОДТВЕРЖДЕНО | не для 4–16 ГБ |
| Baichuan-M3-235B | нет на Ollama | 235B (база Qwen3-235B-A22B) | 13.01.2026 | apache-2.0 | — | — | — |
| Baichuan2-7B-Chat | нет на Ollama | 7B | 29.08.2023 (вне окна) | `baichuan2-community-license` (кастом) | GGUF Q4_K_M 4.61 ГБ | НЕ ПОДТВЕРЖДЕНО | — |
| TeleChat2-7B-32K | нет на Ollama; GGUF-квантов НЕ найдено | 7B | 12.02.2025 | кастомная «TeleChat模型社区许可协议» (коммерч. по заявке) | нет Q4 | НЕ ПОДТВЕРЖДЕНО | **карточка: Function Call** / 32768 |
| TeleChat3-36B-Thinking / -Coder | — | 36B | 24.12.2025 / 29.01.2026 | — | — | — | малых TeleChat3 НЕТ |
| Yi-1.5-6B-Chat / 9B-Chat | `yi:6b` 3.5 ГБ Q4_0, `yi:9b` 5.0 ГБ Q4_0 | 6.06B / 8.83B | 11.05.2024 / 10.05.2024 (вне окна) | apache-2.0 | — / 4K ctx (16K у 9B-Chat-16K) | НЕ ПОДТВЕРЖДЕНО (en/zh) | — |
| Yi-Coder-1.5B/9B | `yi-coder:1.5b`, `yi-coder:9b` | 1.5B / 9B | 2024-08 | apache-2.0 | — | НЕ ПОДТВЕРЖДЕНО | 131072 (9B) |
| Kimi-Linear-48B-A3B-Instruct | нет на Ollama | 48B total / 3B active, ctx **1M** | 30.10.2025 | MIT | ~30 ГБ | НЕ ПОДТВЕРЖДЕНО | не для 4–16 ГБ |
| Kimi-VL-A3B-Instruct | нет на Ollama | 16B total / 3B active, 128K | 09.04.2025 | MIT | — | — | VLM |
| Kimi-Audio-7B-Instruct | нет на Ollama | 7B, ctx 8192 | 25.04.2025 | MIT | ~5 ГБ | НЕ ПОДТВЕРЖДЕНО | аудио, не текстовый чат |
| Kimi-K2.5 / K2.6 / K2.7-Code / K3 | `kimi-k2.6`, `kimi-k2.7-code`, `kimi-k3` | огромные | 01.01.2026 / 14.04.2026 / 11.06.2026 / 13.06.2026 | — | — | — | малой (<10B) текстовой модели у Moonshot НЕТ |

**Уточнение по тегам Ollama:** `deepseek-r1:8b-0528-qwen3` БЕЗ суффикса кванта = 404; работают `-q4_K_M`, `-q8_0`, `-fp16`. `deepseek-r1:latest` = Qwen3-8B Q4_K_M 5.2 ГБ.

**Источники дополнения A**
- DeepSeek: https://huggingface.co/api/models/deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B · .../DeepSeek-R1-Distill-Qwen-7B · .../DeepSeek-R1-Distill-Llama-8B · .../DeepSeek-R1-0528-Qwen3-8B · https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B/raw/main/config.json · https://huggingface.co/api/models?author=deepseek-ai&limit=100&sort=createdAt&direction=-1 · https://ollama.com/library/deepseek-r1:1.5b · :7b · :8b · :8b-0528-qwen3-q4_K_M · :8b-llama-distill-q4_K_M · https://ollama.com/library/deepseek-r1/tags
- DeepSeek 2026/OCR: https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash/raw/main/README.md · /config.json · https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/raw/main/README.md · https://huggingface.co/api/models/deepseek-ai/DeepSeek-OCR · https://ollama.com/library/deepseek-ocr:3b · https://huggingface.co/api/models/ggml-org/DeepSeek-OCR-GGUF?blobs=true · https://huggingface.co/api/models/deepseek-ai/DeepSeek-OCR-2 · https://huggingface.co/deepseek-ai/DeepSeek-OCR-2/raw/main/README.md · https://huggingface.co/api/models/sabafallah/DeepSeek-OCR-2-GGUF?blobs=true · https://huggingface.co/api/models/deepseek-ai/DeepSeek-Prover-V2-7B
- Baichuan: https://huggingface.co/api/models/baichuan-inc/Baichuan-M2-32B · https://huggingface.co/baichuan-inc/Baichuan-M2-32B/raw/main/README.md · https://huggingface.co/api/models/baichuan-inc/Baichuan-M2-32B-Q4_K_M-GGUF?blobs=true · https://huggingface.co/api/models/baichuan-inc/Baichuan-M3-235B · https://huggingface.co/baichuan-inc/Baichuan2-7B-Chat/raw/main/README.md · https://huggingface.co/api/models?author=baichuan-inc&limit=100&sort=createdAt&direction=-1
- TeleChat: https://huggingface.co/api/models/Tele-AI/TeleChat2-7B-32K · https://huggingface.co/Tele-AI/TeleChat2-7B-32K/raw/main/config.json · https://huggingface.co/Tele-AI/TeleChat2-7B-32K/raw/main/README.md · https://huggingface.co/api/models?search=TeleChat3&limit=40&sort=createdAt&direction=-1 · https://github.com/Tele-AI/TeleChat2
- Yi: https://huggingface.co/api/models?author=01-ai&limit=100&sort=createdAt&direction=-1 · https://huggingface.co/api/models/01-ai/Yi-1.5-6B-Chat · .../Yi-1.5-9B-Chat-16K · https://huggingface.co/01-ai/Yi-1.5-6B-Chat/raw/main/config.json · https://ollama.com/library/yi:6b · https://ollama.com/library/yi:9b · https://ollama.com/library/yi-coder/tags
- Kimi: https://huggingface.co/api/models?author=moonshotai&limit=100&sort=createdAt&direction=-1 · https://huggingface.co/moonshotai/Kimi-Linear-48B-A3B-Instruct/raw/main/README.md · /config.json · https://huggingface.co/moonshotai/Kimi-VL-A3B-Instruct/raw/main/README.md · https://huggingface.co/api/models/moonshotai/Kimi-Audio-7B-Instruct · https://ollama.com/library/kimi-k3
