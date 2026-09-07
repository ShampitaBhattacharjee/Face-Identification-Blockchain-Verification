"""Supported EVM testnets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Network:
    key: str
    name: str
    chain_id: int
    default_rpc: str
    explorer: str
    faucet: str
    native_symbol: str
    poa: bool
    min_priority_fee_gwei: float

    def tx_url(self, tx_hash: str) -> str:
        return f"{self.explorer}/tx/{tx_hash}"

    def address_url(self, address: str) -> str:
        return f"{self.explorer}/address/{address}"


NETWORKS: dict[str, Network] = {
    "amoy": Network(
        key="amoy",
        name="Polygon Amoy Testnet",
        chain_id=80002,
        default_rpc="https://rpc-amoy.polygon.technology",
        explorer="https://amoy.polygonscan.com",
        faucet="https://faucet.polygon.technology",
        native_symbol="POL",
        poa=True,
        min_priority_fee_gwei=30.0,  # Amoy enforces a 25 gwei minimum tip
    ),
    "sepolia": Network(
        key="sepolia",
        name="Ethereum Sepolia Testnet",
        chain_id=11155111,
        default_rpc="https://ethereum-sepolia-rpc.publicnode.com",
        explorer="https://sepolia.etherscan.io",
        faucet="https://cloud.google.com/application/web3/faucet/ethereum/sepolia",
        native_symbol="ETH",
        poa=False,
        min_priority_fee_gwei=1.5,
    ),
}


def get_network(key: str) -> Network:
    try:
        return NETWORKS[key.lower()]
    except KeyError as exc:
        raise ValueError(
            f"Unknown chain '{key}'. Supported: {', '.join(sorted(NETWORKS))}"
        ) from exc
