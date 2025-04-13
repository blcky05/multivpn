import subprocess
import os
import random
import argparse

def check_prerequisites():
    """Checks if Docker and Docker Compose are installed."""
    try:
        subprocess.run(['docker', '--version'], check=True, capture_output=True)
        subprocess.run(['docker-compose', '--version'], check=True, capture_output=True)
        print("Docker and Docker Compose are installed.")
        return True
    except FileNotFoundError as e:
        print(f"Error: {e.filename} not found. Please ensure Docker and Docker Compose are installed.")
        print("You can find installation instructions here:")
        print("- Docker: https://docs.docker.com/engine/install/")
        print("- Docker Compose: https://docs.docker.com/compose/install/")
        return False
    except subprocess.CalledProcessError:
        print("Error: Docker or Docker Compose command failed. Please check your installation.")
        return False
    
def choose_random_file(directory, prefix=None):
    """
    Randomly chooses a file from the specified directory that matches the prefix.

    Args:
        directory (str): The path to the directory containing the files.
        prefix (str, optional): The prefix to filter files by. Defaults to None.

    Returns:
        str or None: The name of the randomly chosen file, or None if no matching files are found.
    """
    try:
        all_files = os.listdir(directory)
        matching_files = []
        for filename in all_files:
            if prefix is None or filename.startswith(prefix):
                matching_files.append(filename)

        if not matching_files:
            print(f"No files found in '{directory}' matching the prefix '{prefix}'." if prefix else f"No files found in '{directory}'.")
            return None
        else:
            chosen_file = random.choice(matching_files)
            return chosen_file
    except FileNotFoundError:
        print(f"Error: Directory '{directory}' not found.")
        return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

def generate_gluetun_service(vpn_number, server_location="any", env_file=".env-nordvpn"):
    """Generates a service definition for a single NordVPN connection using Gluetun."""
    http_proxy_port = 8888 + vpn_number
    socks5_proxy_port = 1080 + vpn_number

    service_content = f"""
  gluetun_{vpn_number}:
    image: qmcgaw/gluetun
    container_name: gluetun_nordvpn_{vpn_number}
    cap_add:
      - NET_ADMIN
    devices:
      - /dev/net/tun
    env_file:
      - {env_file}
    environment:
      - VPN_SERVICE=nordvpn
      - VPN_TYPE=openvpn
      - SERVER_COUNTRIES={server_location}
      - TZ=Europe/Berlin # Adjust as needed
      - HTTPPROXY=on
      - HTTPPROXY_PORT={http_proxy_port}
      - SOCKS5=on
      - SOCKS5_PORT={socks5_proxy_port}
    ports:
      - "{http_proxy_port}:{http_proxy_port}" # HTTP Proxy
      - "{socks5_proxy_port}:{socks5_proxy_port}" # SOCKS5 Proxy
    restart: unless-stopped
"""
    return service_content

def generate_openvpn_proxy_service(vpn_number, server_location="any", openvpn_config_dir="/etc/openvpn/ovpn_tcp", env_file=".env-nordvpn"):
    """Generates a service definition for a single NordVPN connection using openvpn-proxy."""
    if not os.path.exists(openvpn_config_dir):
        raise FileNotFoundError(f"OpenVPN configuration directory '{openvpn_config_dir}' does not exist.")
    if not os.path.isdir(openvpn_config_dir):
        raise NotADirectoryError(f"'{openvpn_config_dir}' is not a directory.")

    openvpn_config_file = choose_random_file(openvpn_config_dir, prefix=server_location if server_location != "any" else None)
    if not openvpn_config_file:
        raise FileNotFoundError(f"No OpenVPN configuration file found for location '{server_location}'.")

    local_ip = subprocess.check_output(['hostname', '-I']).decode('utf-8').strip().split()[0]
    http_proxy_port = 8888 + vpn_number

    service_content = f"""
  openvpn_proxy_{vpn_number}:
    image: jonoh/openvpn-proxy
    container_name: openvpn_proxy_nordvpn_{vpn_number}
    cap_add:
      - NET_ADMIN
    devices:
      - /dev/net/tun
    volumes:
      - {openvpn_config_dir}:/config/openvpn
    env_file:
      - {env_file}
    environment:
      - OPENVPN_CONFIG_FILE=/config/openvpn/{openvpn_config_file}
      - LOCAL_NETWORK={local_ip}/24 # Adjust as needed
      - OPENVPN_PROXY_PORT={http_proxy_port}
    ports:
      - "{http_proxy_port}:{http_proxy_port}" # HTTP Proxy
    restart: unless-stopped
"""
    return service_content

