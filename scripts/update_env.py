import os
from argparse import ArgumentParser


def update_env_variable(key, value):
    if not value:
        raise ValueError("Value is required")
    if not key:
        raise ValueError("Key is required")
    # Read the existing .env file
    if os.path.exists(".env"):
        with open(".env", "r") as file:
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
    with open(".env", "w") as file:
        file.writelines(lines)

    print(f"Updated {key} in .env")


def main():
    parser = ArgumentParser()
    parser.add_argument("key", type=str)
    parser.add_argument("value", type=str)
    args = parser.parse_args()
    if not args.key or not args.value:
        parser.error("Key and value are required")
    update_env_variable(args.key, args.value)


if __name__ == "__main__":
    main()
