#!/usr/bin/env python3
"""Compile and deploy FaceMatchRegistry to the configured testnet.

Usage:
    python scripts/deploy.py                # deploy to CHAIN from .env (default amoy)
    python scripts/deploy.py --chain sepolia
    python scripts/deploy.py --compile-only # just compile and write contracts/FaceMatchRegistry.abi.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402

from faceid.chain import ChainClient, ChainError, save_deployment  # noqa: E402
from faceid.config import Settings  # noqa: E402
from faceid.networks import get_network  # noqa: E402
from faceid.report import utc_now_iso  # noqa: E402

SOLC_VERSION = "0.8.20"
CONTRACT_NAME = "FaceMatchRegistry"
SOURCE = ROOT / "contracts" / f"{CONTRACT_NAME}.sol"
ABI_OUT = ROOT / "contracts" / f"{CONTRACT_NAME}.abi.json"

console = Console()


def compile_contract(source: Path = SOURCE) -> tuple[list[dict], str]:
    from solcx import compile_standard, install_solc, set_solc_version

    install_solc(SOLC_VERSION)
    set_solc_version(SOLC_VERSION)
    output = compile_standard(
        {
            "language": "Solidity",
            "sources": {source.name: {"content": source.read_text(encoding="utf-8")}},
            "settings": {
                "optimizer": {"enabled": True, "runs": 200},
                "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}},
            },
        },
        solc_version=SOLC_VERSION,
    )
    artefact = output["contracts"][source.name][CONTRACT_NAME]
    return artefact["abi"], artefact["evm"]["bytecode"]["object"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chain", help="amoy or sepolia (overrides CHAIN in .env)")
    parser.add_argument("--compile-only", action="store_true")
    args = parser.parse_args(argv)

    with console.status(f"Compiling {CONTRACT_NAME}.sol with solc {SOLC_VERSION} ..."):
        abi, bytecode = compile_contract()
    ABI_OUT.write_text(json.dumps(abi, indent=2), encoding="utf-8")
    console.print(f"[green]Compiled[/] {SOURCE.name} -> {ABI_OUT.relative_to(ROOT)} ({len(bytecode) // 2} bytes)")
    if args.compile_only:
        return 0

    load_dotenv()
    settings = Settings.from_env()
    network = get_network(args.chain or settings.chain)
    if not settings.private_key:
        console.print("[red]PRIVATE_KEY is not set. Copy .env.example to .env and add a funded testnet key.[/]")
        return 5

    try:
        client = ChainClient(network, settings.rpc_url or network.default_rpc, settings.private_key)
        balance = client.balance()
        console.print(f"Deployer {client.address} has {balance:.6f} {network.native_symbol} on {network.name}")
        if balance == 0:
            console.print(f"[red]Wallet is empty. Get test funds at {network.faucet}[/]")
            return 5
        with console.status("Deploying contract and waiting for confirmation ..."):
            address, receipt = client.deploy(abi, "0x" + bytecode)
    except ChainError as exc:
        console.print(f"[red]{exc}[/]")
        return 4

    tx_hash = receipt["transactionHash"].hex()
    if not tx_hash.startswith("0x"):
        tx_hash = "0x" + tx_hash
    record = {
        "chain": network.key,
        "chain_id": network.chain_id,
        "address": address,
        "deployer": client.address,
        "tx_hash": tx_hash,
        "block_number": int(receipt["blockNumber"]),
        "deployed_at": utc_now_iso(),
        "solc": SOLC_VERSION,
        "abi": abi,
    }
    path = save_deployment(network.key, ROOT / "deployments", record)
    console.print(
        Panel.fit(
            f"[bold]Contract:[/] {address}\n"
            f"[bold]Explorer:[/] {network.address_url(address)}\n"
            f"[bold]Deploy tx:[/] {network.tx_url(tx_hash)}\n"
            f"[bold]Saved:[/] {path.relative_to(ROOT)}",
            title=f"FaceMatchRegistry deployed to {network.name}",
            border_style="green",
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
