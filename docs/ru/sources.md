# Данные и исходные проекты

[English](../sources.md) · [Главная проекта](../../README.ru.md)

## Адресные данные

- Снимок российских диапазонов IPv4 получен из [RIPEstat](https://stat.ripe.net/data/country-resource-list/data.json?resource=RU&v4_format=prefix) 7 ноября 2026 года.
- Списки провайдеров получены из [Google](https://www.gstatic.com/ipranges/goog.json), [Cloudflare](https://www.cloudflare.com/ips-v4) и [Telegram](https://core.telegram.org/resources/cidr.txt) 8 и 9 ноября 2026 года.
- Каталог сервисов использует `amnezia.json` из [lib4u/amnezia-tunneling-ru](https://github.com/lib4u/amnezia-tunneling-ru/tree/64e090efba761ba11dd618e70dc7da1c8a345235). В снимок также вошли A-записи, полученные через [Google Public DNS](https://developers.google.com/speed/public-dns/docs/doh/json) 9 ноября 2026 года.

Снимки хранятся в [`data/`](../../data/). Генератор объединяет пересекающиеся диапазоны и сохраняет все российские и локальные префиксы в `ru-direct`. Чтобы сократить таблицу маршрутов, он добавляет в исключения часть других диапазонов. В комплектном снимке таких адресов 111 284 160. По модели маршрутизации старых версий Android получается 2 004 маршрута для `ru-direct` и 751 для `ru-services`. [Варианты списков и команды обновления](lists.md)

## AmneziaWG 3.1 и SPA

В комплект входят [amneziawg-go, коммит `1b86b2a`](https://github.com/amnezia-vpn/amneziawg-go/tree/1b86b2ae0e493e7ea93f8c1a0f0cb6735b1551f1) и [amneziawg-tools, коммит `ee0f0a9`](https://github.com/amnezia-vpn/amneziawg-tools/tree/ee0f0a9aa34ff0a0da4b3433b9512781cfe02843). Точные версии, лицензии и исходники amneziawg-tools лежат внутри архива в `dist/`. [Команда сборки](../../servers/build-native.sh) · [Лицензии](../../THIRD_PARTY_NOTICES.md)

Параметры AmneziaWG и формат экспорта взяты из [AmneziaVPN 5.1.0.6](https://github.com/amnezia-vpn/amnezia-client/tree/5.1.0.6). Имя `amnezia-awg2` в `.vpn` служит идентификатором в конфигурации клиента. Установщик запускает AmneziaWG через systemd, без Docker. Поддержка SPA в клиенте добавлена в форке COLDWIRE. [Код SPA-сервера](../../servers/spa/) · [Код VPN-клиента](https://github.com/bgunn9in/COLDWIRE-amnezia-client)
