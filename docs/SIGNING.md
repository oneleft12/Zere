# Подпись ZERE и «верифицированный» издатель в Windows

Windows блокирует ZERE не из-за кода, а из-за отсутствия подписи. Два разных
механизма:

| Механизм | Что делает | Что снимает блокировку |
|---|---|---|
| **Smart App Control** (Windows 11, WDAC) | не даёт запустить неподписанный exe вообще: «Политика ограничила приложение» | подпись Authenticode сертификатом от доверенного УЦ ([Microsoft Learn](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)) |
| **SmartScreen** | «Windows защитила ваш компьютер» у скачанного файла | подпись + накопленная репутация файла/издателя ([как считается](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)) |

Самоподписанный сертификат и «верификация» репозитория на GitHub **не
помогают**: Smart App Control проверяет цепочку доверия до корневых
сертификатов Windows, а не репозиторий. Нужен сертификат от публичного УЦ.

## Что уже готово в проекте

- **`installer/sign.ps1`** — подпись встроенными средствами PowerShell
  (`Set-AuthenticodeSignature`), Windows SDK и `signtool.exe` не нужны.
  Источник сертификата: `-Thumbprint` (USB-токен, облачный HSM, Certum),
  `-Pfx` (старый сертификат, локальная сборка) или `-SelfTest` (проверка
  конвейера; Windows такому сертификату не доверяет).
- **`installer/build-installer.ps1`** — параметры `-CertThumbprint`,
  `-PfxPath`, `-PfxPassword`, `-SelfTestSign`. Подписывает **оба** файла:
  `zere.exe` (внутри дистрибутива, до упаковки в payload) и `ZereSetup.exe`
  (после компиляции). Подпись одного установщика бесполезна: ярлыки запускают
  `zere.exe`, и Smart App Control проверяет именно его.
- **`.github/workflows/build-installer.yml`** — сборка и подпись в CI, если в
  секретах репозитория лежит сертификат.
- Подпись ставится с **меткой времени** (DigiCert): после истечения
  сертификата файл остаётся валидным.

## Как подписывать

```powershell
# сертификат на USB-токене / в облаке / в хранилище сертификатов
powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1 -CertThumbprint <ОТПЕЧАТОК>

# старый сертификат файлом .pfx
powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1 -PfxPath C:\keys\zere.pfx -PfxPassword <пароль>

# проверка конвейера без сертификата УЦ (для распространения не годится)
powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1 -SelfTestSign
```

Отпечаток сертификата: `Get-ChildItem Cert:\CurrentUser\My | Format-List Subject,Thumbprint`.
Проверка результата:

```powershell
Get-AuthenticodeSignature installer\Output\ZereSetup.exe | Format-List Status,StatusMessage,SignerCertificate,TimeStamperCertificate
```

`Status = Valid` — то, что нужно. `UnknownError`/`NotTrusted` — подпись есть,
но УЦ не доверенный (так выглядит `-SelfTestSign`).

## Где взять сертификат

### Вариант A. SignPath Foundation — бесплатно для открытых проектов

Сертификат OV-уровня выдан на **SignPath Foundation**, приватный ключ на их
HSM, подпись — в CI. Плюсы: 0 €, ключ не у тебя (не украдут). Минус: в
свойствах файла издатель — `SignPath Foundation`, а не «ZERE».

1. Заявка: <https://signpath.org/apply> (проект должен быть открытым, с
   лицензией и историей в git).
2. В SignPath создать организацию/проект, политику `release-signing`,
   конфигурацию артефактов (какие `.exe` подписывать) и API-токен.
3. В GitHub: secret `SIGNPATH_API_TOKEN`, variables `SIGNPATH_ORGANIZATION_ID`,
   `SIGNPATH_PROJECT_SLUG`, `SIGNPATH_POLICY_SLUG`, `SIGNPATH_CONFIG_SLUG`.
