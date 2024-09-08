import argparse
import pathlib
import subprocess
import zipfile

import requests


def main(apiver: str | None = None):
    apiver = apiver or pathlib.Path(__file__).parent.name
    parser = argparse.ArgumentParser(description=f"BT Auto Dumper CLI {apiver}")
    parser.add_argument("subnet_identifier", help="Subnet Identifier", type=str)
    parser.add_argument("autovalidator_address", help="AutoValidator Address", type=str)
    parser.add_argument("api_key", help="API Key", type=str)

    args = parser.parse_args()

    dump_and_upload(args.subnet_identifier, args.autovalidator_address, args.api_key)


def dump_and_upload(subnet_identifier: str, autovalidator_address: str, api_key: str):
    subnets = {
        "compute_horde": {
            "12": ["echo 'Mainnet Command 1'", "echo 'Mainnet Command 2'"],
            "t147": ["echo 'Testnet Command 1'", "echo 'Testnet Command 2'"],
        }
    }

    if subnet_identifier in subnets:
        commands = subnets[subnet_identifier]
    else:
        commands = {}
        for subnet_data in subnets.values():
            if subnet_identifier in subnet_data:
                commands[subnet_identifier] = subnet_data[subnet_identifier]
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
    send_to_autovalidator(zip_filename, autovalidator_address, api_key)


def send_to_autovalidator(zip_filename, autovalidator_address, api_key):
    url = f"{autovalidator_address}/api/v1/files/"
    headers = {"Authorization": f"Token {api_key}"}
    files = {"file": open(zip_filename, "rb")}

    response = requests.post(url, headers=headers, files=files)
    if response.status_code == 201:
        print("File successfully uploaded and resource created.")
    elif response.status_code == 200:
        print("Request succeeded.")
    else:
        print(f"Failed to upload file. Status code: {response.status_code}")
        print(response.text)


if __name__ == "__main__":
    main()