def generate_combined_docker_compose(num_connections, method_choice, server_locations,
                                     env_file,
                                     openvpn_config_dir="/etc/openvpn/ovpn_tcp"):
    """Generates a single docker-compose.yml file with multiple services."""
    compose_file = "docker-compose.yml"

    services = []
    for i in range(1, num_connections + 1):
        if method_choice == "1":
            service_content = generate_gluetun_service(i, server_locations[i - 1], env_file=env_file)
        elif method_choice == "2":
            service_content = generate_openvpn_proxy_service(i, server_locations[i - 1], 
                                                                       openvpn_config_dir=openvpn_config_dir, env_file=env_file)
        else:
            raise ValueError("Invalid method choice.")
        services.append(service_content)
        
    compose_content = f"services:\n" + "\n".join(services)
    with open(compose_file, "w") as f:
        f.write(compose_content)

    print(f"Generated combined docker-compose file: {compose_file}")
    return compose_file, env_file

def create_or_use_env_file(env_file, nordvpn_username, nordvpn_password):
    """
    Creates an .env file to store NordVPN credentials if it doesn't already exist.
    If the file exists, it uses the existing file without overwriting it.
    """
    if os.path.exists(env_file):
        print(f"Environment file '{env_file}' exists. Ignoring provided credentials.")
        return

    if len(nordvpn_username) == 0 or len(nordvpn_password) == 0:
        raise ValueError("Username and password must be provided to create a new .env file.")

    env_content = f"""
NORDVPN_USERNAME={nordvpn_username}
NORDVPN_PASSWORD={nordvpn_password}
OPENVPN_USERNAME={nordvpn_username}
OPENVPN_PASSWORD={nordvpn_password}
"""
    with open(env_file, "w") as f:
        f.write(env_content)
    print(f"Generated environment file: {env_file}")

def start_vpn_connection(config_file):
    """Starts a single VPN connection using Docker Compose."""
    try:
        subprocess.run(['docker-compose', '-f', config_file, 'up', '-d'], check=True)
        print(f"Started VPN connection using {config_file}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error starting VPN connection with {config_file}: {e}")
        return False

def stop_vpn_connections(config_file):
    """Stops all VPN connections."""
    try:
        subprocess.run(['docker-compose', '-f', config_file, 'down'], check=True)
        print(f"Stopped VPN connections using {config_file}")
    except FileNotFoundError:
        print(f"Configuration file not found: {config_file}")
    except subprocess.CalledProcessError as e:
        print(f"Error stopping VPN connections with {config_file}: {e}")

def display_proxy_info(num_connections):
    """Displays the proxy information for each VPN connection."""
    print("\n--- Proxy Information ---")
    print("You can use the following addresses as proxies on your host machine:")
    print("Note: Ensure the VPN-Proxy containers are running.")
    for i in range(1, num_connections + 1):
        http_port = 8888 + i
        socks5_port = 1080 + i
        print(f"VPN Connection {i}:")
        print(f"  HTTP Proxy: http://localhost:{http_port}")
        print(f"  SOCKS5 Proxy: socks5://localhost:{socks5_port}")
    print("-------------------------")

def open_browser_with_proxy(proxy_type, proxy_address, profile_name, url="about:blank"):
    """Opens a Chromium browser window with the specified proxy configuration."""
    try:
        command = [
            "chromium-browser",  # Or "google-chrome" depending on your system
            f"--proxy-server={proxy_address}", # Changed to not include the protocol in the flag value
            f"--user-data-dir=./chrome_profile_{profile_name}",
            "--new-window",
            url
        ]
        subprocess.Popen(command)
        print(f"Opened browser window with {proxy_type} proxy: {proxy_address} (Profile: {profile_name})")
    except FileNotFoundError:
        print("Error: chromium-browser not found. Please ensure it's installed and in your PATH.")
    except Exception as e:
        print(f"Error opening browser: {e}")

