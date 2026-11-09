# Источники и границы проверки

[English](../sources.md) | Русский

Документация сверена с кодом комплекта и AmneziaVPN 5.1.0.6.
Для серверов поддерживаются **Ubuntu 22.04, 24.04 и 26.04 LTS amd64**.
Другие версии и архитектуры не поддерживаются. Имя `amnezia-awg2` в `.vpn`
обозначает элемент клиентского формата, а не необходимость Docker или версию 2.

## Первичные источники

- [AmneziaWG](https://docs.amnezia.org/documentation/amnezia-wg/).
- [Раздельное туннелирование](https://docs.amnezia.org/ru/documentation/instructions/vpn-split-tunneling/).
- [Исходники клиента 5.1.0.6](https://github.com/amnezia-vpn/amnezia-client/tree/5.1.0.6).
- [Импорт и декодирование](https://github.com/amnezia-vpn/amnezia-client/blob/5.1.0.6/client/core/controllers/selfhosted/importController.cpp).
- [Поля AWG/last_config](https://github.com/amnezia-vpn/amnezia-client/blob/5.1.0.6/client/core/models/protocols/awgProtocolConfig.cpp).
- [Повторное использование кэша](https://github.com/amnezia-vpn/amnezia-client/blob/5.1.0.6/client/core/controllers/selfhosted/installController.cpp).
- [Endpoint и исключение адреса сервера](https://github.com/amnezia-vpn/amnezia-client/blob/5.1.0.6/client/mozilla/localsocketcontroller.cpp).
- [Сообщение о потере CIDR в hostname](https://github.com/amnezia-vpn/amnezia-client/issues/2939).
- [Android ProtocolConfig](https://github.com/amnezia-vpn/amnezia-client/blob/dev/client/android/protocolApi/src/main/kotlin/ProtocolConfig.kt) — изменяемая ветка, поведение зависит от версии.
- [Android Binder и TransactionTooLargeException](https://developer.android.com/reference/android/os/TransactionTooLargeException).
- [Маршрутизация и фильтрация приложений AdGuard](https://adguard.com/kb/adguard-for-windows/app-management/).

## Адресные снимки

- RU IPv4: [RIPEstat](https://stat.ripe.net/data/country-resource-list/data.json?resource=RU&v4_format=prefix), query_time **2026-11-07**.
- Защищённые провайдеры: [Google](https://www.gstatic.com/ipranges/goog.json), [Cloudflare](https://www.cloudflare.com/ips-v4), [Telegram](https://core.telegram.org/resources/cidr.txt); снимки 8–9 ноября 2026 года, 154 свёрнутых IPv4-префикса.
- Каталог сервисов: [lib4u/amnezia-tunneling-ru](https://github.com/lib4u/amnezia-tunneling-ru), commit `64e090efba761ba11dd618e70dc7da1c8a345235`, файл `amnezia.json`, SHA256 `16e78eeac83c64e34311d165ed7f50f5b93f2c64651479af3c5653f6705213ec`.
- DNS-дополнение: [Google Public DNS JSON API](https://developers.google.com/speed/public-dns/docs/doh/json), снимок **2026-11-09T02:07:47Z**. A-записи получены для 15 из 22 недостающих семейств.

`data/ru-networks.txt` — 8678 свёрнутых RU/локальных префиксов;
`data/protected-vpn-networks.txt` — диапазоны провайдеров;
`data/service-addresses.txt` — адреса сервисов;
`data/service-roots.txt` — 86 выбранных семейств.
Это общие адресные данные, без настроенных VPN-узлов.
Офлайн-генерация без дополнительных IP воспроизводит приложенные JSON;
онлайн-генерация получает новые данные и выводит идентификатор каталога.
Покрытие, дополнительные адреса без VPN и хеши — в [lists.md](lists.md).

## Бинарный пакет AWG 3.1

Сборка `servers/build-native.sh` выполняется на отдельной Ubuntu 22.04 amd64:

- [amneziawg-go](https://github.com/amnezia-vpn/amneziawg-go/tree/1b86b2ae0e493e7ea93f8c1a0f0cb6735b1551f1), commit `1b86b2ae0e493e7ea93f8c1a0f0cb6735b1551f1`;
- [amneziawg-tools](https://github.com/amnezia-vpn/amneziawg-tools/tree/ee0f0a9aa34ff0a0da4b3433b9512781cfe02843), commit `ee0f0a9aa34ff0a0da4b3433b9512781cfe02843`;
- Go 1.25.12 с go.dev, SDK проверяется по закреплённому SHA256.

Manifest внутри пакета фиксирует источники и хеши. В архив входят лицензии
компонентов и соответствующие исходники GPL-инструмента; сохраняйте их при
распространении бинарного пакета. Компилятор на VPS не устанавливается.

Генерация параметров сверена с
[AwgInstaller](https://github.com/amnezia-vpn/amnezia-client/blob/5.1.0.6/client/core/installers/awgInstaller.cpp)
и [protocolConstants.h](https://github.com/amnezia-vpn/amnezia-client/blob/5.1.0.6/client/core/utils/constants/protocolConstants.h).
Формат клиентского экспорта —
[SelfHostedUserServerConfig](https://github.com/amnezia-vpn/amnezia-client/blob/5.1.0.6/client/core/models/selfhosted/selfHostedUserServerConfig.cpp),
format_version=1, без SSH-доступа. Ключи генерирует официальная `awg`.

## Xray REALITY

- [Xray-core 26.10.21](https://github.com/XTLS/Xray-core/releases/tag/v26.10.21) — закреплённый официальный linux-amd64 ZIP.
- [Исходники этой версии](https://github.com/XTLS/Xray-core/tree/v26.10.21), включая конфигурацию REALITY и freedom.
- [REALITY, первичное описание](https://github.com/XTLS/REALITY).
- [Официальная документация REALITY](https://xtls.github.io/en/config/transports/reality.html).
- [Импорт стороннего Xray в Amnezia 5.1.0.6](https://github.com/amnezia-vpn/amnezia-client/blob/5.1.0.6/client/core/controllers/selfhosted/importController.cpp).

Хеши upstream и собственного минимального пакета приведены в [xray.md](xray.md)
и manifest внутри `dist/xray-native-linux-amd64.tar.gz`. В пакет включена MPL 2.0
лицензия Xray и ссылка на соответствующий исходный тег. Базы geoip/geosite не
нужны этой конфигурации и не включены. `servers/fetch-xray.py` проверяет upstream
ZIP; установка сверяет собственный пакет с хешем, закреплённым в коде.

## Проверки

Автоматические тесты проверяют конвертацию синтетических профилей, сохранение
ключей и административного SSH host, отказ от перезаписи, покрытие/защиту
списков, расчёт маршрутов, архивы и проверки установщиков, SSH host keys
и порядок отказов deploy. Это не заменяет сетевого теста с реальным клиентом.

Полный нативный цикл установки, трафика, добавления peer, reboot и restore
выполнен на Ubuntu 22.04 VM по 1 vCPU / 1 ГБ; отдельный двухсерверный стенд
проверил deploy и handshake через реле. [Отчёт выхода](validation-native.md),
[проверка трёх режимов на Ubuntu 22.04](validation-protocols.md).
В более позднем [цикле LTS](validation-lts.md) проверены все три режима
на новых VM Ubuntu 24.04 и 26.04 с теми же 1 vCPU / 1 ГБ, включая sudo-rs,
Python 3.12/3.14, холодный запуск и восстановление. [Проверка обычной
перезагрузки](validation-lts.md#обычные-перезагрузки) добавила 24 перезагрузки
гостя 10 ноября с локально исправленной тестовой сборкой QEMU/WHPX.

Нативные AWG и Xray реально передавали трафик. Импорт AWG `.vpn`, Xray JSON
и VLESS URI проверен в AmneziaVPN 5.1.0.6 Linux внутри отдельной VM:
приложение сохранило нужные контейнеры и доступы, без подключения VPN GUI.
Импорт этих экспортов на всех физических Windows/macOS/Android/iOS устройствах
не проверялся. Заметка об AdGuard
описывает отдельное ручное наблюдение, не совместимость всех версий.
IPv6-выход отсутствует; все сочетания DNS/DoH/KillSwitch не проверялись.
Краткие измерения памяти не доказывают предел скорости, многосуточную
устойчивость или способность обходить конкретный DPI.
