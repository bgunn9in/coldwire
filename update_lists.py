#!/usr/bin/env python3
"""Build exactly two Amnezia import lists, with bounded old-Android route counts."""
import argparse
import bisect
from concurrent.futures import ThreadPoolExecutor
import hashlib
import ipaddress as ip
import json
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
LOCAL = tuple(map(ip.IPv4Network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "100.64.0.0/10")))
RIPE = "https://stat.ripe.net/data/country-resource-list/data.json?resource=RU&v4_format=prefix"
CATALOG_REPO = "https://api.github.com/repos/lib4u/amnezia-tunneling-ru/commits/main"
SOURCES = {
    "telegram": "https://core.telegram.org/resources/cidr.txt",
    "cloudflare": "https://www.cloudflare.com/ips-v4",
    "google": "https://www.gstatic.com/ipranges/goog.json",
}


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 awg-relay-kit", "Accept": "application/json,text/plain,*/*"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError("Source exceeds the download limit")
    return raw


def collapse(networks):
    return list(ip.collapse_addresses(networks))


def complement(networks):
    result, cursor = [], 0
    for network in sorted(networks):
        start, end = int(network.network_address), int(network.broadcast_address)
        if start < cursor:
            raise ValueError("Overlapping or duplicate networks")
        if start > cursor:
            result.extend(ip.summarize_address_range(ip.IPv4Address(cursor), ip.IPv4Address(start - 1)))
        cursor = end + 1
    if cursor < 2**32:
        result.extend(ip.summarize_address_range(ip.IPv4Address(cursor), ip.IPv4Address(2**32 - 1)))
    return result


def contains(networks, network):
    starts = [int(n.network_address) for n in networks]
    index = bisect.bisect_right(starts, int(network.network_address)) - 1
    return index >= 0 and network.subnet_of(networks[index])


def legacy_routes(networks):
    # Android <13 excludes loopback before computing positive VPN routes; add IPv6 default.
    return len(complement(collapse(networks + [ip.IPv4Network("127.0.0.0/8")]))) + 1


def optimize(exact, protected, addresses, budget=2000):
    vpn = complement(exact)
    required = {n for n in vpn if any(a in n for a in addresses) or any(n.overlaps(p) for p in protected)}
    if len(required) > budget:
        raise ValueError("Protected VPN prefixes exceed the route budget; previous lists preserved")
    ranked = sorted(set(vpn) - required, key=lambda n: (-n.num_addresses, int(n.network_address)))
    kept = required | set(ranked[:max(0, budget - len(required))])
    # shortcut: all RU is retained by also bypassing small foreign gaps; exact policy needs a capable router/client.
    bypass = complement(kept)
    if not all(contains(bypass, n) for n in exact):
        raise ValueError("Lost RU coverage")
    if any(n.overlaps(p) for n in vpn if n not in kept for p in protected):
        raise ValueError("Protected foreign network bypassed")
    added = sum(n.num_addresses for n in bypass) - sum(n.num_addresses for n in exact)
    return bypass, added


def compact(exact, addresses):
    starts = [int(n.network_address) for n in exact]
    selected = set(LOCAL)
    for value in addresses:
        address = ip.ip_address(value)
        if address.version != 4:
            continue
        index = bisect.bisect_right(starts, int(address)) - 1
        if index >= 0 and address in exact[index]:
            selected.add(exact[index])
    result = collapse(selected)
    if not all(contains(exact, n) for n in result):
        raise ValueError("Compact list contains a non-RU/non-local network")
    if legacy_routes(result) > 1000:
        raise ValueError("Compact list exceeds 1000 legacy Android routes")
    if not contains(result, ip.IPv4Network("77.88.55.88/32")):
        raise ValueError("Yandex missing from the service list")
    return result


def encode(networks):
    entries = [{"hostname": f"direct-{str(n.network_address).replace('.', '-')}-{n.prefixlen}.invalid", "ip": str(n)} for n in networks]
    return (json.dumps(entries, indent=2) + "\n").encode()


def read_networks(path):
    return [ip.IPv4Network(line) for line in path.read_text().splitlines() if line and not line.startswith("#")]


def dns_lookup(domain):
    data = json.loads(fetch("https://dns.google/resolve?" + urllib.parse.urlencode({"name": domain, "type": "A"})))
    if data.get("Status") not in (0, 3):
        raise ValueError("DNS resolver failed for " + domain)
    return [str(ip.IPv4Address(a["data"])) for a in data.get("Answer", []) if a["type"] == 1]


def live_sources():
    country = json.loads(fetch(RIPE))
    if country.get("status") != "ok" or country.get("data_call_name") != "country-resource-list":
        raise ValueError("Unexpected RIPE response")
    ru = [ip.IPv4Network(n) for n in country["data"]["resources"]["ipv4"]]
    if len(ru) < 1000 or any(not n.is_global or n.prefixlen < 8 for n in ru):
        raise ValueError("Unexpected RU allocation count or prefix")
    exact = collapse(ru + list(LOCAL))
    protected = []
    for name, url in SOURCES.items():
        raw = fetch(url)
        if name == "google":
            values = [p["ipv4Prefix"] for p in json.loads(raw)["prefixes"] if "ipv4Prefix" in p]
        else:
            values = [line for line in raw.decode().splitlines() if line and ":" not in line and not line.startswith("#")]
        networks = [ip.IPv4Network(n) for n in values]
        if not networks or any(not n.is_global or n.prefixlen < 8 for n in networks):
            raise ValueError("Invalid protected provider prefixes: " + name)
        protected.extend(networks)
    commit = json.loads(fetch(CATALOG_REPO))["sha"]
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("Invalid catalog commit")
    catalog_url = f"https://raw.githubusercontent.com/lib4u/amnezia-tunneling-ru/{commit}/amnezia.json"
    catalog = json.loads(fetch(catalog_url))
    if not isinstance(catalog, list) or len(catalog) < 100:
        raise ValueError("Invalid service catalog")
    roots = (ROOT / "data/service-roots.txt").read_text().split()
    addresses, represented = set(), set()
    selected = 0
    for record in catalog:
        hostname = record["hostname"].lower().rstrip(".")
        matched = {r for r in roots if hostname == r or hostname.endswith("." + r)}
        if matched:
            selected += 1
            values = record.get("ips", []) or [record.get("ip", "")]
            values = [str(ip.ip_address(a)) for a in values if a]
            addresses.update(values)
            if values:
                represented.update(matched)
    if selected < 30:
        raise ValueError("Service catalog unexpectedly lost most selected domains")
    missing = sorted(set(roots) - represented)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for values in pool.map(dns_lookup, missing):
            addresses.update(values)
    if len(addresses) < 30:
        raise ValueError("Too few service addresses")
    print(f"RIPE snapshot: {country['data'].get('query_time')}; catalog commit: {commit}; {selected} catalog domains; {len(missing)} DNS fallbacks")
    return exact, collapse(protected), sorted(addresses)


def publish(output, full, services):
    # Publish into a NEW directory: failure never replaces either known working list.
    output = output.resolve()
    if output.exists():
        raise FileExistsError("Use a new --output directory; previous files are never overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".awg-lists-", dir=output.parent))
    try:
        for name, networks in (("ru-direct", full), ("ru-services", services)):
            raw = encode(networks)
            (staging / f"{name}.amnezia.json").write_bytes(raw)
            print(f"{name}: {len(networks)} entries, {legacy_routes(networks)} legacy routes, SHA256 {hashlib.sha256(raw).hexdigest()}")
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New output directory containing exactly two JSON files")
    parser.add_argument("--offline", action="store_true", help="Use the bundled source snapshots without network access")
    parser.add_argument("--entry", help="Optional entry IPv4 to keep outside the bypass list")
    parser.add_argument("--exit", help="Optional exit IPv4 to keep outside the bypass list")
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise FileExistsError("Output directory already exists")
        required = tuple(ip.IPv4Address(a) for a in (args.entry, args.exit, "1.1.1.1", "1.0.0.1", "8.8.8.8") if a is not None)
        if args.offline:
            exact = read_networks(ROOT / "data/ru-networks.txt")
            protected = read_networks(ROOT / "data/protected-vpn-networks.txt")
            addresses = (ROOT / "data/service-addresses.txt").read_text().split()
        else:
            exact, protected, addresses = live_sources()
        if exact != collapse(exact) or not exact or not protected or not addresses:
            raise ValueError("Invalid source snapshot")
        if any(contains(exact, ip.IPv4Network(f"{a}/32")) for a in required):
            raise ValueError("A protected address overlaps the RU/local source; resolve the policy conflict explicitly")
        full, added = optimize(exact, protected, required)
        services = compact(exact, addresses)
        if legacy_routes(full) > 2010:
            raise ValueError("Expanded list exceeds 2010 legacy Android routes")
        if any(contains(services, ip.IPv4Network(f"{a}/32")) for a in required):
            raise ValueError("Protected address in compact list")
        print(f"All {len(exact)} RU/local prefixes preserved; additionally {added:,} foreign addresses ({100 * added / 2**32:.3f}% of IPv4) bypass VPN in ru-direct")
        publish(args.output, full, services)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Update failed: {error}. Existing lists were not replaced.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
