# client.py

import sys
import argparse
import logging
import pyperclip
import win32file
import win32pipe
import pywintypes
import time
import os
import json
import configparser
from pathlib import Path
from cryptography.fernet import Fernet

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Set to DEBUG for more detailed logs
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("client.log"), logging.StreamHandler(sys.stdout)],
)


def get_google_creds_path():
    """
    Determines the path for google_creds.json based on whether the application is frozen.

    Returns:
        Path: The path to google_creds.json.
    """
    if getattr(sys, "frozen", False):
        # Running as a bundled executable
        app_data = Path.home() / "AppData" / "Roaming" / "Ace Centre" / "AACSpeakHelper"
    else:
        # Running as a script (development)
        # Assume that config.enc is at the repository root, and so is google_creds.json
        app_data = Path.cwd()

    return app_data / "google_creds.json"


def find_config_enc(start_path: Path, max_depth: int = 5) -> Path:
    """
    Searches for 'config.enc' starting from 'start_path' and traversing up to 'max_depth' levels.

    Args:
        start_path (Path): The directory to start searching from.
        max_depth (int): The maximum number of parent directories to traverse.

    Returns:
        Path: The path to 'config.enc' if found.

    Raises:
        FileNotFoundError: If 'config.enc' is not found within the specified depth.
    """
    current_path = start_path
    for depth in range(max_depth):
        config_path = current_path / "config.enc"
        internal_config_path = current_path / "_internal" / "config.enc"
        logging.debug(f"Checking for config.enc at: {config_path}")
        if config_path.is_file():
            logging.debug(f"Found config.enc at: {config_path}")
            return config_path
        if internal_config_path.is_file():
            logging.debug(f"Found _internal/config.enc at: {internal_config_path}")
            return internal_config_path
        current_path = current_path.parent  # Move one level up
        logging.debug(f"Moving up to parent directory: {current_path}")

    raise FileNotFoundError(
        f"'config.enc' not found within {max_depth} levels up from {start_path}"
    )


