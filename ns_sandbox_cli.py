#!/usr/bin/env python3
"""
NS Sandbox CLI - Command line tool for managing Netsuite sandbox environments.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: requests library not installed. Run: pip install -r requirements.txt")
    sys.exit(1)


CONFIG_DIR = Path.home() / ".ns-sandbox-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"
SANDBOX_CACHE_FILE = CONFIG_DIR / "sandbox_cache.json"

DEFAULT_RATE_LIMIT = 10
DEFAULT_RATE_LIMIT_WINDOW = 60
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF = 2


class RateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(self, rate_limit=DEFAULT_RATE_LIMIT, window_seconds=DEFAULT_RATE_LIMIT_WINDOW):
        self.rate_limit = rate_limit
        self.window_seconds = window_seconds
        self.tokens = rate_limit
        self.last_update = time.time()

    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_update
        tokens_to_add = (elapsed / self.window_seconds) * self.rate_limit
        self.tokens = min(self.rate_limit, self.tokens + tokens_to_add)
        self.last_update = now

    def acquire(self):
        """Acquire a token, waiting if necessary."""
        while True:
            self._refill()
            if self.tokens >= 1:
                self.tokens -= 1
                return
            sleep_time = (1 - self.tokens) * (self.window_seconds / self.rate_limit)
            time.sleep(sleep_time)


rate_limiter = RateLimiter()


def ensure_config_dir():
    """Create config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    """Load configuration from file."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_config(config):
    """Save configuration to file."""
    ensure_config_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def load_cache():
    """Load sandbox cache from file."""
    if not SANDBOX_CACHE_FILE.exists():
        return {}
    try:
        with open(SANDBOX_CACHE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_cache(cache):
    """Save sandbox cache to file."""
    ensure_config_dir()
    with open(SANDBOX_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def get_api_base_url(account_id):
    """Get the API base URL for a given account."""
    return f"https://{account_id}.suitetalk.api.netsuite.com"


def make_api_request(method, endpoint, account_id, token_id, token_secret, consumer_key, consumer_secret, data=None, max_retries=DEFAULT_MAX_RETRIES):
    """Make an authenticated API request to Netsuite with rate limiting and retry logic."""
    import base64
    import hashlib
    import hmac

    global rate_limiter

    base_url = get_api_base_url(account_id)
    url = f"{base_url}{endpoint}"

    for attempt in range(max_retries + 1):
        rate_limiter.acquire()

        timestamp = str(int(time.time()))
        nonce = str(os.urandom(8).hex())

        auth_header_parts = [
            f'oauth_consumer_key="{consumer_key}"',
            f'oauth_token="{token_id}"',
            f'oauth_signature_method="HMAC-SHA256"',
            f'oauth_timestamp="{timestamp}"',
            f'oauth_nonce="{nonce}"',
            f'oauth_version="1.0"',
        ]

        base_string = f"{method.upper()}&{requests.utils.quote(url, safe='')}&"

        signature_base = "&".join(auth_header_parts)
        signature_base = requests.utils.quote(signature_base, safe='')

        key = f"{consumer_secret}&{token_secret}"
        signature = hmac.new(
            key.encode(),
            base_string.encode(),
            hashlib.sha256
        ).digest()
        signature_b64 = base64.b64encode(signature).decode()

        auth_header_parts.append(f'oauth_signature="{requests.utils.quote(signature_b64, safe="")}"')
        auth_header = "OAuth " + ", ".join(auth_header_parts)

        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        try:
            if method.lower() == "get":
                response = requests.get(url, headers=headers, timeout=30)
            elif method.lower() == "post":
                response = requests.post(url, headers=headers, json=data, timeout=30)
            elif method.lower() == "put":
                response = requests.put(url, headers=headers, json=data, timeout=30)
            elif method.lower() == "delete":
                response = requests.delete(url, headers=headers, timeout=30)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    wait_time = int(retry_after)
                else:
                    wait_time = DEFAULT_RETRY_BACKOFF ** attempt
                if attempt < max_retries:
                    print(f"Rate limited. Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"Error: Rate limit exceeded after {max_retries} retries.")
                    return response

            return response

        except requests.RequestException as e:
            if attempt < max_retries:
                wait_time = DEFAULT_RETRY_BACKOFF ** attempt
                print(f"Request failed: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"API request failed after {max_retries} retries: {e}")
                return None

    return None


def list_sandboxes(args):
    """List all sandbox environments."""
    config = load_config()

    account_id = args.account or config.get("account_id")
    if not account_id:
        print("Error: Account ID required. Use --account or run 'ns-sandbox-cli config' first.")
        sys.exit(1)

    token_id = args.token or config.get("token_id")
    token_secret = args.token_secret or config.get("token_secret")
    consumer_key = args.consumer_key or config.get("consumer_key")
    consumer_secret = args.consumer_secret or config.get("consumer_secret")

    if not all([token_id, token_secret, consumer_key, consumer_secret]):
        print("Error: Missing authentication credentials.")
        print("Required: token_id, token_secret, consumer_key, consumer_secret")
        sys.exit(1)

    response = make_api_request(
        "GET",
        "/services/rest/connect/v1/sandboxes",
        account_id,
        token_id,
        token_secret,
        consumer_key,
        consumer_secret
    )

    if response is None:
        sys.exit(1)

    if response.status_code == 200:
        sandboxes = response.json().get("sandboxes", [])

        if not sandboxes:
            print("No sandbox environments found.")
            return

        print(f"\n{'ID':<12} {'Name':<25} {'Status':<15} {'Type':<12} {'Last Refresh':<20}")
        print("-" * 84)

        for sb in sandboxes:
            sb_id = sb.get("id", "N/A")
            name = sb.get("name", "N/A")[:24]
            status = sb.get("status", "unknown")
            sb_type = sb.get("type", "N/A")
            last_refresh = sb.get("last_refreshed", "Never")

            if last_refresh and last_refresh != "Never":
                try:
                    dt = datetime.fromisoformat(last_refresh.replace("Z", "+00:00"))
                    last_refresh = dt.strftime("%Y-%m-%d %H:%M")
                except (ValueError, AttributeError):
                    pass

            print(f"{sb_id:<12} {name:<25} {status:<15} {sb_type:<12} {last_refresh:<20}")

        print(f"\nTotal: {len(sandboxes)} sandbox(es)")

        cache = load_cache()
        cache["last_list"] = datetime.now().isoformat()
        cache["sandboxes"] = sandboxes
        save_cache(cache)
    else:
        print(f"Error: API request failed with status {response.status_code}")
        try:
            error_data = response.json()
            print(f"Details: {error_data}")
        except:
            print(f"Response: {response.text[:200]}")
        sys.exit(1)


def create_sandbox(args):
    """Create a new sandbox environment."""
    config = load_config()

    account_id = args.account or config.get("account_id")
    if not account_id:
        print("Error: Account ID required.")
        sys.exit(1)

    token_id = args.token or config.get("token_id")
    token_secret = args.token_secret or config.get("token_secret")
    consumer_key = args.consumer_key or config.get("consumer_key")
    consumer_secret = args.consumer_secret or config.get("consumer_secret")

    if not all([token_id, token_secret, consumer_key, consumer_secret]):
        print("Error: Missing authentication credentials.")
        sys.exit(1)

    payload = {
        "name": args.name,
        "type": args.sandbox_type or "Developer",
        "include_data": args.include_data if hasattr(args, 'include_data') else True
    }

    if args.description:
        payload["description"] = args.description

    response = make_api_request(
        "POST",
        "/services/rest/connect/v1/sandboxes",
        account_id,
        token_id,
        token_secret,
        consumer_key,
        consumer_secret,
        data=payload
    )

    if response is None:
        sys.exit(1)

    if response.status_code in [200, 201]:
        result = response.json()
        print("Sandbox created successfully!")
        print(f"ID: {result.get('id', 'N/A')}")
        print(f"Name: {result.get('name', 'N/A')}")
        print(f"Status: {result.get('status', 'N/A')}")
        print(f"Type: {result.get('type', 'N/A')}")
    else:
        print(f"Error: Failed to create sandbox (status {response.status_code})")
        try:
            error_data = response.json()
            print(f"Details: {error_data}")
        except:
            print(f"Response: {response.text[:200]}")
        sys.exit(1)


def delete_sandbox(args):
    """Delete a sandbox environment."""
    config = load_config()

    account_id = args.account or config.get("account_id")
    if not account_id:
        print("Error: Account ID required.")
        sys.exit(1)

    token_id = args.token or config.get("token_id")
    token_secret = args.token_secret or config.get("token_secret")
    consumer_key = args.consumer_key or config.get("consumer_key")
    consumer_secret = args.consumer_secret or config.get("consumer_secret")

    if not all([token_id, token_secret, consumer_key, consumer_secret]):
        print("Error: Missing authentication credentials.")
        sys.exit(1)

    if not args.force:
        confirm = input(f"Are you sure you want to delete sandbox '{args.sandbox_id}'? [y/N]: ")
        if confirm.lower() != 'y':
            print("Deletion cancelled.")
            sys.exit(0)

    response = make_api_request(
        "DELETE",
        f"/services/rest/connect/v1/sandboxes/{args.sandbox_id}",
        account_id,
        token_id,
        token_secret,
        consumer_key,
        consumer_secret
    )

    if response is None:
        sys.exit(1)

    if response.status_code == 204:
        print(f"Sandbox '{args.sandbox_id}' deleted successfully.")
    elif response.status_code == 200:
        print(f"Sandbox '{args.sandbox_id}' deletion initiated.")
    else:
        print(f"Error: Failed to delete sandbox (status {response.status_code})")
        try:
            error_data = response.json()
            print(f"Details: {error_data}")
        except:
            print(f"Response: {response.text[:200]}")
        sys.exit(1)


def refresh_sandbox(args):
    """Refresh a sandbox environment from production."""
    config = load_config()

    account_id = args.account or config.get("account_id")
    if not account_id:
        print("Error: Account ID required.")
        sys.exit(1)

    token_id = args.token or config.get("token_id")
    token_secret = args.token_secret or config.get("token_secret")
    consumer_key = args.consumer_key or config.get("consumer_key")
    consumer_secret = args.consumer_secret or config.get("consumer_secret")

    if not all([token_id, token_secret, consumer_key, consumer_secret]):
        print("Error: Missing authentication credentials.")
        sys.exit(1)

    payload = {}
    if args.include_data is not None:
        payload["include_data"] = args.include_data

    response = make_api_request(
        "POST",
        f"/services/rest/connect/v1/sandboxes/{args.sandbox_id}/refresh",
        account_id,
        token_id,
        token_secret,
        consumer_key,
        consumer_secret,
        data=payload
    )

    if response is None:
        sys.exit(1)

    if response.status_code in [200, 202]:
        result = response.json()
        print("Sandbox refresh initiated successfully!")
        print(f"Sandbox ID: {args.sandbox_id}")
        print(f"Status: {result.get('status', 'pending')}")
        print(f"Estimated completion: {result.get('estimated_completion', 'unknown')}")
    else:
        print(f"Error: Failed to refresh sandbox (status {response.status_code})")
        try:
            error_data = response.json()
            print(f"Details: {error_data}")
        except:
            print(f"Response: {response.text[:200]}")
        sys.exit(1)


def get_sandbox_details(args):
    """Get detailed information about a specific sandbox."""
    config = load_config()

    account_id = args.account or config.get("account_id")
    if not account_id:
        print("Error: Account ID required.")
        sys.exit(1)

    token_id = args.token or config.get("token_id")
    token_secret = args.token_secret or config.get("token_secret")
    consumer_key = args.consumer_key or config.get("consumer_key")
    consumer_secret = args.consumer_secret or config.get("consumer_secret")

    if not all([token_id, token_secret, consumer_key, consumer_secret]):
        print("Error: Missing authentication credentials.")
        sys.exit(1)

    response = make_api_request(
        "GET",
        f"/services/rest/connect/v1/sandboxes/{args.sandbox_id}",
        account_id,
        token_id,
        token_secret,
        consumer_key,
        consumer_secret
    )

    if response is None:
        sys.exit(1)

    if response.status_code == 200:
        sandbox = response.json()
        print("\n=== Sandbox Details ===\n")
        print(f"ID:              {sandbox.get('id', 'N/A')}")
        print(f"Name:            {sandbox.get('name', 'N/A')}")
        print(f"Type:            {sandbox.get('type', 'N/A')}")
        print(f"Status:          {sandbox.get('status', 'N/A')}")
        print(f"Description:     {sandbox.get('description', 'N/A')}")
        print(f"Created:         {sandbox.get('created_at', 'N/A')}")
        print(f"Last Refresh:    {sandbox.get('last_refreshed', 'Never')}")
        print(f"Expiry Date:     {sandbox.get('expiry_date', 'N/A')}")
        print(f"Data Included:   {sandbox.get('include_data', 'N/A')}")

        if sandbox.get("credentials"):
            print("\n--- Credentials ---")
            creds = sandbox["credentials"]
            print(f"Account ID:      {creds.get('account_id', 'N/A')}")
            print(f"Endpoint:        {creds.get('endpoint', 'N/A')}")
    else:
        print(f"Error: Failed to get sandbox details (status {response.status_code})")
        try:
            error_data = response.json()
            print(f"Details: {error_data}")
        except:
            print(f"Response: {response.text[:200]}")
        sys.exit(1)


def configure(args):
    """Configure default credentials and settings."""
    ensure_config_dir()
    config = load_config()

    print("NS Sandbox CLI Configuration")
    print("-" * 30)

    if args.account:
        config["account_id"] = args.account
        print(f"Account ID: {args.account}")

    if args.token:
        config["token_id"] = args.token
        print("Token ID: [configured]")

    if args.token_secret:
        config["token_secret"] = args.token_secret
        print("Token Secret: [configured]")

    if args.consumer_key:
        config["consumer_key"] = args.consumer_key
        print("Consumer Key: [configured]")

    if args.consumer_secret:
        config["consumer_secret"] = args.consumer_secret
        print("Consumer Secret: [configured]")

    if args.rate_limit:
        config["rate_limit"] = args.rate_limit
        print(f"Rate Limit: {args.rate_limit} requests per {config.get('rate_limit_window', DEFAULT_RATE_LIMIT_WINDOW)}s")

    if args.rate_limit_window:
        config["rate_limit_window"] = args.rate_limit_window
        print(f"Rate Limit Window: {args.rate_limit_window}s")

    save_config(config)
    print("\nConfiguration saved successfully!")
    print(f"Config file: {CONFIG_FILE}")


def show_config(args):
    """Show current configuration."""
    config = load_config()

    if not config:
        print("No configuration found. Run 'ns-sandbox-cli config' to set up.")
        return

    print("Current Configuration:")
    print("-" * 30)

    for key, value in config.items():
        if "secret" in key.lower() or "token" in key.lower():
            display_value = "[REDACTED]" if value else "[NOT SET]"
        else:
            display_value = value or "[NOT SET]"
        print(f"{key}: {display_value}")

    print(f"\nConfig file: {CONFIG_FILE}")


def main():
    global rate_limiter

    parser = argparse.ArgumentParser(
        prog="ns-sandbox-cli",
        description="CLI tool for managing Netsuite sandbox environments"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    list_parser = subparsers.add_parser("list", help="List all sandbox environments")
    list_parser.add_argument("--account", help="Netsuite account ID")
    list_parser.add_argument("--token", help="OAuth token ID")
    list_parser.add_argument("--token-secret", help="OAuth token secret")
    list_parser.add_argument("--consumer-key", help="OAuth consumer key")
    list_parser.add_argument("--consumer-secret", help="OAuth consumer secret")
    list_parser.set_defaults(func=list_sandboxes)

    create_parser = subparsers.add_parser("create", help="Create a new sandbox")
    create_parser.add_argument("--name", required=True, help="Sandbox name")
    create_parser.add_argument("--type", dest="sandbox_type", choices=["Developer", "Sales", "Premium"], help="Sandbox type")
    create_parser.add_argument("--description", help="Sandbox description")
    create_parser.add_argument("--include-data", dest="include_data", action="store_true", help="Include production data")
    create_parser.add_argument("--account", help="Netsuite account ID")
    create_parser.add_argument("--token", help="OAuth token ID")
    create_parser.add_argument("--token-secret", help="OAuth token secret")
    create_parser.add_argument("--consumer-key", help="OAuth consumer key")
    create_parser.add_argument("--consumer-secret", help="OAuth consumer secret")
    create_parser.set_defaults(func=create_sandbox)

    delete_parser = subparsers.add_parser("delete", help="Delete a sandbox")
    delete_parser.add_argument("sandbox_id", help="Sandbox ID to delete")
    delete_parser.add_argument("--force", "-f", action="store_true", help="Skip confirmation")
    delete_parser.add_argument("--account", help="Netsuite account ID")
    delete_parser.add_argument("--token", help="OAuth token ID")
    delete_parser.add_argument("--token-secret", help="OAuth token secret")
    delete_parser.add_argument("--consumer-key", help="OAuth consumer key")
    delete_parser.add_argument("--consumer-secret", help="OAuth consumer secret")
    delete_parser.set_defaults(func=delete_sandbox)

    refresh_parser = subparsers.add_parser("refresh", help="Refresh a sandbox from production")
    refresh_parser.add_argument("sandbox_id", help="Sandbox ID to refresh")
    refresh_parser.add_argument("--include-data", dest="include_data", action="store_true", help="Include production data")
    refresh_parser.add_argument("--account", help="Netsuite account ID")
    refresh_parser.add_argument("--token", help="OAuth token ID")
    refresh_parser.add_argument("--token-secret", help="OAuth token secret")
    refresh_parser.add_argument("--consumer-key", help="OAuth consumer key")
    refresh_parser.add_argument("--consumer-secret", help="OAuth consumer secret")
    refresh_parser.set_defaults(func=refresh_sandbox)

    details_parser = subparsers.add_parser("details", help="Get sandbox details")
    details_parser.add_argument("sandbox_id", help="Sandbox ID")
    details_parser.add_argument("--account", help="Netsuite account ID")
    details_parser.add_argument("--token", help="OAuth token ID")
    details_parser.add_argument("--token-secret", help="OAuth token secret")
    details_parser.add_argument("--consumer-key", help="OAuth consumer key")
    details_parser.add_argument("--consumer-secret", help="OAuth consumer secret")
    details_parser.set_defaults(func=get_sandbox_details)

    config_parser = subparsers.add_parser("config", help="Configure credentials")
    config_parser.add_argument("--account", help="Netsuite account ID")
    config_parser.add_argument("--token", help="OAuth token ID")
    config_parser.add_argument("--token-secret", help="OAuth token secret")
    config_parser.add_argument("--consumer-key", help="OAuth consumer key")
    config_parser.add_argument("--consumer-secret", help="OAuth consumer secret")
    config_parser.add_argument("--rate-limit", type=int, help=f"Max requests per window (default: {DEFAULT_RATE_LIMIT})")
    config_parser.add_argument("--rate-limit-window", type=int, help=f"Rate limit window in seconds (default: {DEFAULT_RATE_LIMIT_WINDOW})")
    config_parser.set_defaults(func=configure)

    show_config_parser = subparsers.add_parser("show-config", help="Show current configuration")
    show_config_parser.set_defaults(func=show_config)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    config = load_config()
    rate_limit = config.get("rate_limit", DEFAULT_RATE_LIMIT)
    rate_limit_window = config.get("rate_limit_window", DEFAULT_RATE_LIMIT_WINDOW)
    rate_limiter = RateLimiter(rate_limit, rate_limit_window)

    args.func(args)


if __name__ == "__main__":
    main()
