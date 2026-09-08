"""Streamlit dashboard. Thin UI over the exact same library the CLI uses.

Run:  streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from faceid.chain import ChainClient, ChainError, build_calldata_payload, load_deployment  # noqa: E402
from faceid.config import Settings  # noqa: E402
from faceid.detect import NoFaceFoundError, detect_face  # noqa: E402
from faceid.networks import get_network  # noqa: E402
from faceid.search import ReverseImageSearcher, SearchError  # noqa: E402

load_dotenv()
settings = Settings.from_env()

st.set_page_config(page_title="Face ID Blockchain Verification", page_icon="🔗", layout="wide")
st.title("Face ID Blockchain Verification")
st.caption("Photo → face encoding → genuine reverse-image search → tamper-evident on-chain record")

with st.sidebar:
    st.header("Settings")
    chain_key = st.selectbox("Chain", ["amoy", "sepolia"], index=0 if settings.chain == "amoy" else 1)
    use_crop = st.checkbox("Search with face crop (instead of full photo)", value=False)
    anchor = st.checkbox("Anchor result on-chain", value=True)
    st.divider()
    st.write("SerpApi key:", "configured" if settings.serpapi_key else "missing")
    st.write("Wallet key:", "configured" if settings.private_key else "missing")
    st.write("Contract:", "deployed" if load_deployment(chain_key, ROOT / "deployments") else "not deployed (calldata mode)")

uploaded = st.file_uploader("Upload a photo you have consent to use", type=["jpg", "jpeg", "png"])
run = st.button("Run pipeline", type="primary", disabled=uploaded is None)

if uploaded and run:
    workdir = Path(tempfile.mkdtemp(prefix="faceid_"))
    image_path = workdir / uploaded.name
    image_path.write_bytes(uploaded.getbuffer())

    st.subheader("1 · Face detection & encoding")
    try:
        face = detect_face(image_path, workdir)
    except (NoFaceFoundError, RuntimeError) as exc:
        st.error(str(exc))
        st.stop()
    c1, c2 = st.columns([1, 3])
    c1.image(str(face.crop_path), caption="Detected face", width=180)
    c2.json(face.to_dict())

    st.subheader("2 · Reverse-image search (live)")
    searcher = ReverseImageSearcher(settings.serpapi_key, settings.bing_key, workdir, preferred_host=settings.image_host)
    try:
        with st.spinner("Uploading image and querying providers ..."):
            result = searcher.search(face.crop_path if use_crop else image_path)
    except SearchError as exc:
        st.error(str(exc))
        st.stop()
    st.write(f"Query URL: {result.image_url}  ·  providers: {', '.join(result.providers_used)}")
    st.dataframe(
        [
            {"score": m.score, "social": m.is_social, "post": m.is_post, "domain": m.domain, "title": m.title, "url": m.url}
            for m in result.matches[:25]
        ],
        use_container_width=True,
    )
    chosen = result.best_social()
    if chosen is None:
        st.error("No social-media match found. Nothing will be anchored.")
        st.stop()
    st.success(f"Selected match: {chosen.url}")

    if anchor:
        st.subheader("3 · Blockchain anchoring")
        network = get_network(chain_key)
        try:
            client = ChainClient(network, settings.rpc_url or network.default_rpc, settings.private_key)
            deployment = load_deployment(network.key, ROOT / "deployments")
            with st.spinner(f"Broadcasting on {network.name} ..."):
                if deployment:
                    contract = client.contract(settings.contract_address or deployment["address"], deployment["abi"])
                    res = client.record_match(contract, face.image_hash, face.embedding_hash, chosen.url, chosen.provider)
                else:
                    payload = build_calldata_payload(face.image_hash, face.embedding_hash, chosen.url, chosen.provider)
                    res = client.anchor_calldata(payload)
        except ChainError as exc:
            st.error(str(exc))
            st.stop()
        st.json(res.to_dict())
        st.markdown(f"**[View transaction on explorer]({res.explorer_url})**")
        if res.record_id is not None:
            st.code(f"python scripts/verify.py --record-id {res.record_id} --image <your photo> --chain {chain_key}")
        else:
            st.code(f"python scripts/verify.py --tx {res.tx_hash} --image <your photo> --chain {chain_key}")
