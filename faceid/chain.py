"""Stage 3: tamper-evident anchoring on an EVM testnet via web3.py.

Two anchoring modes:
  * contract - call `FaceMatchRegistry.recordMatch()` (preferred, queryable, indexed event)
  * calldata - 0-value self-transaction whose `data` field carries a JSON payload; used
               automatically when no contract has been deployed so a demo never dead-ends.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from web3 import Web3

from faceid.hashing import to_bytes32
from faceid.networks import Network

log = logging.getLogger(__name__)

MAX_CALLDATA_BYTES = 8 * 1024
PAYLOAD_APP = "face-id-blockchain-verification"


class ChainError(RuntimeError):
    """RPC, signing or transaction failure."""


@dataclass
class AnchorResult:
    mode: str
    chain: str
    tx_hash: str
    block_number: int
    gas_used: int
    explorer_url: str
    submitter: str
    contract_address: str | None = None
    record_id: int | None = None
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _poa_middleware():
    try:  # web3 >= 7
        from web3.middleware import ExtraDataToPOAMiddleware

        return ExtraDataToPOAMiddleware
    except ImportError:  # web3 6.x
        from web3.middleware import geth_poa_middleware

        return geth_poa_middleware


def build_calldata_payload(
    image_hash: str,
    embedding_hash: str,
    post_url: str,
    provider: str,
    extra: dict[str, Any] | None = None,
) -> bytes:
    """Serialise the match as compact, sorted JSON for the calldata anchoring mode."""
    if not post_url:
        raise ChainError("post_url must not be empty")
    payload: dict[str, Any] = {
        "app": PAYLOAD_APP,
        "v": 1,
        "imageHash": image_hash,
        "embeddingHash": embedding_hash,
        "postUrl": post_url,
        "provider": provider,
        "ts": int(time.time()),
    }
    if extra:
        payload.update(extra)
    data = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(data) > MAX_CALLDATA_BYTES:
        raise ChainError(f"Payload too large ({len(data)} bytes > {MAX_CALLDATA_BYTES})")
    return data


def decode_calldata_payload(data: bytes | str) -> dict[str, Any]:
    if isinstance(data, str):
        data = bytes.fromhex(data[2:] if data.startswith("0x") else data)
    try:
        payload = json.loads(bytes(data).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ChainError("Transaction data is not a JSON anchor payload") from exc
    if not isinstance(payload, dict) or payload.get("app") != PAYLOAD_APP:
        raise ChainError("Transaction data is not a Face ID anchor payload")
    return payload


def load_deployment(chain_key: str, deployments_dir: str | Path) -> dict[str, Any] | None:
    path = Path(deployments_dir) / f"{chain_key}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_deployment(chain_key: str, deployments_dir: str | Path, data: dict[str, Any]) -> Path:
    path = Path(deployments_dir) / f"{chain_key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


class ChainClient:
    """Thin, explicit wrapper around web3.py with EIP-1559 fee handling."""

    def __init__(
        self,
        network: Network,
        rpc_url: str,
        private_key: str | None = None,
        timeout: int = 240,
    ) -> None:
        self.network = network
        self.rpc_url = rpc_url
        self.timeout = timeout
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 60}))
        if network.poa:
            self.w3.middleware_onion.inject(_poa_middleware(), layer=0)
        if not self.w3.is_connected():
            raise ChainError(f"Cannot reach RPC endpoint {rpc_url}")
        actual = self.w3.eth.chain_id
        if actual != network.chain_id:
            raise ChainError(
                f"RPC {rpc_url} reports chain id {actual}, expected "
                f"{network.chain_id} ({network.name}). Check RPC_URL / CHAIN."
            )
        self.account = self.w3.eth.account.from_key(private_key) if private_key else None

    #  account 

    @property
    def address(self) -> str:
        if self.account is None:
            raise ChainError("No PRIVATE_KEY configured; this client is read-only")
        return self.account.address

    def balance(self) -> float:
        return float(self.w3.from_wei(self.w3.eth.get_balance(self.address), "ether"))

    #  transaction plumbing 

    def _fees(self) -> dict[str, int]:
        latest = self.w3.eth.get_block("latest")
        base_fee = latest.get("baseFeePerGas")
        floor = int(Web3.to_wei(self.network.min_priority_fee_gwei, "gwei"))
        try:
            priority = int(self.w3.eth.max_priority_fee)
        except Exception:  # noqa: BLE001 - some RPCs lack eth_maxPriorityFeePerGas
            priority = 0
        priority = max(priority, floor)
        if base_fee is None:  # legacy chain
            return {"gasPrice": max(int(self.w3.eth.gas_price), floor)}
        return {"maxPriorityFeePerGas": priority, "maxFeePerGas": int(base_fee) * 2 + priority}

    def _base_params(self) -> dict[str, Any]:
        return {
            "from": self.address,
            "nonce": self.w3.eth.get_transaction_count(self.address, "pending"),
            "chainId": self.network.chain_id,
            **self._fees(),
        }

    def _sign_and_send(self, tx: dict[str, Any]) -> Any:
        if "gas" not in tx:
            tx["gas"] = int(self.w3.eth.estimate_gas(tx) * 1.2)
        signed = self.account.sign_transaction(tx)  # type: ignore[union-attr]
        raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        tx_hash = self.w3.eth.send_raw_transaction(raw)
        log.info("Broadcast %s", Web3.to_hex(tx_hash))
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=self.timeout)
        if receipt["status"] != 1:
            raise ChainError(f"Transaction {Web3.to_hex(tx_hash)} reverted")
        return receipt

    def _result(self, mode: str, receipt: Any, **extra: Any) -> AnchorResult:
        tx_hash = Web3.to_hex(receipt["transactionHash"])
        return AnchorResult(
            mode=mode,
            chain=self.network.key,
            tx_hash=tx_hash,
            block_number=int(receipt["blockNumber"]),
            gas_used=int(receipt["gasUsed"]),
            explorer_url=self.network.tx_url(tx_hash),
            submitter=self.address,
            **extra,
        )

    #  contract mode 

    def deploy(self, abi: list[dict[str, Any]], bytecode: str) -> tuple[str, Any]:
        contract = self.w3.eth.contract(abi=abi, bytecode=bytecode)
        tx = contract.constructor().build_transaction(self._base_params())
        receipt = self._sign_and_send(tx)
        return receipt["contractAddress"], receipt

    def contract(self, address: str, abi: list[dict[str, Any]]):
        return self.w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)

    def record_match(
        self, contract: Any, image_hash: str, embedding_hash: str, post_url: str, provider: str
    ) -> AnchorResult:
        fn = contract.functions.recordMatch(
            to_bytes32(image_hash), to_bytes32(embedding_hash), post_url, provider
        )
        tx = fn.build_transaction(self._base_params())
        receipt = self._sign_and_send(tx)
        record_id: int | None = None
        try:
            from web3.logs import DISCARD

            logs = contract.events.MatchRecorded().process_receipt(receipt, errors=DISCARD)
            if logs:
                record_id = int(logs[0]["args"]["id"])
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not decode MatchRecorded event: %s", exc)
        return self._result(
            "contract",
            receipt,
            contract_address=contract.address,
            record_id=record_id,
            payload={
                "imageHash": image_hash,
                "embeddingHash": embedding_hash,
                "postUrl": post_url,
                "provider": provider,
            },
        )

    def get_record(self, contract: Any, record_id: int) -> dict[str, Any]:
        rec = contract.functions.getRecord(record_id).call()
        return {
            "id": record_id,
            "imageHash": Web3.to_hex(rec[0]),
            "embeddingHash": Web3.to_hex(rec[1]),
            "postUrl": rec[2],
            "provider": rec[3],
            "timestamp": int(rec[4]),
            "submitter": rec[5],
        }

    #  calldata mode 

    def anchor_calldata(self, payload: bytes) -> AnchorResult:
        tx = {**self._base_params(), "to": self.address, "value": 0, "data": Web3.to_hex(payload)}
        receipt = self._sign_and_send(tx)
        return self._result("calldata", receipt, payload=decode_calldata_payload(payload))

    def get_calldata_anchor(self, tx_hash: str) -> dict[str, Any]:
        tx = self.w3.eth.get_transaction(tx_hash)
        receipt = self.w3.eth.get_transaction_receipt(tx_hash)
        block = self.w3.eth.get_block(receipt["blockNumber"])
        return {
            "tx_hash": Web3.to_hex(receipt["transactionHash"]),
            "block_number": int(receipt["blockNumber"]),
            "from": tx["from"],
            "to": tx["to"],
            "timestamp": int(block["timestamp"]),
            "payload": decode_calldata_payload(tx["input"]),
        }