if __name__ == "__main__":
    if not check_prerequisites():
        exit(1)

    # Set up argument parser
    parser = argparse.ArgumentParser(description="MultiVPN script to manage multiple VPN connections.")
    parser.add_argument("--num-connections", type=int, choices=range(1,11), help="Number of VPN connections to establish.")
    parser.add_argument("--method", choices=["1", "2"], help="VPN connection method: 1 for Gluetun, 2 for OpenVPN Proxy.")
    parser.add_argument("--env-file", default=".env-nordvpn", help="Path to the environment file (default: .env-nordvpn).")
    parser.add_argument("--server-locations", nargs="*", help="List of server locations (e.g., 'us', 'de', 'fr').")
    parser.add_argument("--username", help="NordVPN username (used if env file does not exist).")
    parser.add_argument("--password", help="NordVPN password (used if env file does not exist).")
    parser.add_argument("--url", help="URL to open in the browser with the configured proxy.")
    args = parser.parse_args()

      # Fallback to input prompts if arguments are not provided
    num_connections = args.num_connections or int(input("Enter the number of VPN connections you want to establish: "))
    env_file = args.env_file

    if not os.path.exists(env_file):
        nordvpn_username = args.username or input("Enter your NordVPN (OpenVPN) username: ")
        nordvpn_password = args.password or input("Enter your NordVPN (OpenVPN) password: ")
        create_or_use_env_file(env_file, nordvpn_username, nordvpn_password)
    else:
        print(f"Using existing environment file: {env_file}")
        create_or_use_env_file(env_file, "", "")  # Just to ensure the file is created if it doesn't exist

    method_choice = args.method or input("Which VPN connection method do you want to use?\n1. Gluetun\n2. OpenVPN Proxy\nEnter your choice (1 or 2): ")

    server_locations = args.server_locations
    if not server_locations:
        server_locations = []
        print("You can specify server locations (e.g., 'us', 'de', 'fr').")
        print("Leave blank to connect to any available server.")
        for i in range(1, num_connections + 1):
            location = input(f"Enter desired server location for connection {i}: ")
            server_locations.append(location if location else "any")


    try:
        config_file, env_file = generate_combined_docker_compose(
            num_connections, method_choice, server_locations, env_file=env_file
        )

        print(f"\nGenerated Docker Compose file: {config_file}")
        print(f"Generated environment file: {env_file}")

        print("\nStarting VPN connections...")
        if not start_vpn_connection(config_file):
            print("Failed to start VPN connections. Check the logs for errors.")
            exit(1)

        print("\nAll VPN connections started successfully!")
        display_proxy_info(num_connections)

        open_browsers = input("\nDo you want to automatically open browser windows with the configured proxies? (yes/no): ").lower()
        if open_browsers == "yes":
            print("\nOpening browser windows...")
            for i in range(1, num_connections + 1):
                http_port = 8888 + i
                socks5_port = 1080 + i
                open_browser_with_proxy("http", f"localhost:{http_port}", str(i), url=args.url or "about:blank")  # Using HTTP proxy

            print("\nBrowser windows opened. Each window is configured to use a different VPN connection.")

        input("\nPress Enter to stop all VPN connections...")

    finally:
        # Ensure VPN connections are stopped
        print("\nStopping all VPN connections...")
        stop_vpn_connections(config_file)
        print("All VPN connections stopped.")

        # Prompt for cleanup
        cleanup = input("Do you want to delete the generated configuration and environment files and Chrome profile directories? (yes/no): ").lower()
        if cleanup == "yes":
            try:
                os.remove(config_file)
                print(f"Deleted: {config_file}")
            except FileNotFoundError:
                pass

            try:
                os.remove(env_file)
                print(f"Deleted: {env_file}")
            except FileNotFoundError:
                pass

            for i in range(1, num_connections + 1):
                profile_dir = f"chrome_profile_{i}"
                try:
                    subprocess.run(['rm', '-rf', profile_dir], check=True)  # Use 'rmdir' if directories are empty
                    print(f"Deleted directory: {profile_dir}")
                except FileNotFoundError:
                    pass
                except subprocess.CalledProcessError as e:
                    print(f"Error deleting directory {profile_dir}: {e}")
            print("Cleanup complete.")