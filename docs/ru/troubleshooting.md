# Проверка и решение проблем

[English](../troubleshooting.md) | Русский

В командах замените `ENTRY_IPV4` и `EXIT_IPV4` своими адресами; интерфейс `ens3`
замените интерфейсом VPS. Не переключайте единственный работающий VPN ради
диагностики. Для испытаний используйте отдельное устройство и отдельный peer,
сохраняя прямой профиль B. Установщикам нужны чистые серверы Debian 12/13
или Ubuntu 22.04/24.04/26.04 LTS amd64. Существующую установку они не восстанавливают.

## По симптомам

| Наблюдение | Проверка |
|---|---|
| Образ Ubuntu 26.04 не загружается / illegal instruction | Сверьте amd64/amd64v3 и возможности виртуального CPU; см. [отчёт LTS](validation-lts.md) |
| Напрямую B работает, через A нет | Endpoint A, нужный TCP/UDP-порт, firewall хостера, capture/forwarding/NAT A |
| Без исключений подключается, со списком нет | Режим «без VPN», «Заменить список», число маршрутов; попробовать `ru-services` |
| UDP443 не работает с локальным фильтром | Сравнить на тестовом устройстве с 32497; ключи менять не требуется |
| Подключено, сайты не открываются | Handshake/transfer, DNS, MTU, маршруты и IPv6 клиента |
| Нет административных функций | Тип экспорта и сохранённый верхний адрес управления B |
| После изменения настроек подключение идёт напрямую | Приложение пересоздало `last_config`; повторить конвертацию актуального экспорта |

Один peer на двух устройствах вызывает смену его Endpoint. Выдавайте отдельный
доступ каждому устройству. Перегенерация ключей B ломает ранее выданные профили.

## Установщик в Windows

