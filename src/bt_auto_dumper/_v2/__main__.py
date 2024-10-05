import argparse
import configparser
import json
import logging
import os
import pathlib
import subprocess
import time
import zipfile
from io import BufferedReader

import bittensor as bt  # type: ignore
import requests
from dotenv import load_dotenv

load_dotenv()


def main(apiver: str | None = None):
    apiver = apiver or pathlib.Path(__file__).parent.name
    parser = argparse.ArgumentParser(description=f"BT Auto Dumper CLI {apiver}")
    parser.add_argument("--note", help="Comment or note for the operation", type=str, default="")
    parser.add_argument("--subnet_identifier", help="Subnet Identifier", type=str, default="")
    parser.add_argument("--autovalidator_address", help="AutoValidator Address", type=str, default="")
    parser.add_argument(
        "--chain",
        help="Specify the chain to use",
        type=str,
        choices=["testnet", "mainnet", "devnet"],
        default="mainnet",
    )
    parser.add_argument("--set-autovalidator-address", help="Set a new autovalidator address", type=str, default="")
    parser.add_argument("--set-codename", help="Set a new Subnet Identifier codename", type=str, default="")

    args = parser.parse_args()

    # Get configuration directory from env variable.
    config_base_dir = os.getenv("CONFIG_DIR", default="")

    # Check if the CONFIG_DIR environment variable is set
    if not config_base_dir:
        raise RuntimeError("CONFIG_DIR environment variable is not set.")

    config_expanded_dir = os.path.expanduser(config_base_dir)

    # Define the full path for the configuration file
    config_path = os.path.join(config_expanded_dir, "config.ini")

    # Check if the user wants to update config values
    if args.set_autovalidator_address or args.set_codename:
        update_confg(
            config_path=config_path,
            new_autovalidator_address=args.set_autovalidator_address,
            new_codename=args.set_codename,
        )
        logging.info(f"Configuration updated successfully at {config_path}")

    if not (subnet_identifier := args.subnet_identifier) or not (autovalidator_address := args.autovalidator_address):
        autovalidator_address, subnet_identifier = load_config(config_path=config_path)

    wallet = bt.wallet(name="validator", hotkey="validator-hotkey", path="~/.bittensor/wallets")
    dump_and_upload(subnet_identifier, args.chain, wallet, autovalidator_address, args.note)


def dump_and_upload(
    subnet_identifier: str, subnet_chain: str, wallet: bt.wallet, autovalidator_address: str, note: str
):
    """
    Dump and upload the logs of the commands to the AutoValidator
    Example:
        dump_and_upload("computehorde", "mainnet", "http://localhost:8000", "Test")
    """

    commands = get_commands_from_server(subnet_identifier, subnet_chain, wallet, autovalidator_address)
    if not commands:
        logging.error(f"Subnet dumper commands of {subnet_identifier} not found.")
        return
    logging.info(f"Subnet dumper commands of {subnet_identifier} retrieved successfully. {commands}")
    output_files = []
    for i, command in enumerate(commands, start=1):
        output_file = f"{subnet_identifier}_{i}.txt"
        with open(output_file, "w") as f:
            f.write(f"Command: {command}\n")
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            f.write(result.stdout)
        output_files.append(output_file)

    zip_filename = f"{subnet_identifier}-output.zip"
    with zipfile.ZipFile(zip_filename, "w") as zipf:
        for file in output_files:
            zipf.write(file)
    send_to_autovalidator(zip_filename, wallet, autovalidator_address, note, subnet_identifier, subnet_chain)


def make_signed_request(
    method: str, url: str, headers: dict, file_path: str, wallet: bt.wallet, subnet_chain: str
) -> requests.Response:
    """
    Example:
        >>> make_signed_request(
            "POST",
            "http://localhost:8000/api/v1/files/",
            {"Note": "Test"},
            "/path/test.zip",
            wallet,
            "mainnet"
        )

    """
    headers["Nonce"] = str(time.time())
    headers["Hotkey"] = wallet.hotkey.ss58_address
    headers["Realm"] = subnet_chain
    file_content = b""
    files = None
    if file_path:
        files = {"file": open(file_path, "rb")}
        file = files.get("file")

        if isinstance(file, BufferedReader):
            file_content = file.read()
            file.seek(0)
    headers_str = json.dumps(headers, sort_keys=True)
    data_to_sign = f"{method}{url}{headers_str}{file_content.decode(errors='ignore')}".encode()
    signature = wallet.hotkey.sign(
        data_to_sign,
    ).hex()
    headers["Signature"] = signature

    response = requests.request(method, url, headers=headers, files=files)
    return response