4. Порядок для полноценной подписи (иначе Smart App Control заблокирует
   приложение при первом запуске):
   - собрать `zere.exe` (`scripts\build-zere-exe.ps1`) и отправить его на
     подпись;
   - положить подписанный `zere.exe` в репозиторий сборки и дособрать
     установщик;
   - отправить на подпись получившийся `ZereSetup.exe`.

   Шаг отправки в workflow (`signpath/github-action-submit-signing-request@v2`):

   ```yaml
   - uses: actions/upload-artifact@v4
     id: upload
     with:
       name: unsigned
       path: installer/Output/ZereSetup.exe
   - uses: signpath/github-action-submit-signing-request@v2
     with:
       api-token: ${{ secrets.SIGNPATH_API_TOKEN }}
       organization-id: ${{ vars.SIGNPATH_ORGANIZATION_ID }}
       project-slug: ${{ vars.SIGNPATH_PROJECT_SLUG }}
       signing-policy-slug: ${{ vars.SIGNPATH_POLICY_SLUG }}
       artifact-configuration-slug: ${{ vars.SIGNPATH_CONFIG_SLUG }}
       github-artifact-id: ${{ steps.upload.outputs.artifact-id }}
       wait-for-completion: true
       output-artifact-directory: signed
   ```

### Вариант B. Certum Open Source Code Signing — €25–69, издатель — ты

Сертификат на твоё имя с префиксом «Open Source Developer», проект должен быть
открытым: <https://shop.certum.eu/open-source-code-signing.html>. Варианты:

| Комплект | Цена | Что получаешь |
|---|---|---|
| Код активации | **€25** | если уже есть карта cryptoCertum и ридер |
| Облако (SimplySign) | **€49** | подпись через приложение, без ридера; подходит для CI с их утилитой |
| Карта + ридер | **€69** | физический токен, стандартный путь для OV |

Срок действия сертификата — до 459 дней (с 02.2026), потом перевыпуск. После
установки карты/облачного профиля сертификат появляется в
`Cert:\CurrentUser\My` — дальше просто `-CertThumbprint`.

### Вариант C. Azure Artifact Signing (бывш. Trusted Signing)

<https://learn.microsoft.com/en-us/azure/artifact-signing/overview> — ~$10/мес,
ключ в FIPS 140-3 L3 HSM, лучший вариант для CI. Но Identity Validation
требует юрлицо с подтверждаемой историей; индивидуальному разработчику обычно
отказывают.

### Вариант D. Обычный OV/EV сертификат

€200–600/год у Sectigo/DigiCert/GlobalSign/SSL.com. С 2024 года **EV больше
не даёт мгновенную репутацию SmartScreen** — подписанный файл всё равно
сначала покажет предупреждение, пока не наберёт статистику.

## После подписи

1. **Проверить на чистой ВМ с включённым Smart App Control** — Microsoft
   просит тестировать установщик, приложение и деинсталлятор:
   <https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/test-your-app-with-smart-app-control>
2. **Отправить файл в Microsoft** как ложное срабатывание — ускоряет появление
   в «известных»: <https://www.microsoft.com/en-us/wdsi/filesubmission>.
3. **Репутация SmartScreen** набирается по загрузкам и запускам: свежий
   релиз на GitHub/сайте, версия не меняется без причины (каждая пересборка —
   новый файл без репутации).
4. **CI**: положить `.pfx` в base64 в секрет `SIGNING_PFX_BASE64`, пароль — в
   `SIGNING_PFX_PASSWORD`; workflow подпишет оба файла и проверит статус.

## Пока сертификата нет

- Установка из репозитория — работает без подписи:
  `installer\Install-Zere.bat` (скрипты Smart App Control не блокирует).
- Сам установщик — `.bat`/PowerShell, а не exe, поэтому его не блокируют.
- Опубликовать в **Microsoft Store** (MSIX): подпись Store доверенная, такие
  приложения SAC пропускает — но нужен аккаунт разработчика и упаковка MSIX.
- Отключать Smart App Control не советуем: обратно он включается только
  переустановкой Windows, и это ослабляет защиту машины.
