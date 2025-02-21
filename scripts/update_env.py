import os
from argparse import ArgumentParser


def update_env_variable(file_path, key, value):
    # Read the existing .env file
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            lines = file.readlines()
    else:
        lines = []

    # Check if the key already exists and update it
    key_exists = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            key_exists = True
            break

    # If the key does not exist, add it
    if not key_exists:
        lines.append(f"{key}={value}\n")

    # Write the updated lines back to the .env file
    with open(file_path, "w") as file:
        file.writelines(lines)

    print(f"Updated {key} in {file_path}")


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--file", type=str, default=".env")
    parser.add_argument("--key", type=str)
    parser.add_argument("--value", type=str)
    args = parser.parse_args()
    update_env_variable(args.file, args.key, args.value)
