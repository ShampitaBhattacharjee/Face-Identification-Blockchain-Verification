#!/usr/bin/env python3
"""Face ID Blockchain Verification - end-to-end pipeline.

  photo -> face detection + encoding -> genuine reverse-image search
        -> social-media post match -> tamper-evident record on a public testnet

Examples:
  python main.py --image samples/photo.jpg
  python main.py --image samples/photo.jpg --chain sepolia --use-crop
  python main.py --image samples/photo.jpg --skip-chain          # search only
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from faceid import __version__
from faceid.config import Settings
from faceid.detect import FaceResult, NoFaceFoundError, detect_face
from faceid.networks import get_network
from faceid.report import utc_now_iso, write_report
from faceid.search import (
    DEFAULT_PROVIDERS,
    Match,
    MissingApiKeyError,
    ReverseImageSearcher,
    SearchError,
    SearchResult,
    load_fixture_result,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

console = Console(legacy_windows=False)

EXIT_OK = 0
EXIT_NO_FACE = 2
EXIT_NO_MATCH = 3
EXIT_CHAIN = 4
EXIT_CONFIG = 5

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "tests" / "fixtures" / "serpapi_google_lens.json"
DEPLOYMENTS = ROOT / "deployments"


class ConfigError(RuntimeError):
    """Missing or inconsistent configuration."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="main.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--image", required=True, type=Path, help="Input photo (JPEG/PNG).")
    p.add_argument("--image-url", help="Public URL of the same image; skips the temp-host upload.")
    p.add_argument("--use-crop", action="store_true", help="Search with the face crop instead of the full photo.")
    p.add_argument(
        "--providers",
        default=",".join(DEFAULT_PROVIDERS),
        help="Comma-separated providers: google_lens,yandex,bing (default: all configured).",
    )
    p.add_argument("--min-matches", type=int, default=1, help="Minimum social-media matches required.")
    p.add_argument(
        "--allow-non-social",
        action="store_true",
        help="If no social post is found, anchor the best non-social match instead of failing.",
    )
    p.add_argument("--chain", help="amoy (default) or sepolia. Overrides CHAIN in .env.")
    p.add_argument(
        "--anchor-mode",
        choices=("auto", "contract", "calldata"),
        default="auto",
        help="auto = deployed contract if available, else calldata self-transaction.",
    )
    p.add_argument("--skip-chain", action="store_true", help="Run face + search stages only.")
    p.add_argument("--output-dir", type=Path, default=Path("output"))
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="TESTING ONLY: fixture search data, no chain. Never valid for a submission run.",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args(argv)


# --------------------------------------------------------------------------- display


def banner(args: argparse.Namespace) -> None:
    console.print(
        Panel.fit(
            f"[bold]Face ID Blockchain Verification[/] v{__version__}\n"
            f"image: {args.image}   chain: {args.chain or 'from .env'}   "
            f"anchor: {args.anchor_mode}",
            border_style="cyan",
        )
    )


def print_face(face: FaceResult) -> None:
    t = Table(box=box.SIMPLE, show_header=False)
    t.add_column(style="bold")
    t.add_column()
    top, right, bottom, left = face.box
    t.add_row("Encoder", face.encoder)
    t.add_row("Faces found", str(face.num_faces))
    t.add_row("Bounding box", f"top={top} right={right} bottom={bottom} left={left}")
    t.add_row("Embedding dim", str(face.embedding.size))
    t.add_row("Crop saved", str(face.crop_path))
    t.add_row("Image SHA-256", face.image_hash)
    t.add_row("Embedding SHA-256", face.embedding_hash)
    console.print(t)


def print_matches(result: SearchResult, limit: int = 12) -> None:
    console.print(f"Query image URL: [link={result.image_url}]{result.image_url}[/link]")
    console.print(f"Providers used: {', '.join(result.providers_used)}")
    t = Table(title=f"Top {min(limit, len(result.matches))} of {len(result.matches)} matches", box=box.SIMPLE_HEAVY)
    t.add_column("#", justify="right")
    t.add_column("Score", justify="right")
    t.add_column("Social", justify="center")
    t.add_column("Post", justify="center")
    t.add_column("Domain")
    t.add_column("Title / URL", overflow="fold")
    for i, m in enumerate(result.matches[:limit], start=1):
        style = "bold green" if m.is_social and m.is_post else ("green" if m.is_social else "")
        t.add_row(
            str(i),
            f"{m.score:.1f}",
            "yes" if m.is_social else "-",
            "yes" if m.is_post else "-",
            m.domain,
            f"{m.title[:70]}\n[dim]{m.url}[/dim]",
            style=style,
        )
    console.print(t)


def print_summary(face: FaceResult, chosen: Match, anchor, report_path: Path) -> None:
    lines = [
        f"[bold]Image hash:[/]      {face.image_hash}",
        f"[bold]Embedding hash:[/]  {face.embedding_hash}",
        f"[bold]Matched post:[/]    [link={chosen.url}]{chosen.url}[/link]",
        f"[bold]Provider:[/]        {chosen.provider}",
    ]
    if anchor is not None:
        lines += [
            f"[bold]Chain:[/]           {anchor.chain} ({anchor.mode} mode)",
            f"[bold]Tx hash:[/]         {anchor.tx_hash}",
            f"[bold]Block:[/]           {anchor.block_number}   gas used: {anchor.gas_used}",
        ]
        if anchor.record_id is not None:
            lines.append(f"[bold]Record id:[/]       {anchor.record_id}")
        lines.append(f"[bold]Explorer:[/]        [link={anchor.explorer_url}]{anchor.explorer_url}[/link]")
    lines.append(f"[bold]Report:[/]          {report_path}")
    console.print(Panel("\n".join(lines), title="Pipeline complete", border_style="green"))