def load_config():
    """
    Load configuration from an encrypted file and optionally override with settings from settings.cfg.

    Returns:
        dict: A dictionary containing configuration keys and their corresponding values.

    Raises:
        EnvironmentError: If required environment variables are not set.
        FileNotFoundError: If config.enc or google_creds.json are not found.
        ValueError: If the configuration is incomplete or corrupted.
    """
    config = {}

    # Determine the starting directory based on whether the app is frozen
    if getattr(sys, "frozen", False):
        # Running as a bundled executable
        executable_dir = Path(sys.executable).parent
        start_dir = executable_dir
        logging.debug(f"Executable directory: {executable_dir}")
    else:
        # Running as a script (development)
        start_dir = (
            Path.cwd()
        )  # Assuming the current working directory is the repo root
        logging.debug(
            f"Script is running in development mode. Current working directory: {start_dir}"
        )

    # Attempt to find config.enc
    try:
        encrypted_config_path = find_config_enc(start_dir)
        logging.info(f"Found encrypted configuration file at: {encrypted_config_path}")
    except FileNotFoundError as e:
        logging.warning(e)
        encrypted_config_path = None

    if encrypted_config_path:
        # Load the encryption key from the environment variable
        encryption_key = os.getenv("CONFIG_ENCRYPTION_KEY")
        if not encryption_key:
            logging.error("CONFIG_ENCRYPTION_KEY environment variable is not set.")
            raise EnvironmentError(
                "CONFIG_ENCRYPTION_KEY environment variable is not set."
            )

        try:
            # Initialize Fernet with the encryption key
            fernet = Fernet(encryption_key.encode())

            # Read and decrypt the configuration
            with encrypted_config_path.open("rb") as f:
                encrypted_data = f.read()
            decrypted_data = fernet.decrypt(encrypted_data)
            decrypted_config = json.loads(decrypted_data.decode())
            print(decrypted_config)

            logging.info("Successfully decrypted configuration from config.enc.")

            # Write google_creds.json to the determined path
            google_creds_json = decrypted_config.get("GOOGLE_CREDS_JSON")
            google_creds_path = get_google_creds_path()

            if google_creds_json:
                os.makedirs(google_creds_path.parent, exist_ok=True)
                with google_creds_path.open("w") as f:
                    json.dump(json.loads(google_creds_json), f)
                logging.info(f"Google credentials file created at {google_creds_path}")
                config["GOOGLE_CREDS_PATH"] = str(google_creds_path)
            else:
                logging.error("GOOGLE_CREDS_JSON not found in decrypted configuration.")
                raise ValueError(
                    "GOOGLE_CREDS_JSON not found in decrypted configuration."
                )

            # Populate the remaining configuration keys
            config["MICROSOFT_TOKEN"] = decrypted_config.get("MICROSOFT_TOKEN")
            config["MICROSOFT_REGION"] = decrypted_config.get("MICROSOFT_REGION")
            config["MICROSOFT_TOKEN_TRANS"] = decrypted_config.get(
                "MICROSOFT_TOKEN_TRANS"
            )

            # Validate that all required fields are present
            required_fields = [
                "MICROSOFT_TOKEN",
                "MICROSOFT_REGION",
                "MICROSOFT_TOKEN_TRANS",
                "GOOGLE_CREDS_PATH",
            ]
            missing_fields = [
                field for field in required_fields if not config.get(field)
            ]
            if missing_fields:
                logging.error(
                    f"Missing configuration fields: {', '.join(missing_fields)}"
                )
                raise ValueError(
                    f"Missing configuration fields: {', '.join(missing_fields)}"
                )

            logging.info("Configuration loaded successfully from encrypted file.")

        except Exception as e:
            logging.error(f"Failed to load configuration from encrypted file: {e}")
            logging.info("Falling back to loading configuration from settings.cfg.")
            encrypted_config_path = None  # Reset to allow loading from settings.cfg

    # Load configuration from settings.cfg if it exists
    settings_cfg_path = start_dir / "settings.cfg"
    if settings_cfg_path.is_file():
        logging.info(f"Loading configuration overrides from {settings_cfg_path}")
        config_parser = configparser.ConfigParser()
        config_parser.read(settings_cfg_path)

        if "overrides" in config_parser.sections():
            for key, value in config_parser["overrides"].items():
                config[key.upper()] = value
                logging.info(f"Overridden {key.upper()} with value from settings.cfg")
        else:
            logging.warning(f"No [overrides] section found in {settings_cfg_path}")
    else:
        logging.info("No settings.cfg file found. Skipping overrides.")

    # Final validation to ensure all required fields are present
    required_fields = [
        "MICROSOFT_TOKEN",
        "MICROSOFT_REGION",
        "MICROSOFT_TOKEN_TRANS",
        "GOOGLE_CREDS_PATH",
    ]
    missing_fields = [field for field in required_fields if not config.get(field)]
    if missing_fields:
        logging.error(
            f"Missing configuration fields after loading: {', '.join(missing_fields)}"
        )
        raise ValueError(f"Missing configuration fields: {', '.join(missing_fields)}")

    # Verify that google_creds.json exists
    google_creds_path = Path(config["GOOGLE_CREDS_PATH"])
    if not google_creds_path.is_file():
        logging.error(f"Google credentials file not found at {google_creds_path}.")
        raise FileNotFoundError(
            f"Google credentials file not found at {google_creds_path}."
        )

    logging.info("Final configuration loaded successfully.")
    return config


def get_config_path():
    """
    Determines the path to settings.cfg based on whether the application is frozen.

    Returns:
        str: The path to settings.cfg.
    """
    if getattr(sys, "frozen", False):
        # Running as a bundled executable
        home_directory = Path.home()
        return str(
            home_directory
            / "AppData"
            / "Roaming"
            / "Ace Centre"
            / "AACSpeakHelper"
            / "settings.cfg"
        )
    else:
        # Running as a script (development)
        return str(Path(__file__).resolve().parent / "settings.cfg")


def load_standard_config(configuration_path):
    """
    Loads additional settings from settings.cfg to override configurations from config.enc.

    Args:
        configuration_path (str): The path to settings.cfg.

    Returns:
        dict: A dictionary containing overridden configuration keys and values.
    """
    configuration = configparser.ConfigParser()
    configuration.read(configuration_path)
    overrides = {}

    if "overrides" in configuration.sections():
        for key, value in configuration["overrides"].items():
            overrides[key.upper()] = value
            logging.info(f"Overridden {key.upper()} with value from settings.cfg")
    else:
        logging.warning(f"No [overrides] section found in {configuration_path}")

    return overrides


