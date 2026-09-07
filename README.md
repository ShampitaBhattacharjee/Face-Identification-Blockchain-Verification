# Face ID Blockchain Verification

[![pipeline status](https://gitlab.com/hhgoa-group/face-id-blockchain-verification/badges/main/pipeline.svg)](https://gitlab.com/hhgoa-group/face-id-blockchain-verification/-/pipelines)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Solidity 0.8.20](https://img.shields.io/badge/solidity-0.8.20-363636)
![Polygon Amoy](https://img.shields.io/badge/chain-Polygon%20Amoy%20%7C%20Sepolia-8247e5)

A command-line pipeline that takes a photo, **detects and encodes the face**, finds a **real matching
social-media post via genuine reverse-image search** (SerpApi Google Lens, Yandex, Bing Visual Search), and
**anchors the match on a public blockchain** as a tamper-evident, independently verifiable record.

Nothing is hardcoded: every search result comes from a live API call and every anchor is a real testnet
transaction you can open on a block explorer.

```text
$ python main.py --image samples/photo.jpg

─── Stage 1/3 - Face detection & encoding ───
  Encoder            face_recognition (dlib ResNet, 128-d)
  Faces found        1
  Image SHA-256      9f2c...e1a7
  Embedding SHA-256  41d0...77b3

─── Stage 2/3 - Reverse-image search ───
  Providers used: google_lens/visual_matches, google_lens/exact_matches, yandex
   #  Score  Social  Post  Domain          Title / URL
   1   19.8   yes    yes   x.com           Jane Doe on X: "Excited to speak at DevConf today!"
   2   19.6   yes    yes   instagram.com   Jane Doe on Instagram: "Backstage at DevConf"
   ...

─── Stage 3/3 - Blockchain anchoring ───
  Wallet 0x5B3...f21 balance: 0.482 POL
  Contract: https://amoy.polygonscan.com/address/0x9aB...
  Tx hash:   0x7c1e...
  Record id: 0
  Explorer:  https://amoy.polygonscan.com/tx/0x7c1e...
```

---

## Architecture

```mermaid
flowchart LR
    A[Input photo] --> B[Stage 1<br/>detect.py<br/>dlib / DeepFace / OpenCV]
    B -->|128-d embedding<br/>face crop| C[SHA-256 image hash<br/>SHA-256 embedding hash]
    B --> D[Stage 2<br/>search.py]
    D -->|upload| E[(Temp image host<br/>litterbox / tmpfiles / 0x0)]
    E -->|public URL| F[SerpApi Google Lens<br/>SerpApi Yandex<br/>Bing Visual Search]
    F -->|ranked matches| G{Social post<br/>found?}
    G -->|no| X[exit 3 - nothing anchored]
    G -->|yes| H[Stage 3<br/>chain.py - web3.py]
    C --> H
    H -->|recordMatch()| I[FaceMatchRegistry.sol<br/>Polygon Amoy / Sepolia]
    I --> J[Tx hash + explorer link<br/>JSON report]
    J --> K[scripts/verify.py<br/>re-hash & compare]
```

| Stage | Module | What it does |
|---|---|---|
| 1 Face | `faceid/detect.py` | Detects the most prominent face, produces a 128-d embedding (`face_recognition`/dlib, falls back to DeepFace, then OpenCV Haar), saves a padded crop, computes SHA-256 of the image bytes and of the rounded embedding. |
| 2 Search | `faceid/search.py` | Uploads the image to a short-lived public host, queries SerpApi Google Lens (`visual_matches` + `exact_matches`), SerpApi Yandex Images and optionally Bing Visual Search. Results are de-duplicated and ranked: **social-media post** > social profile > everything else. Raw API responses are saved to `output/raw_*.json` for auditability. |
| 3 Chain | `faceid/chain.py`, `contracts/FaceMatchRegistry.sol` | Signs an EIP-1559 transaction locally and calls `recordMatch(imageHash, embeddingHash, postUrl, provider)`. Emits `MatchRecorded`, returns a sequential record id. If no contract is deployed yet it falls back to a calldata self-transaction so a demo never dead-ends. |
| Verify | `scripts/verify.py` | Reads the record back from the chain, re-hashes a local image and prints **PASSED/FAILED**. Any single-bit change to the photo fails the check. |

---

## Quick start

### 1. Clone and install

```bash
git clone https://gitlab.com/hhgoa-group/face-id-blockchain-verification.git
cd face-id-blockchain-verification
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

<details>
<summary><b>Installing dlib</b> (needed by <code>face_recognition</code>)</summary>

- **Ubuntu/Debian:** `sudo apt install build-essential cmake libopenblas-dev liblapack-dev` then `pip install dlib`
- **macOS:** `brew install cmake` then `pip install dlib`
- **Windows:** install Visual Studio Build Tools (C++ workload) + CMake, or `pip install dlib-bin`
- **No compiler?** Use Docker (below) or `pip install -r requirements-optional.txt` to get DeepFace, which the
  pipeline uses automatically when dlib is missing.
</details>

### 2. Configure `.env`

```bash
cp .env.example .env
```

| Variable | Required | Where to get it |
|---|---|---|
| `SERPAPI_KEY` | yes | Free account (100 searches/month): <https://serpapi.com/manage-api-key> |
| `PRIVATE_KEY` | yes | A **testnet-only** wallet. Create one in MetaMask and export the key, or run `python -c "from eth_account import Account; a=Account.create(); print(a.address, a.key.hex())"` |
| `CHAIN` | no | `amoy` (default) or `sepolia` |
| `RPC_URL` | no | Leave blank for the public RPC, or an Alchemy/Infura URL for reliability |
| `BING_API_KEY` | no | Azure *Bing Search v7* resource, adds a second independent provider |
| `CONTRACT_ADDRESS` | no | Override the address stored in `deployments/<chain>.json` |

Fund the wallet with test tokens: **Amoy** <https://faucet.polygon.technology> (select *Amoy*, paste your address),
**Sepolia** <https://cloud.google.com/application/web3/faucet/ethereum/sepolia>.

### 3. Deploy the smart contract (once per chain)

```bash
python scripts/deploy.py                 # uses CHAIN from .env
python scripts/deploy.py --chain sepolia
```

This compiles `contracts/FaceMatchRegistry.sol` with solc 0.8.20 (downloaded automatically by py-solc-x), deploys
it, and writes address + ABI to `deployments/<chain>.json`. Commit that file so judges can inspect your contract.

### 4. Run the pipeline

```bash
python main.py --image samples/photo.jpg
```

Useful flags:

| Flag | Effect |
|---|---|
| `--use-crop` | Search with the detected face crop instead of the whole photo |
| `--image-url URL` | You already host the image publicly; skip the temporary upload |
| `--providers google_lens,yandex,bing` | Choose providers (default: all that have keys) |
| `--chain sepolia` | Target Ethereum Sepolia instead of Polygon Amoy |
| `--anchor-mode contract\|calldata\|auto` | Force the anchoring method (default `auto`) |
| `--skip-chain` | Stop after the search stage (useful while tuning) |
| `--allow-non-social` | Anchor the best non-social match if no social post is found |
| `-v` | Verbose logging (upload host, provider responses) |

Exit codes: `0` success, `2` no face, `3` no social match (nothing anchored), `4` chain error, `5` configuration error.

Every run writes `output/report_<timestamp>.json` (hashes, all matches, chosen match, tx hash, explorer URL)
plus `output/raw_<provider>.json` with the untouched API responses.

### 5. Verify independently

```bash
python scripts/verify.py --record-id 0 --image samples/photo.jpg
# calldata-mode anchors:
python scripts/verify.py --tx 0x7c1e... --image samples/photo.jpg
```

The script trusts nothing local: it reads the record from the chain, recomputes the SHA-256 of the file you give
it and prints `TAMPER-EVIDENCE CHECK PASSED` or `FAILED`. Edit one pixel of the image and re-run to see it fail.

### Optional: dashboard and Docker

```bash
pip install -r requirements-optional.txt
streamlit run dashboard/app.py          # browser UI over the same library code

docker build -t faceid .
docker run --rm --env-file .env -v $PWD/samples:/app/samples -v $PWD/output:/app/output \
    -v $PWD/deployments:/app/deployments faceid --image samples/photo.jpg
```

---

## Which blockchain, and why

**Default: Polygon Amoy testnet** (chain id 80002, explorer <https://amoy.polygonscan.com>).

- Free test tokens from an official faucet, ~2 second blocks, so a live demo confirms in seconds.
- Fully EVM compatible: the same Solidity contract and `web3.py` code run unchanged on Ethereum.
- Public block explorer with verified event logs, so judges can click the link and see the record.

**Also supported: Ethereum Sepolia** (`CHAIN=sepolia`). Slower (~12 s blocks) and faucets are stricter, but it is the
canonical Ethereum testnet if that is preferred.

### On-chain data model (`contracts/FaceMatchRegistry.sol`)

```solidity
struct Record {
    bytes32 imageHash;      // SHA-256 of the original image bytes
    bytes32 embeddingHash;  // SHA-256 of the rounded 128-d face embedding
    string  postUrl;        // matching social-media post
    string  provider;       // e.g. google_lens:visual_matches
    uint256 timestamp;      // block.timestamp
    address submitter;      // wallet that anchored it
}
function recordMatch(bytes32, bytes32, string calldata, string calldata) external returns (uint256 id);
function getRecord(uint256 id) external view returns (Record memory);
function recordsByImageHash(bytes32) external view returns (uint256[] memory);
event MatchRecorded(uint256 indexed id, bytes32 indexed imageHash, ..., address indexed submitter);
```

The registry is append-only: there is no owner, no update and no delete function. Once mined, a record can only be
contradicted by a later record, never altered.

### Why this is tamper-evident

1. The photo is hashed (SHA-256) *before* anything is uploaded; the hash, not the image, goes on-chain.
2. The face embedding is also hashed, binding the record to the biometric result, not just the file.
3. The transaction is signed locally with your key and included in a block whose hash depends on every prior block.
4. Anyone can re-run `scripts/verify.py` with the original photo: a matching hash proves the image is byte-identical
   to what was anchored at that block time; any edit breaks the match.

---

## Project layout

```text
main.py                    CLI orchestrator (rich terminal UI, JSON report)
faceid/
  detect.py                Stage 1: detection + encoding, encoder fallbacks
  search.py                Stage 2: image upload, SerpApi/Bing providers, ranking
  chain.py                 Stage 3: web3 client, contract + calldata anchoring, read-back
  networks.py              Amoy / Sepolia parameters
  hashing.py, config.py, report.py
contracts/FaceMatchRegistry.sol
scripts/deploy.py          compile + deploy, writes deployments/<chain>.json
scripts/verify.py          independent on-chain verification
dashboard/app.py           optional Streamlit UI
tests/                     unit tests (no network, fixture data only)
RECORDING_SCRIPT.md        exact steps for the unedited demo video
```

Development: `make install-dev && make test && make lint`. CI runs ruff, pytest and a contract compile on every push.

---

## Known limitations

- **SerpApi quota.** The free tier allows 100 searches/month; each run uses 2 to 3 (Lens visual, Lens exact, Yandex).
  Use `--providers google_lens` to spend one per run.
- **Public URL requirement.** Google Lens and Yandex need a fetchable URL, so the image is uploaded to an anonymous
  temporary host (litterbox 1 h, tmpfiles 1 h, 0x0.st). Pass `--image-url` to use your own hosting instead.
- **Recall depends on the person's public footprint.** Reverse-image search finds the *same or near-identical photo*
  online. A photo that has never been posted publicly will produce web matches but rarely a social post; the pipeline
  then exits with code 3 and anchors nothing, by design.
- **Social-post heuristics.** Domains and URL patterns are used to classify "social post"; unusual URL shapes may be
  classified as a profile rather than a post (they still rank above non-social results).
- **Embedding hash is not a biometric standard.** It fingerprints one encoder's output; different encoders (or dlib
  versions) give different hashes for the same face. It should be read as "this exact biometric result was produced".
- **dlib build time.** Compiling dlib takes several minutes; use Docker or DeepFace if that is a problem.
- **Public RPC reliability.** Free public RPCs occasionally rate-limit; set `RPC_URL` to an Alchemy/Infura endpoint
  if you see timeouts. Amoy enforces a 25 gwei minimum priority fee; the client sets 30 gwei.
- **Testnet only.** No real value is at stake and testnets can be reset. Moving to mainnet is a config change but
  would cost gas and should include an access-control review of the contract.

## Privacy and ethics

- Only process photos of yourself or people who have explicitly consented. The `samples/` folder is empty on purpose.
- Nothing biometric is stored on-chain: only two SHA-256 hashes, a public URL that the search engine already indexes,
  and a timestamp. The photo itself is uploaded to a short-lived host and expires within an hour.
- The pipeline only ever returns URLs that are already publicly indexed by Google/Yandex/Bing; it does not log in to,
  scrape, or bypass any platform.

## License

MIT
