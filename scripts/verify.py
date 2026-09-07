#!/usr/bin/env python3
"""Independently verify an anchored record and prove tamper-evidence.

Usage:
    python scripts/verify.py --record-id 0 --image samples/photo.jpg
    python scripts/verify.py --tx 0xabc... --image samples/photo.jpg   # calldata-mode anchor

The script reads the record straight from the chain (no local state is trusted), then
re-hashes the local image and compares it with the on-chain imageHash. Any single-bit
change to the photo makes the check FAIL.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from faceid.chain import ChainClient, ChainError, load_deployment  # noqa: E402
from faceid.config import Settings  # noqa: E402
from faceid.hashing import normalise_hex, sha256_file  # noqa: E402
from faceid.networks import get_network  # noqa: E402

console = Console()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--record-id", type=int, help="FaceMatchRegistry record id (contract mode)")
    parser.add_argument("--tx", help="Transaction hash of a calldata-mode anchor")
    parser.add_argument("--image", type=Path, help="Local image to re-hash and compare")
    parser.add_argument("--chain", help="amoy or sepolia (overrides CHAIN in .env)")
    args = parser.parse_args(argv)
    if args.record_id is None and not args.tx:
        parser.error("provide --record-id or --tx")

    load_dotenv()
    settings = Settings.from_env()
    network = get_network(args.chain or settings.chain)

    try:
        client = ChainClient(network, settings.rpc_url or network.default_rpc, private_key=None)
        if args.record_id is not None:
            deployment = load_deployment(network.key, ROOT / "deployments")
            address = settings.contract_address or (deployment or {}).get("address")
            if not deployment or not address:
                console.print("[red]No deployment found. Run scripts/deploy.py first or set CONTRACT_ADDRESS.[/]")
                return 5
            contract = client.contract(address, deployment["abi"])
            record = client.get_record(contract, args.record_id)
            on_chain_hash = record["imageHash"]
            title = f"Record #{args.record_id} @ {address}"
        else:
            anchor = client.get_calldata_anchor(args.tx)
            record = {**anchor["payload"], "timestamp": anchor["timestamp"], "tx_hash": anchor["tx_hash"], "block_number": anchor["block_number"]}
            on_chain_hash = record["imageHash"]
            title = f"Calldata anchor {args.tx}"
    except ChainError as exc:
        console.print(f"[red]{exc}[/]")
        return 4

    table = Table(title=title, show_lines=False)
    table.add_column("Field", style="bold")
    table.add_column("On-chain value")
    for key, value in record.items():
        if key == "timestamp":
            value = f"{value} ({datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()})"
        table.add_row(key, str(value))
    console.print(table)

    if not args.image:
        console.print("[yellow]Pass --image <file> to run the tamper-evidence check.[/]")
        return 0

    local_hash = sha256_file(args.image)
    ok = normalise_hex(local_hash) == normalise_hex(on_chain_hash)
    console.print(f"Local SHA-256 : {local_hash}")
    console.print(f"On-chain hash : {normalise_hex(on_chain_hash)}")
    if ok:
        console.print("[bold green]TAMPER-EVIDENCE CHECK PASSED - image matches the on-chain record[/]")
        return 0
    console.print("[bold red]TAMPER-EVIDENCE CHECK FAILED - image differs from the on-chain record[/]")
    return 1


if __name__ == "__main__":
    sys.exit(main())
