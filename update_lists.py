#!/usr/bin/env python3
"""Build exactly two Amnezia import lists, with bounded old-Android route counts."""
import argparse
import bisect
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from http.client import HTTPException
import ipaddress as ip
import json
from operator import attrgetter
import os
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
LOCAL = tuple(map(ip.IPv4Network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "100.64.0.0/10")))
LOOPBACK = ip.IPv4Network("127.0.0.0/8")
DIRECT_ROUTE_BUDGET = 2004
RIPE = "https://stat.ripe.net/data/country-resource-list/data.json?resource=RU&v4_format=prefix"
BUNDLED_RIPE_DATE = "2026-11-07"
ONLINE_SOURCE_FAILED = 2
LIST_NAMES = ("ru-direct", "ru-services")
CATALOG_REPO = "https://api.github.com/repos/lib4u/amnezia-tunneling-ru/commits/main"
SOURCES = {
    "telegram": "https://core.telegram.org/resources/cidr.txt",
    "cloudflare": "https://www.cloudflare.com/ips-v4",
    "google": "https://www.gstatic.com/ipranges/goog.json",
}


class SourceError(ValueError):
    pass


@contextmanager
def source(name):
    try:
        yield
    except (OSError, HTTPException, ValueError, KeyError, TypeError, AttributeError) as error:
        raise SourceError(f"{name}: {error}") from error


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 awg-relay-kit", "Accept": "application/json,text/plain,*/*"})
    if url == CATALOG_REPO:
        token = os.environ.get("COLDWIRE_LISTS_GITHUB_TOKEN")
        if token:
            request.add_unredirected_header("Authorization", f"Bearer {token}")
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
    index = bisect.bisect_right(networks, network.network_address, key=attrgetter("network_address")) - 1
    return index >= 0 and network.subnet_of(networks[index])


def legacy_routes(networks):
    # Android <13 excludes loopback before computing positive VPN routes; add IPv6 default.
    return len(complement(collapse(networks + [LOOPBACK]))) + 1


def optimize(exact, protected, addresses, budget=DIRECT_ROUTE_BUDGET):
    vpn = complement(collapse(exact + [LOOPBACK]))
    protected = collapse([*protected, *(ip.IPv4Network((address, 32)) for address in addresses)])
    required = set()
    for network in vpn:
        index = bisect.bisect_right(protected, network.broadcast_address, key=attrgetter("network_address")) - 1
        if index >= 0 and protected[index].broadcast_address >= network.network_address:
            required.add(network)
    slots = budget - 1 - len(required)  # Reserve one route for IPv6.
    if slots < 0:
        raise ValueError("Protected VPN prefixes exceed the route budget; previous lists preserved")
    ranked = sorted(set(vpn) - required, key=lambda n: (-n.num_addresses, int(n.network_address)))
    kept = required | set(ranked[:slots])
    # shortcut: all RU is retained by also bypassing small foreign gaps; exact policy needs a capable router/client.
    bypass = complement(collapse([*kept, LOOPBACK]))
    if not all(contains(bypass, n) for n in exact):
        raise ValueError("Lost RU coverage")
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
    with source(f"Google Public DNS ({domain})"):
        data = json.loads(fetch("https://dns.google/resolve?" + urllib.parse.urlencode({"name": domain, "type": "A"})))
        if data.get("Status") not in (0, 3):
            raise ValueError(f"DNS status {data.get('Status')}")
        return [str(ip.IPv4Address(a["data"])) for a in data.get("Answer", []) if a["type"] == 1]


def live_sources():
    with source("RIPEstat"):
        country = json.loads(fetch(RIPE))
        if country.get("status") != "ok" or country.get("data_call_name") != "country-resource-list":
            raise ValueError("Unexpected response")
        ru = [ip.IPv4Network(n) for n in country["data"]["resources"]["ipv4"]]
        if len(ru) < 1000 or any(not n.is_global or n.prefixlen < 8 for n in ru):
            raise ValueError("Unexpected RU allocation count or prefix")
        snapshot = country["data"]["query_time"]
    exact = collapse(ru + list(LOCAL))
    protected = []
    for name, url in SOURCES.items():
        with source(f"{name} IPv4 ranges"):
            raw = fetch(url)
            if name == "google":
                values = [p["ipv4Prefix"] for p in json.loads(raw)["prefixes"] if "ipv4Prefix" in p]
            else:
                values = [line for line in raw.decode().splitlines() if line and ":" not in line and not line.startswith("#")]
            networks = [ip.IPv4Network(n) for n in values]
            if not networks or any(not n.is_global or n.prefixlen < 8 for n in networks):
                raise ValueError("Invalid protected provider prefixes")
            protected.extend(networks)
    roots = (ROOT / "data/service-roots.txt").read_text().split()
    addresses, represented = set(), set()
    selected = 0
    with source("GitHub service catalog"):
        commit = json.loads(fetch(CATALOG_REPO))["sha"]
        if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
            raise ValueError("Invalid catalog commit")
        catalog_url = f"https://raw.githubusercontent.com/lib4u/amnezia-tunneling-ru/{commit}/amnezia.json"
        catalog = json.loads(fetch(catalog_url))
        if not isinstance(catalog, list) or len(catalog) < 100:
            raise ValueError("Invalid service catalog")
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
        raise SourceError("Service catalog and DNS returned too few service addresses")
    print(f"RIPE snapshot: {snapshot}; catalog commit: {commit}; {selected} catalog domains; {len(missing)} DNS fallbacks")
    return exact, collapse(protected), sorted(addresses)


def previous_prefixes(folder):
    previous = {}
    for name in LIST_NAMES:
        path = folder.expanduser() / f"{name}.amnezia.json"
        try:
            entries = json.loads(path.read_bytes())
            if not isinstance(entries, list):
                raise ValueError("Expected a JSON list")
            previous[name] = {ip.IPv4Network(entry["ip"]) for entry in entries}
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError(f"Invalid comparison file {path}: {error}") from error
    return previous


def publish(output, full, services, previous=None):
    # Publish into a NEW directory: failure never replaces either known working list.
    output = output.resolve()
    if output.exists():
        raise FileExistsError("Use a new --output directory; previous files are never overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".awg-lists-", dir=output.parent))
    try:
        for name, networks in zip(LIST_NAMES, (full, services)):
            raw = encode(networks)
            (staging / f"{name}.amnezia.json").write_bytes(raw)
            print(f"{name}: {len(networks)} entries, {legacy_routes(networks)} legacy routes, SHA256 {hashlib.sha256(raw).hexdigest()}")
            if previous is not None:
                current = set(networks)
                print(f"{name}: {len(current - previous[name])} added, {len(previous[name] - current)} removed IPv4 prefixes")
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def parser_options(parser):
    parser.add_argument("--output", type=Path,
                        help="New output directory (default: generated/ru-lists-<UTC timestamp>)")
    parser.add_argument("--offline", action="store_true", help="Use the bundled source snapshots without network access")
    parser.add_argument("--compare-with", type=Path, metavar="DIRECTORY",
                        help="Compare IPv4 prefixes with the two previous JSON files in this directory")
    parser.add_argument("--entry", help="Optional entry IPv4 to keep outside the bypass list")
    parser.add_argument("--exit", help="Optional exit IPv4 to keep outside the bypass list")
    parser.add_argument("--vpn-only", action="append", default=[], metavar="IPV4",
                        help="Keep an additional destination IPv4 outside both bypass lists; repeat for more addresses")


def generate(args):
    output = args.output or Path("generated") / datetime.now(timezone.utc).strftime("ru-lists-%Y%m%d-%H%M%S-%f")
    try:
        if output.exists():
            raise FileExistsError("Output directory already exists")
        previous = previous_prefixes(args.compare_with) if args.compare_with is not None else None
        required = tuple(ip.IPv4Address(a) for a in (args.entry, args.exit, *args.vpn_only,
                                                    "1.1.1.1", "1.0.0.1", "8.8.8.8") if a is not None)
        if args.offline:
            exact = read_networks(ROOT / "data/ru-networks.txt")
            protected = read_networks(ROOT / "data/protected-vpn-networks.txt")
            addresses = (ROOT / "data/service-addresses.txt").read_text().split()
            print(f"RIPE snapshot: {BUNDLED_RIPE_DATE} (bundled)")
        else:
            exact, protected, addresses = live_sources()
        if exact != collapse(exact) or not exact or not protected or not addresses:
            raise ValueError("Invalid source snapshot")
        if any(a in LOOPBACK or contains(exact, ip.IPv4Network((a, 32))) for a in required):
            raise ValueError("A protected address overlaps the RU/local or loopback ranges; resolve the policy conflict")
        full, added = optimize(exact, protected, required)
        services = compact(exact, addresses)
        if legacy_routes(full) > DIRECT_ROUTE_BUDGET:
            raise ValueError(f"Expanded list exceeds {DIRECT_ROUTE_BUDGET} legacy Android routes")
        if any(contains(services, ip.IPv4Network(f"{a}/32")) for a in required):
            raise ValueError("Protected address in compact list")
        print(f"All {len(exact)} RU/local prefixes preserved; additionally {added:,} foreign addresses ({100 * added / 2**32:.3f}% of IPv4) bypass VPN in ru-direct")
        publish(output, full, services, previous)
        print(f"Lists saved to {output.resolve()}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Update failed: {error}. Existing lists were not replaced.", file=sys.stderr)
        return ONLINE_SOURCE_FAILED if isinstance(error, SourceError) else 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser_options(parser)
    return generate(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
