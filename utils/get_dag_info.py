import os
from dotenv import load_dotenv
import time
from datetime import datetime

from spectred.SpectredMultiClient import SpectredMultiClient
from utils.deflationary_table import DEFLATIONARY_TABLE
from utils.sompi_to_spr import sompis_to_spr


load_dotenv()
SPECTRED_HOSTS = os.getenv("SPECTRED_HOSTS").split(",")

network_info = {}


async def get_coin_supply(client):
    resp = await client.request("getCoinSupplyRequest", {})
    circulating_sompi = int(resp["getCoinSupplyResponse"]["circulatingSompi"])
    max_sompi = int(resp["getCoinSupplyResponse"]["maxSompi"])
    return {
        "circulatingSupply": sompis_to_spr(circulating_sompi),
        "maxSupply": sompis_to_spr(max_sompi),
    }


async def get_block_reward(daa_score):
    reward = 0
    for to_break_score in sorted(DEFLATIONARY_TABLE):
        reward = DEFLATIONARY_TABLE[to_break_score]
        if daa_score < to_break_score:
            break
    return reward


async def get_next_block_reward_info(daa_score):
    future_reward = 0
    daa_breakpoint = 0
    daa_list = sorted(DEFLATIONARY_TABLE)

    for i, to_break_score in enumerate(daa_list):
        if daa_score < to_break_score:
            future_reward = DEFLATIONARY_TABLE[daa_list[i + 1]]
            daa_breakpoint = to_break_score
            break

    next_halving_timestamp = int(time.time() + (daa_breakpoint - daa_score))
    next_halving_date = datetime.utcfromtimestamp(next_halving_timestamp).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )
    days_until_halving = (next_halving_timestamp - int(time.time())) / 86400

    return future_reward, next_halving_timestamp, next_halving_date, days_until_halving


async def get_last_blocks(client, num_blocks=100):
    # get the pruning point
    dag_info_resp = await client.request("getBlockDagInfoRequest", {})
    pruning_point = dag_info_resp["getBlockDagInfoResponse"]["pruningPointHash"]
    print(f"Pruning point hash: {pruning_point}")

    block_hashes = []
    low_hash = pruning_point

    while len(block_hashes) < num_blocks:
        # starting from low_hash
        blocks_resp = await client.request(
            "getBlocksRequest",
            {
                "lowHash": low_hash,
                "includeBlocks": True,
                "includeTransactions": True,
            },
        )
        response = blocks_resp["getBlocksResponse"]

        # block hashes and blocks from the response
        blocks_batch = response.get("blocks", [])

        for block in blocks_batch:
            block_hash = block["verboseData"]["hash"]
            is_chain_block = block["verboseData"].get("isChainBlock", False)
            print(f"Block {block_hash}: isChainBlock={is_chain_block}")

            if is_chain_block:
                block_hashes.append(block)
            if len(block_hashes) >= num_blocks:
                break

        # Update low_hash to the last block's hash for the next iteration
        if block_hashes:
            low_hash = block_hashes[-1]["verboseData"]["hash"]
        else:
            break

    return block_hashes


async def calculate_tps_spr_s(num_blocks=100):
    client = SpectredMultiClient(SPECTRED_HOSTS)
    await client.initialize_all()

    chain_blocks = await get_last_blocks(client, num_blocks)

    tps, sprs = 0, 0
    for block in chain_blocks:
        num_txs = len(block["transactions"])
        print(f"Block {block['verboseData']['hash']} has {num_txs} transactions.")

        tps += num_txs
        for tx in block["transactions"]:
            for output in tx["outputs"]:
                sprs += int(output["amount"])

    tps = (
        round(tps / len(chain_blocks), 1) if chain_blocks else 0
    )  # TPS = (Total number of transactions in 100 chained blocks) / 100
    sprs = (
        round(sompis_to_spr(sprs) / len(chain_blocks), 1) if chain_blocks else 0
    )  # SPR/s = (Total SPR transferred in 100 chained blocks) / 100

    return tps, sprs


async def update_network_info():
    global network_info

    client = SpectredMultiClient(SPECTRED_HOSTS)
    await client.initialize_all()

    dag_info_resp = await client.request("getBlockDagInfoRequest", {})
    dag_info = dag_info_resp["getBlockDagInfoResponse"]
    network_name = dag_info["networkName"]
    difficulty = dag_info["difficulty"]
    daa_score = int(dag_info["virtualDaaScore"])

    coin_supply = await get_coin_supply(client)
    block_reward = await get_block_reward(daa_score)
    (
        future_reward,
        next_halving_timestamp,
        next_halving_date,
        days_until_halving,
    ) = await get_next_block_reward_info(daa_score)

    network_info.update(
        {
            "Network Name": network_name,
            "Max Supply": coin_supply["maxSupply"],
            "Circulating Supply": coin_supply["circulatingSupply"],
            "Difficulty": difficulty,
            "Block Reward": f"{block_reward:.2f} -> {future_reward:.2f} in {days_until_halving:.1f} days",
            "Next Halving Date": f"{next_halving_date} (Timestamp: {next_halving_timestamp})",
            "virtualDaaScore": daa_score,
        }
    )
