# ns-sandbox-cli

CLI tool to interact with Netsuite sandbox environments. Because clicking through the UI every time gets old.

## Why I Built This

I was tired of logging into Netsuite, navigating to Sandboxes, clicking around, waiting for pages to load, just to check if a sandbox exists or refresh it. This tool lets me do all that from my terminal while I'm already there debugging something.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Make it executable (optional)
chmod +x ns_sandbox_cli.py

# Set up your credentials once
./ns_sandbox_cli.py config \
  --account YOUR_ACCOUNT_ID \
  --token YOUR_TOKEN_ID \
  --token-secret YOUR_TOKEN_SECRET \
  --consumer-key YOUR_CONSUMER_KEY \
  --consumer-secret YOUR_CONSUMER_SECRET
```

## Usage

### List all sandboxes

```bash
./ns_sandbox_cli.py list
```

Shows a table with all your sandboxes, their status, type, and last refresh time.

### Create a new sandbox

```bash
./ns_sandbox_cli.py create --name "dev-sandbox-2024" --type Developer --include-data
```

Types available: Developer, Sales, Premium

### Delete a sandbox

```bash
./ns_sandbox_cli.py delete SB12345
./ns_sandbox_cli.py delete SB12345 --force
```

The `--force` flag skips the confirmation prompt. Use carefully.

### Refresh a sandbox

```bash
./ns_sandbox_cli.py refresh SB12345
./ns_sandbox_cli.py refresh SB12345 --include-data
```

Pulls fresh data from production. Takes a while depending on your account size.

### Get sandbox details

```bash
./ns_sandbox_cli.py details SB12345
```

Shows full details including credentials and endpoint info.

### Override credentials on the fly

Don't want to use saved config? Pass them directly:

```bash
./ns_sandbox_cli.py list \
  --account OTHER_ACCOUNT \
  --token OTHER_TOKEN \
  --token-secret OTHER_SECRET \
  --consumer-key OTHER_KEY \
  --consumer-secret OTHER_SECRET
```

## Config File Location

Config gets saved to `~/.ns-sandbox-cli/config.json`. Cache lives in the same directory.

## Getting API Credentials

You'll need OAuth 1.0a credentials from Netsuite:

1. Go to Setup > Integration > Manage Integrations
2. Create a new integration with TBA (Token Based Authentication)
3. Note down the Consumer Key and Consumer Secret
4. Create tokens for that integration
5. You'll get Token ID and Token Secret

Save all four values plus your account ID.

## Notes

- The OAuth signing is done manually in the code (no external oauth lib dependency)
- API calls timeout after 30 seconds
- Sandbox list gets cached locally for faster subsequent calls
- No analytics, no telemetry, no phone home - just a simple CLI

## Common Issues

**401 Unauthorized**: Check your credentials. Token might have expired.

**403 Forbidden**: Your integration might not have sandbox permissions.

**Timeout**: Netsuite API can be slow. Try again or check if you're rate limited.

## License

MIT. Do whatever you want with it.
