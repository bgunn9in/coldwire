#!/usr/bin/env python3
"""Copy a native Xray client JSON to a new IPv4 endpoint, preserving credentials."""
import argparse
import copy
import ipaddress
import json
from pathlib import Path
import sys
from exit_config import write_private


def convert(config, entry, port):
    ipaddress.IPv4Address(entry)
    if not 1 <= port <= 65535:
        raise ValueError('Invalid TCP port')
    result = copy.deepcopy(config)
    peers = [v for v in result['outbounds'] if v.get('protocol') == 'vless']
    if len(peers) != 1 or peers[0].get('streamSettings', {}).get('security') != 'reality' or len(peers[0]['settings']['vnext']) != 1:
        raise ValueError('Expected one VLESS REALITY outbound and one server')
    peers[0]['settings']['vnext'][0].update(address=entry, port=port)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--entry',required=True)
    parser.add_argument('--port',type=int,default=443)
    args=parser.parse_args()
    try:
        if args.input.stat().st_size>1_000_000:raise ValueError('Oversized profile')
        result=convert(json.loads(args.input.read_text(encoding='utf-8-sig')),args.entry,args.port)
        write_private(args.output,json.dumps(result,indent=2)+'\n')
        print('Created new client JSON; source and credentials preserved:',args.output)
    except (OSError,ValueError,KeyError,TypeError):
        print('Xray conversion failed; use a native client JSON and a NEW output file. Private data suppressed.',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':sys.exit(main())
