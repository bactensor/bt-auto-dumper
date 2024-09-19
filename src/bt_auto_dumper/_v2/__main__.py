import argparse
import json
import pathlib
import subprocess
import time
import zipfile

import bittensor as bt
import requests


def main(apiver: str | None = None):
    apiver = apiver or pathlib.Path(__file__).parent.name
    parser = argparse.ArgumentParser(description=f"BT Auto Dumper CLI {apiver}")
    parser.add_argument("--note", help="Comment or note for the operation", type=str, default="")
    parser.add_argument("--walletname", help="Wallet Name", type=str, required=True)
    parser.add_argument("--wallethotkey", help="Wallet Hotkey", type=str, required=True)
    parser.add_argument("subnet_identifier", help="Subnet Identifier", type=str)
    parser.add_argument("autovalidator_address", help="AutoValidator Address", type=str)

    args = parser.parse_args()

    dump_and_upload(args.walletname, args.wallethotkey, args.subnet_identifier, args.autovalidator_address, args.note)


def dump_and_upload(walletname, wallethotkey, subnet_identifier: str, autovalidator_address: str, note: str):
    subnets = {
        "compute_horde": ["echo 'Mainnet Command 1'", "echo 'Mainnet Command 2'"],
        "omron": ["echo 'Mainnet Command 1'", "echo 'Mainnet Command 2'"],
    }
    wallet = bt.wallet(name=walletname, hotkey=wallethotkey)
    commands = {}
    for subnet_id, command in subnets.items():
        if subnet_id == subnet_identifier:
            commands[subnet_id] = command
            break

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

    zip_filename = "output.zip"
    with zipfile.ZipFile(zip_filename, "w") as zipf:
        for file in output_files:
            zipf.write(file)
    send_to_autovalidator(zip_filename, wallet, autovalidator_address, note, subnet_identifier)


def make_signed_request(method, url, headers, files, wallet):
    headers["Nonce"] = str(time.time())
    headers["Hotkey"] = wallet.hotkey.ss58_address
    file_content = files.get("file").read()
    files.get("file").seek(0)
    headers_str = json.dumps(headers, sort_keys=True)
    data_to_sign = f"{method}{url}{headers_str}{file_content}".encode()
    signature = wallet.hotkey.sign(
        data_to_sign,
    ).hex()
    headers["Signature"] = signature

    response = requests.request(method, url, headers=headers, files=files)
    return response


def send_to_autovalidator(zip_filename, wallet, autovalidator_address, note, subnet_identifier):
    url = f"{autovalidator_address}/api/v1/files/"
    files = {"file": open(zip_filename, "rb")}

    headers = {
        "Note": note,
        "SubnetID": ",".join(subnet_identifier),
    }
    response = make_signed_request("POST", url, headers, files, wallet)
    if response.status_code == 201:
        print("File successfully uploaded and resource created.")
    elif response.status_code == 200:
        print("Request succeeded.")
    else:
        print(f"Failed to upload file. Status code: {response.status_code}")
        print(response.text)


if __name__ == "__main__":
    main()
