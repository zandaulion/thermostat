"""Where the device inventory lives.

`devices.json` names rooms and carries cloud device ids, so it is deployment
data rather than source. It sits on the data volume beside the credentials,
and the repository ships only `devices.example.json`.

Resolution order:
  1. $DEVICES_FILE          -- explicit wins, for odd layouts and tests
  2. $DATA_DIR/devices.json -- the deployed container
  3. ./devices.json         -- a checkout run straight from the working tree
"""
import json
import os


def devices_path() -> str:
    explicit = os.environ.get("DEVICES_FILE")
    if explicit:
        return explicit
    data_dir = os.environ.get("DATA_DIR")
    if data_dir:
        candidate = os.path.join(data_dir, "devices.json")
        if os.path.exists(candidate):
            return candidate
    return "devices.json"


def load_devices() -> dict:
    """-> the inventory, or raise.

    Raising rather than returning {} is deliberate. An empty inventory makes
    every fetcher return "no devices, no error", which is indistinguishable
    from a healthy poll of a house with nothing in it -- the same silent
    failure this codebase already guards against elsewhere. The poller records
    the exception and /api/health shows it.
    """
    path = devices_path()
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Device inventory not found at {path}. Copy devices.example.json "
            "there and fill it in, or set DEVICES_FILE."
        )
    with open(path, "r") as f:
        return json.load(f)