# --------------------------------------------------------------------------- stages


def anchor_match(args: argparse.Namespace, settings: Settings, face: FaceResult, match: Match):
    from faceid.chain import ChainClient, build_calldata_payload, load_deployment

    network = get_network(args.chain or settings.chain)
    if not settings.private_key:
        raise ConfigError(
            "PRIVATE_KEY is not set. Copy .env.example to .env and add a funded testnet wallet key."
        )
    rpc_url = settings.rpc_url or network.default_rpc
    with console.status(f"Connecting to {network.name} ..."):
        client = ChainClient(network, rpc_url, settings.private_key)
    balance = client.balance()
    console.print(f"Wallet {client.address} balance: {balance:.6f} {network.native_symbol}")
    if balance == 0:
        raise ConfigError(f"Wallet has no {network.native_symbol}. Fund it at {network.faucet}")

    deployment = load_deployment(network.key, DEPLOYMENTS)
    address = settings.contract_address or (deployment or {}).get("address")
    mode = args.anchor_mode
    if mode == "auto":
        mode = "contract" if (address and deployment) else "calldata"
        if mode == "calldata":
            console.print(
                "[yellow]No deployed contract for this chain; using calldata anchoring. "
                "Run `python scripts/deploy.py` for the smart-contract flow.[/]"
            )
    if mode == "contract":
        if not deployment or not address:
            raise ConfigError(
                f"No deployment for '{network.key}'. Run `python scripts/deploy.py --chain {network.key}`."
            )
        contract = client.contract(address, deployment["abi"])
        console.print(f"Contract: {network.address_url(address)}")
        with console.status("Sending recordMatch() and waiting for confirmation ..."):
            return client.record_match(
                contract, face.image_hash, face.embedding_hash, match.url, match.provider
            )
    payload = build_calldata_payload(
        face.image_hash, face.embedding_hash, match.url, match.provider, extra={"encoder": face.encoder}
    )
    with console.status("Broadcasting calldata anchor and waiting for confirmation ..."):
        return client.anchor_calldata(payload)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False, show_time=False)],
    )
    settings = Settings.from_env()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    banner(args)
    report: dict = {
        "version": __version__,
        "started_at": utc_now_iso(),
        "args": {k: str(v) for k, v in vars(args).items()},
    }

    # ---- Stage 1 -------------------------------------------------------
    console.rule("[bold cyan]Stage 1/3 - Face detection & encoding")
    try:
        with console.status("Detecting and encoding face ..."):
            face = detect_face(args.image, args.output_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        return EXIT_CONFIG
    except (NoFaceFoundError, RuntimeError) as exc:
        console.print(f"[red]{exc}[/]")
        return EXIT_NO_FACE
    print_face(face)
    report["face"] = face.to_dict()

    # ---- Stage 2 -------------------------------------------------------
    console.rule("[bold cyan]Stage 2/3 - Reverse-image search")
    if args.dry_run:
        console.print(Panel("DRY RUN - FIXTURE DATA - NOT A LIVE SEARCH", style="bold white on red"))
        result = load_fixture_result(FIXTURE)
    else:
        searcher = ReverseImageSearcher(
            serpapi_key=settings.serpapi_key,
            bing_key=settings.bing_key,
            output_dir=args.output_dir,
            preferred_host=settings.image_host,
        )
        query_image = face.crop_path if args.use_crop else face.image_path
        providers = [p for p in args.providers.split(",") if p.strip()]
        try:
            with console.status(f"Uploading image and querying {', '.join(providers)} ..."):
                result = searcher.search(query_image, image_url=args.image_url, providers=providers)
        except MissingApiKeyError as exc:
            console.print(f"[red]{exc}[/]")
            return EXIT_CONFIG
        except SearchError as exc:
            console.print(f"[red]{exc}[/]")
            return EXIT_NO_MATCH
    print_matches(result)
    report["search"] = result.to_dict()

    social = result.social_matches()
    if len(social) >= args.min_matches and social:
        chosen = social[0]
    elif args.allow_non_social and result.matches:
        chosen = result.matches[0]
        console.print("[yellow]No social-media post found; anchoring best non-social match (--allow-non-social).[/]")
    else:
        console.print(
            f"[red]Found {len(social)} social-media match(es), need {args.min_matches}. "
            "Nothing anchored. Try --use-crop, a different photo, or check raw_*.json in the output dir.[/]"
        )
        report["finished_at"] = utc_now_iso()
        write_report(report, args.output_dir)
        return EXIT_NO_MATCH
    report["chosen_match"] = chosen.to_dict()
    console.print(
        Panel(f"[bold green]{chosen.url}[/]\n{chosen.title}", title="Selected match", border_style="green")
    )

    # ---- Stage 3 -------------------------------------------------------
    console.rule("[bold cyan]Stage 3/3 - Blockchain anchoring")
    anchor = None
    if args.skip_chain or args.dry_run:
        console.print("[yellow]Chain stage skipped (--skip-chain / --dry-run).[/]")
    else:
        try:
            anchor = anchor_match(args, settings, face, chosen)
        except ConfigError as exc:
            console.print(f"[red]{exc}[/]")
            report["finished_at"] = utc_now_iso()
            write_report(report, args.output_dir)
            return EXIT_CONFIG
        except Exception as exc:  # noqa: BLE001 - surface any RPC/signing error cleanly
            console.print(f"[red]Anchoring failed: {exc}[/]")
            report["anchor_error"] = str(exc)
            report["finished_at"] = utc_now_iso()
            write_report(report, args.output_dir)
            return EXIT_CHAIN
        report["anchor"] = anchor.to_dict()

    report["finished_at"] = utc_now_iso()
    report_path = write_report(report, args.output_dir)
    print_summary(face, chosen, anchor, report_path)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