def get_clipboard_text():
    """
    Retrieves the current text from the clipboard.

    Returns:
        str: The clipboard text.
    """
    try:
        return pyperclip.paste()
    except pyperclip.PyperclipException as e:
        logging.error(f"Failed to get clipboard text: {e}")
        return ""


def send_to_pipe(data, retries=3, delay=1):
    """
    Sends data to a named pipe.

    Args:
        data (dict): The data to send.
        retries (int): Number of retries if the pipe is unavailable.
        delay (int): Delay in seconds between retries.

    Returns:
        None
    """
    pipe_name = r"\\.\pipe\AACSpeakHelper"
    attempt = 0
    while attempt < retries:
        try:
            handle = win32file.CreateFile(
                pipe_name,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None,
            )
            message = json.dumps(data).encode()
            win32file.WriteFile(handle, message)
            logging.info(f"Sent data to pipe: {data}")

            try:
                result, response = win32file.ReadFile(handle, 128 * 1024)
                if result == 0:
                    available_voices = response.decode()
                    logging.info(f"Available Voices: {available_voices}")
            except Exception as read_error:
                if "109" not in str(read_error):
                    logging.error(f"Error reading from pipe: {read_error}")

            win32file.CloseHandle(handle)
            break
        except pywintypes.error as e:
            logging.error(
                f"Attempt {attempt + 1}: Error communicating with the pipe server: {e}"
            )
            time.sleep(delay)
            attempt += 1
    else:
        logging.error(
            "Failed to communicate with the pipe server after multiple attempts."
        )


def main():
    """
    Main function to execute the client logic.
    """
    default_config_path = get_config_path()

    parser = argparse.ArgumentParser(description="AACSpeakHelper Client")
    parser.add_argument(
        "-c",
        "--config",
        help="Path to a defined config file",
        required=False,
        default=default_config_path,
    )
    parser.add_argument(
        "-l",
        "--listvoices",
        help="List Voices to see what's available",
        action="store_true",
    )
    parser.add_argument("-p", "--preview", help="Preview Only", action="store_true")
    parser.add_argument("-s", "--style", help="Voice style for Azure TTS", default="")
    parser.add_argument(
        "-sd",
        "--styledegree",
        type=float,
        help="Degree of style for Azure TTS",
        default=None,
    )
    args = vars(parser.parse_args())

    config_path = args["config"]

    try:
        # Load primary configuration from config.enc
        config = load_config()
        logging.info("Primary configuration loaded successfully.")
    except Exception as error:
        logging.error(f"Error loading primary configuration: {error}")
        sys.exit(1)

    # Load overrides from settings.cfg if specified
    if config_path and Path(config_path).is_file():
        try:
            overrides = load_standard_config(config_path)
            config.update(overrides)
            logging.info("Configuration overrides applied successfully.")
        except Exception as error:
            logging.error(f"Error applying configuration overrides: {error}")
            sys.exit(1)
    else:
        if config_path != default_config_path:
            logging.warning(
                f"Specified config file {config_path} does not exist. Skipping overrides."
            )

    # Verify that all required configuration fields are present
    required_fields = [
        "MICROSOFT_TOKEN",
        "MICROSOFT_REGION",
        "MICROSOFT_TOKEN_TRANS",
        "GOOGLE_CREDS_PATH",
    ]
    missing_fields = [field for field in required_fields if not config.get(field)]
    if missing_fields:
        logging.error(f"Missing configuration fields: {', '.join(missing_fields)}")
        sys.exit(1)

    # Verify that google_creds.json exists
    google_creds_path = Path(config["GOOGLE_CREDS_PATH"])
    if not google_creds_path.is_file():
        logging.error(f"Google credentials file not found at {google_creds_path}.")
        sys.exit(1)

    logging.info("All configurations are validated successfully.")

    # Retrieve clipboard text
    clipboard_text = get_clipboard_text()
    logging.debug(f"Clipboard text: {clipboard_text}")

    # Prepare data to send
    data_to_send = {
        "args": args,
        "config": config,
        "clipboard_text": clipboard_text,
    }

    # Send data to the named pipe
    send_to_pipe(data_to_send)


if __name__ == "__main__":
    main()
