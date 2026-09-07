import pytest

from faceid.networks import NETWORKS, get_network


def test_amoy_defaults():
    n = get_network("amoy")
    assert n.chain_id == 80002
    assert n.poa is True
    assert n.tx_url("0xabc") == "https://amoy.polygonscan.com/tx/0xabc"


def test_sepolia_defaults():
    n = get_network("SEPOLIA")
    assert n.chain_id == 11155111
    assert n.address_url("0x1") == "https://sepolia.etherscan.io/address/0x1"


def test_unknown_network():
    with pytest.raises(ValueError):
        get_network("mainnet")


def test_every_network_has_faucet_and_explorer():
    for n in NETWORKS.values():
        assert n.faucet.startswith("https://")
        assert n.explorer.startswith("https://")
