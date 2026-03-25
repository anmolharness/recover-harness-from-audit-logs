# Harness Resource Recovery Tool

CLI tool to recover and recreate deleted Harness resources from audit logs.

## Features

- Fetches audit logs for a specified date range
- Identifies deleted resources (pipelines, services, environments, connectors, templates)
- **Skips organization and project deletions** (as requested)
- Retrieves YAML definitions from audit history
- Recreates resources using Harness APIs
- Supports dry-run mode to preview actions
- Filter by resource type

## Installation

```bash
# Install dependencies
pip install -r requirements.txt
```

## Usage

### Basic Usage

```bash
python recover.py \
  --api-key YOUR_API_KEY \
  --account-id YOUR_ACCOUNT_ID \
  --start-date 2026-01-01 \
  --end-date 2026-03-25
```

### Dry Run (Preview Only)

```bash
python recover.py \
  --api-key YOUR_API_KEY \
  --account-id YOUR_ACCOUNT_ID \
  --start-date 2026-03-01 \
  --end-date 2026-03-25 \
  --dry-run
```

### Filter by Resource Type

```bash
python recover.py \
  --api-key YOUR_API_KEY \
  --account-id YOUR_ACCOUNT_ID \
  --start-date 2026-03-01 \
  --end-date 2026-03-25 \
  --resource-type PIPELINE
```

### Using Environment Variables

```bash
export HARNESS_API_KEY=$(cat ~/.harness_token)
export HARNESS_ACCOUNT_ID="your-account-id"

python recover.py \
  --api-key $HARNESS_API_KEY \
  --account-id $HARNESS_ACCOUNT_ID \
  --start-date 2026-03-01 \
  --end-date 2026-03-25
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--api-key` | Yes | Harness API key |
| `--account-id` | Yes | Harness account ID |
| `--start-date` | Yes | Start date in YYYY-MM-DD format |
| `--end-date` | Yes | End date in YYYY-MM-DD format |
| `--dry-run` | No | Preview actions without recreating resources |
| `--resource-type` | No | Filter by resource type (PIPELINE, SERVICE, ENVIRONMENT, etc.) |
| `--base-url` | No | Harness base URL (default: https://app.harness.io) |

## Supported Resource Types

The tool can recreate the following resource types:

- **Pipelines** - CD/CI pipelines
- **Services** - Service definitions
- **Environments** - Environment definitions
- **Connectors** - Cloud provider connectors, Git connectors, etc.
- **Templates** - Pipeline, step, and stage templates
- **Input Sets** - Pipeline input sets

**Note:** Organizations and Projects are intentionally skipped and will not be recreated.

## How It Works

1. **Fetch Audit Logs** - Retrieves all audit events in the specified date range
2. **Filter Deletions** - Identifies DELETE actions (excluding orgs/projects)
3. **Retrieve YAML** - Fetches the YAML definition from audit history
4. **Parse Resource Type** - Determines the type of resource from YAML structure
5. **Recreate** - Calls the appropriate Harness API endpoint to recreate the resource

## Example Output

```
============================================================
Harness Resource Recovery Tool
============================================================
Account ID: 9iW-060ARf-7xLCnVrVJbQ
Date Range: 2026-03-01 to 2026-03-25
Dry Run: False
============================================================

Fetching audit logs from 2026-03-01 to 2026-03-25...
Found deleted PIPELINE: testingtriggers
Found deleted SERVICE: my-service
Found deleted ENVIRONMENT: production

============================================================
Found 3 deleted resource(s)
============================================================

Processing PIPELINE: testingtriggers
✓ Pipeline recreated successfully

Processing SERVICE: my-service
✓ Service recreated successfully

Processing ENVIRONMENT: production
✓ Environment recreated successfully

============================================================
Recovery Summary
============================================================
Total: 3
Success: 3
Failed: 0
============================================================
```

## Error Handling

- If a resource already exists, the API will return an error
- Failed recreations are logged but don't stop processing
- Network errors and API errors are caught and reported
- Use `--dry-run` first to verify what will be recreated

## Security Notes

- API keys should be kept secure (use environment variables or secure storage)
- The tool requires permissions to read audit logs and create resources
- Recreated resources will use the same identifiers as the deleted ones
- **Secret values cannot be recovered** from audit logs (only metadata)
  - Secrets are recreated with placeholder value: `PLACEHOLDER_UPDATE_MANUALLY`
  - You must manually update secret values in the Harness UI after recovery

## Limitations

- **Secret values** are not stored in audit logs
  - Secrets are recreated with structure/metadata intact
  - Values are set to `PLACEHOLDER_UPDATE_MANUALLY` and must be updated manually in Harness UI
- **Encrypted data** cannot be recovered
- Resources must have been deleted within the audit log retention period
- Some resource types may not be supported yet (GitOps resources, user groups, roles, etc.)
