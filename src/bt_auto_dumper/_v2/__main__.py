import argparse
import configparser
import json
import os
import pathlib
import re
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
    parser.add_argument("subnet_identifier", help="Subnet Identifier", type=str)
    parser.add_argument("autovalidator_address", help="AutoValidator Address", type=str)
    parser.add_argument("subnet_realm", help="Subnet Realm", type=str, choices=["testnet", "mainnet", "devnet"], default="mainnet")
    parser.add_argument("--set-autovalidator-address", help="Set a new autovalidator address", type=str)
    parser.add_argument("--set-codename", help="Set a new Subnet Identifier codename", type=str)

    args = parser.parse_args()

    # Get configuration directory from env variable.
    config_base_dir = os.getenv("CONFIG_DIR")

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
        print(f"Configuration updated successfully at {config_path}")

    if not (subnet_identifier := args.subnet_identifier) or not (autovalidator_address := args.autovalidator_address):
        autovalidator_address, subnet_identifier = load_config(config_path=config_path)
    dump_and_upload(subnet_identifier, args.subnet_realm, autovalidator_address, args.note)


def dump_and_upload(subnet_identifier: str, subnet_realm: str, autovalidator_address: str, note: str):
    """
    Dump and upload the output of the commands to the AutoValidator
    Args:
        subnet_identifier: Subnet Identifier
        subnet_realm: Subnet Realm
        autovalidator_address: AutoValidator Address
        note: Comment or note for the operation
    Example:
        dump_and_upload("computehorde", "mainnet", "http://localhost:8000", "Test")
    """
    subnets = {
        "computehorde": ["echo 'Mainnet Command 1'", "echo 'Mainnet Command 2'"],
        "omron": ["echo 'Mainnet Command 1'", "echo 'Mainnet Command 2'"],
    }

    wallet = bt.wallet(name="validator", hotkey="validator-hotkey")
    normalized_subnet_identifier = re.sub(r"[_\-.]", "", str.lower(subnet_identifier))
    commands = {}
    if normalized_subnet_identifier in subnets:
        commands = {normalized_subnet_identifier: subnets[normalized_subnet_identifier]}

    if not commands:
        print(f"Subnet identifier {subnet_identifier} not found.")
        return
    output_files = []
    for subnet_id, cmds in commands.items():
        for i, command in enumerate(cmds, start=1):
            output_file = f"{subnet_id}_{i}.txt"
            with open(output_file, "w") as f:
                f.write(f"Command: {command}\n")
                result = subprocess.run(command, shell=True, capture_output=True, text=True)
                f.write(result.stdout)
            output_files.append(output_file)

    zip_filename = f"{normalized_subnet_identifier}-output.zip"
    with zipfile.ZipFile(zip_filename, "w") as zipf:
        for file in output_files:
            zipf.write(file)
    send_to_autovalidator(zip_filename, wallet, autovalidator_address, note, normalized_subnet_identifier, subnet_realm)


def make_signed_request(
    method: str, url: str, headers: dict, file_path: str, wallet: bt.wallet, subnet_realm: str
) -> requests.Response:
    """
    Make a signed request to the AutoValidator
    Args:
        method: HTTP method
        url: URL
        headers: HTTP headers
        file_path: File path
        wallet: Wallet object
    Returns:
        Response object
    Example:
        make_signed_request(
            "POST",
            "http://localhost:8000/api/v1/files/",
            {"Note": "Test"},
            {"file": open("test.zip", "rb")},
            wallet
        )
    """
    headers["Nonce"] = str(time.time())
    headers["Hotkey"] = wallet.hotkey.ss58_address
    headers["Realm"] = subnet_realm
    files = {"file": open(file_path, "rb")}
    file = files.get("file")
    file_content = b""
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
    subnet_realm: str,
):
    """
    Send the dump file to the AutoValidator
    Args:
        zip_filename: Zip file name
        wallet: Wallet object
        autovalidator_address: AutoValidator Address
        note: Comment or note for the operation
        subnet_identifier: Subnet Identifier
    Example:
        send_to_autovalidator("test.zip", wallet, "http://localhost:8000", "Test", "computehorde")
    """
    url = f"{autovalidator_address}/api/v1/files/"

    headers = {
        "Note": note,
        "SubnetID": subnet_identifier,
    }
    response = make_signed_request("POST", url, headers, zip_filename, wallet, subnet_realm)
    if response.status_code == 201:
        print("File successfully uploaded and resource created.")
    elif response.status_code == 200:
        print("Request succeeded.")
    else:
        print(f"Failed to upload file. Status code: {response.status_code}")
        print(response.text)


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


if __name__ == "__main__":
    main()