def send_to_autovalidator(
    zip_filename: str,
    wallet: bt.wallet,
    autovalidator_address: str,
    note: str,
    subnet_identifier: str,
    subnet_chain: str,
):
    """
    Example:
        >>> send_to_autovalidator("test.zip", wallet, "http://localhost:8000", "Test", "computehorde", "mainnet")

    """
    url = f"{autovalidator_address}/api/v1/files/"

    headers = {
        "Note": note,
        "SubnetID": subnet_identifier,
    }
    response = make_signed_request("POST", url, headers, zip_filename, wallet, subnet_chain)
    if response.status_code == 201:
        logging.info("File successfully uploaded and resource created.")
    elif response.status_code == 200:
        logging.warning("Request succeeded.")
    else:
        logging.error(f"Failed to upload file. Status code: {response.status_code}")
        logging.error(response.text)


def load_config(config_path: str) -> tuple[str, str]:
    """
    Load the configuration from the config file.

    Args:
        config_path (str): The path to the configuration file.

    Returns:
        tuple: A tuple containing the autovalidator address and the subnet codename.

    """

    # Check if the configuration file exist
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"{config_path} does not exist.")

    # Read the configuration file
    config = configparser.ConfigParser()
    try:
        config.read(config_path)
    except Exception as e:
        raise RuntimeError(f"Error reading configuration file: {config_path} \n Error:{e}")

    # Extract required values from the configuration
    try:
        autovalidator_address = config.get("autovalidator", "autovalidator_address")
        subnet_identifier = config.get("autovalidator", "codename")
    except Exception as e:
        raise KeyError(f"Configuration error: Missing in the config file. \n Error:{e}")

    return autovalidator_address, subnet_identifier


def update_confg(config_path: str, new_autovalidator_address: str, new_codename: str):
    """
    Updates the configuration with a new autovalidator address or codename.
    If the config file doesn't exist, it creates a new one with the provided
    new_autovalidator_address and new_codename.

    Args:
        config_path (str): The path to the configuration file.
        new_autovalidator_address (str): The new autovalidator address to be set.
        new_codename (str): The new subnet identifier codename to be set.

    """
    # Initialize a ConfigParser object
    config = configparser.ConfigParser()

    # Check if the configuration file exists
    if not os.path.exists(config_path):
        config["autovalidator"] = {}
    else:
        try:
            config.read(config_path)
        except Exception as e:
            raise RuntimeError(f"Error reading configuration file: {config_path} \n Error:{e}")

    if new_autovalidator_address:
        config.set("autovalidator", "autovalidator_address", new_autovalidator_address)

    if new_codename:
        config.set("autovalidator", "codename", new_codename)

    # Write or update the configuration file.
    try:
        with open(config_path, "w") as configfile:
            config.write(configfile)
    except Exception as e:
        raise RuntimeError(f"Failed to write to the configuration file: {config_path}.\n Error: {e}")


def get_commands_from_server(
    subnet_identifier: str, subnet_chain: str, wallet: bt.wallet, autovalidator_address: str
) -> list:
    """
    Example:
        >>> get_commands_from_server("computehorde", "mainnet", wallet, "http://localhost:8000")
        [
            "ps awux",
            "docker ps",
            "uptime",
            "free -m",
        ]

    """
    url = f"{autovalidator_address}/api/v1/commands/"
    headers = {
        "Note": "",
        "SubnetID": subnet_identifier,
    }
    response = make_signed_request("GET", url, headers, "", wallet, subnet_chain)
    if response.status_code == 200:
        data = response.json()
        return data
    else:
        logging.error(f"Failed to get commands. Status code: {response.status_code}")
        logging.error(response.text)
        return []


if __name__ == "__main__":
    main()