Скрипт выбирает обычный CPython 3.10+ из зарегистрированных версий.
Команда `py -3` без точной версии может предпочесть сборку без GIL;
это описано в [руководстве Python для Windows](https://docs.python.org/3/using/windows.html).
При проверке текущие зависимости не установились на Python `3.13t`.
Если существующая `.venv` использует эту сборку, скрипт остановится до pip.
Переименуйте папку, сохранив её как резервную, и повторите `setup.ps1`
с обычным CPython.

## Windows и клиентские проверки

```powershell
Find-NetRoute -RemoteIPAddress ENTRY_IPV4
Find-NetRoute -RemoteIPAddress 77.88.55.88
Test-NetConnection EXIT_IPV4 -Port 22
```

Маршрут к A должен идти через физическое подключение. В режиме российских
исключений маршрут к проверяемому адресу Яндекса тоже должен быть прямым.
`Test-NetConnection -Port` проверяет **TCP**, не UDP AWG: успешный SSH не
доказывает доступность VPN, проверка TCP32497 также не проверяет AWG.

Откройте `https://api.ipify.org` без другого прокси: ожидается IPv4 B.
Яндекс Интернетометр при попадании его адресов в исключения должен показывать
провайдера клиента. Проверяйте результат, а не только статус «Подключено».
[Совместимость AdGuard и сравнение портов](windows-admin-port-diagnosis.md).

## Вход A

Команды чтения, не меняющие правила:

```bash
sysctl net.ipv4.ip_forward
systemctl status blackice-relay.service --no-pager
systemctl is-enabled blackice-relay.service
sudo nft list table ip blackice_relay
ip route get EXIT_IPV4
journalctl -u blackice-relay.service -n 40 --no-pager
systemctl list-timers --all --no-pager
```

Ожидаются forwarding=1, active/exited и enabled, DNAT на выбранный порт B
и masquerade только DNAT. Счётчик NAT обычно учитывает первый пакет нового
conntrack-соединения, а не каждый пакет потока. Для потока смотрите FORWARD
и короткий захват заголовков (tcpdump устанавливается отдельно):

```bash
sudo timeout 20 tcpdump -ni ens3 -nn 'udp and (port 443 or port 32497)'
```

Для других портов или TCP измените фильтр. Если трафик приходит на A,
но не пересылается к B, проверьте правила и маршрут A. Если на A нет трафика,
проверьте Endpoint, клиентский фильтр, роутер, сеть и firewall хостера. Отсутствие реле в `ss -lunp` нормально.

## Выход B

Для нативного AWG этого комплекта:

```bash
systemctl status awg-relay-kit-exit.service --no-pager
sudo /usr/local/libexec/awg-relay-kit/awg show awg0
sudo /usr/local/libexec/awg-relay-kit/awg show awg0 latest-handshakes
sudo /usr/local/libexec/awg-relay-kit/awg show awg0 endpoints
sudo /usr/local/libexec/awg-relay-kit/awg show awg0 transfer
sudo nft list table ip awg_exit
```

Ожидаются свежий handshake и двусторонняя передача. Через реле B должен видеть
Endpoint peer с IP A; NAT-порт источника может быть произвольным. Реальный IP
клиента означает прямое подключение. Если пакеты доставлены, но handshake
нет, сверьте регистрацию клиента, ключи/PSK и параметры AWG с рабочим
прямым профилем.

Не публикуйте `showconf`, `dump`, server.json, `.vpn` и pcap с payload:
они могут раскрывать секреты. Публичные peer-ключи и сетевые адреса тоже
сокращайте при публикации логов. [Устройство нативного сервиса](native-server.md).

## DNS, IPv6 и MTU

Обычный DNS и браузерный DoH проверяйте отдельно. DNS-запросы не становятся
прямыми только из-за включения сайта в исключения. Снимки защищают
1.1.1.1, 1.0.0.1 и 8.8.8.8 от попадания в обход VPN.

```bash
curl --noproxy '*' -4 https://api.ipify.org
curl --noproxy '*' -6 --max-time 10 https://api64.ipify.org
```

IPv4 должен совпасть с B. IPv6-выход комплект не реализует. Если второй запрос
показывает адрес провайдера, проверьте политику IPv6/KillSwitch клиента.
Виртуальный IPv6 в клиентском интерфейсе не доказывает IPv6-доступ через B.

Если короткие запросы проходят, а большие страницы зависают, проверяйте MTU
на тестовом клиенте, начиная со значения его профиля. Нативный установщик
выдаёт MTU1280; конвертер сохраняет MTU исходного экспорта.

Часть российского сервиса может использовать зарубежный CDN, отсутствующий
в `ru-services`. `ru-direct` охватывает RU шире, но намеренно направляет
часть зарубежных адресов без VPN. Выберите подходящий список, не объединяя оба.
Логи сохраняйте [штатным способом Amnezia](https://docs.amnezia.org/ru/documentation/instructions/logging/)
и перед публикацией удаляйте доступы, адреса узлов и данные пользователей.

## REALITY

```bash
systemctl status awg-relay-kit-xray.service --no-pager
journalctl -u awg-relay-kit-xray.service -n 40 --no-pager
sudo ss -ltnp
```

На B должен прослушиваться выбранный TCP-порт; на A слушающий сокет
не нужен. При подключении через A источником TCP-соединения на B будет A. Обычный TLS-handshake и
открытый TCP-порт ещё не доказывают работу VLESS: нужен запрос через настоящий
клиент с правильными UUID, shortId, SNI, ключом REALITY и Vision.

| Код/симптом | Что проверить |
|---|---|
| `XRAY_PREFLIGHT` | Поддерживаемая Debian/Ubuntu amd64, назначенный IP, свободный TCP-порт, чистый сервер |
| `XRAY_TLS_TARGET` | Доступ B к выбранному target, корректный сертификат, TLS1.3/h2/X25519; при необходимости задать `--reality-target` |
| `XRAY_BINARY_INSTALL` | Пакет/закреплённый SHA, свободное место, права `/usr/local/libexec` |
| `XRAY_ACTIVATION` | Journal systemd, права бинарника, TCP-порт, LoadCredential и готовность listener |
| Сервис активен, клиент не работает | Согласованность SNI/UUID/shortId/ключа/порта, часы, firewall, сеть клиента |
| Часть dual-stack сайтов не открывается | Сохранены ли серверные DNS `UseIPv4` и freedom sockopt `domainStrategy: UseIPv4` |

На Ubuntu 22.04 systemd 249 путь к credential передаётся через
`${CREDENTIALS_DIRECTORY}`, а не `%d`. DynamicUser должен иметь право прохода
через `/usr/local/libexec` и чтения бинарников. Прямого доступа
к закрытому состоянию сервера ему не требуется. Установщик
создаёт новые бинарные каталоги 0755; существующий закрытый общий каталог не
ослабляет, а отклоняет. Не выдавайте всем чтение `/etc/awg-relay-kit-xray`.

REALITY использует X25519; Python 3.10 `ssl.set_ecdh_curve('X25519')` на штатной
Ubuntu 22.04 непригоден для проверки этой группы. Используется OpenSSL:

```bash
openssl s_client -4 -connect TARGET_HOST:443 -servername TARGET_HOST -tls1_3 -groups X25519 -alpn h2 -verify_hostname TARGET_HOST -verify_return_error -no_ign_eof </dev/null
```

Не публикуйте закрытый config/server.json или клиентские JSON/URI. Проверка
`xray run -test -config ...` от root проверяет синтаксис, но не права DynamicUser
и не доступ клиента. В режиме `both` диагностируйте каждую службу отдельно;
перезапуск Xray не требует перезапуска AWG. [Обслуживание Xray](xray.md).

В [отчёте Debian 12/13](validation-debian.md) проверены все три режима, обычные перезагрузки, восстановление и полное срабатывание таймера.
