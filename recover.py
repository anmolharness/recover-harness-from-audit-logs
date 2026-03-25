#!/usr/bin/env python3
"""
Harness Resource Recovery Tool
Recovers and recreates deleted resources from Harness audit logs
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import requests
import yaml


class HarnessRecovery:
    """Main class for recovering deleted Harness resources"""

    def __init__(self, api_key: str, account_id: str, base_url: str = "https://app.harness.io",
                 session_token: Optional[str] = None):
        self.api_key = api_key
        self.account_id = account_id
        self.base_url = base_url
        self.session_token = session_token

        # SAT token authentication (for audit listing)
        self.headers_api_key = {
            "x-api-key": api_key,
            "Content-Type": "application/json"
        }

        # Session token authentication (for audit YAML - requires browser JWT)
        if session_token:
            self.headers_session = {
                "Authorization": f"Bearer {session_token}",
                "Content-Type": "application/json"
            }
        else:
            self.headers_session = None

        self.headers = self.headers_api_key

    def get_audit_logs(self, start_time: int, end_time: int, page: int = 0, page_size: int = 100) -> Dict[str, Any]:
        """Fetch audit logs for the given time range, filtered for DELETE actions only"""
        url = f"{self.base_url}/gateway/audit/api/audits/list"

        params = {
            "accountIdentifier": self.account_id,
            "startTime": start_time,
            "endTime": end_time,
            "pageIndex": page,
            "pageSize": page_size
        }

        # Request body with filter for DELETE actions only
        body = {
            "filterType": "Audit",
            "actions": ["DELETE"]
        }

        print(f"Fetching deleted resources from {datetime.fromtimestamp(start_time/1000)} to {datetime.fromtimestamp(end_time/1000)}...")

        response = requests.post(url, headers=self.headers, params=params, json=body)
        response.raise_for_status()

        return response.json()

    def get_audit_yaml(self, audit_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the YAML content for a specific audit entry

        Note: This endpoint requires browser session authentication (JWT token).
        SAT tokens will not work. Extract JWT from browser dev tools.
        """
        if not self.headers_session:
            return None

        url = f"{self.base_url}/gateway/audit/api/auditYaml"

        params = {
            "accountIdentifier": self.account_id,
            "auditId": audit_id
        }

        response = requests.get(url, headers=self.headers_session, params=params)

        if response.status_code == 200:
            return response.json()

        if response.status_code == 401:
            print(f"  Authentication failed - session token required (not SAT token)")
        else:
            print(f"  Error fetching audit YAML: {response.status_code} - {response.text[:200]}")
        return None

    def find_deleted_resources(self, start_date: str, end_date: str,
                                skip_ephemeral: bool = True,
                                resource_types_filter: Optional[List[str]] = None,
                                exclude_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Find all deleted resources in the given date range"""
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)

        start_time = int(start_dt.timestamp() * 1000)
        end_time = int(end_dt.timestamp() * 1000)

        # Resource types to skip (ephemeral/transient resources)
        ephemeral_types = ["DELEGATE", "TOKEN"]

        deleted_resources = []
        page = 0

        print(f"Scanning audit logs (this may take a moment)...")

        while True:
            result = self.get_audit_logs(start_time, end_time, page)

            if result.get("status") != "SUCCESS":
                print(f"Error fetching audit logs: {result}")
                break

            data = result.get("data", {})
            content = data.get("content", [])

            if not content:
                break

            for audit in content:
                resource_type = audit.get("resource", {}).get("type", "")

                # Skip organization deletions only
                if resource_type.upper() in ["ORGANIZATION"]:
                    continue

                # Skip ephemeral resources if requested
                if skip_ephemeral and resource_type.upper() in ephemeral_types:
                    continue

                # Skip excluded resource types if provided
                if exclude_types and resource_type.upper() in [et.upper() for et in exclude_types]:
                    continue

                # Filter by specific resource types if provided
                if resource_types_filter and resource_type.upper() not in [rt.upper() for rt in resource_types_filter]:
                    continue

                # All results are already DELETE actions (filtered at API level)
                deleted_resources.append(audit)
                print(f"Found deleted {resource_type}: {audit.get('resource', {}).get('identifier', 'N/A')}")

            # Check if there are more pages
            if data.get("pageIndex", 0) >= data.get("totalPages", 1) - 1:
                break

            page += 1

        return deleted_resources

    def parse_resource_type(self, yaml_content: str) -> Optional[str]:
        """Parse YAML to determine resource type"""
        try:
            data = yaml.safe_load(yaml_content)

            if not data:
                return None

            # Check top-level keys to determine resource type
            if "pipeline" in data:
                return "pipeline"
            elif "inputSet" in data:
                return "inputSet"
            elif "template" in data:
                return "template"
            elif "service" in data:
                return "service"
            elif "environment" in data:
                return "environment"
            elif "infrastructure" in data:
                return "infrastructureDefinition"
            elif "connector" in data:
                return "connector"
            elif "secret" in data:
                return "secret"
            elif "project" in data:
                return "project"
            # Check if it's a secret manager
            elif isinstance(data, dict):
                # Check for secret manager types
                secret_manager_types = ["VaultConnector", "AwsSecretManager", "AzureKeyVault", "GcpSecretManager"]
                for key in data.keys():
                    if any(sm_type.lower() in key.lower() for sm_type in secret_manager_types):
                        return "secret"

            return None
        except Exception as e:
            print(f"Error parsing YAML: {e}")
            return None

    def recreate_pipeline(self, yaml_content: str, org_id: str, project_id: str) -> bool:
        """Recreate a pipeline from YAML"""
        url = f"{self.base_url}/pipeline/api/pipelines/v2"

        params = {
            "accountIdentifier": self.account_id,
            "orgIdentifier": org_id,
            "projectIdentifier": project_id
        }

        headers = self.headers.copy()
        headers["Content-Type"] = "application/yaml"

        response = requests.post(url, headers=headers, params=params, data=yaml_content)

        if response.status_code in [200, 201]:
            print("✓ Pipeline recreated successfully")
            return True
        else:
            print(f"✗ Failed to recreate pipeline: {response.status_code} - {response.text}")
            return False

    def recreate_service(self, yaml_content: str, org_id: str, project_id: str) -> bool:
        """Recreate a service from YAML"""
        url = f"{self.base_url}/ng/api/servicesV2"

        params = {
            "accountIdentifier": self.account_id
        }

        headers = self.headers.copy()
        headers["Content-Type"] = "application/yaml"

        response = requests.post(url, headers=headers, params=params, data=yaml_content)

        if response.status_code in [200, 201]:
            print("✓ Service recreated successfully")
            return True
        else:
            print(f"✗ Failed to recreate service: {response.status_code} - {response.text}")
            return False

    def recreate_environment(self, yaml_content: str, org_id: str, project_id: str) -> bool:
        """Recreate an environment from YAML"""
        url = f"{self.base_url}/ng/api/environmentsV2"

        params = {
            "accountIdentifier": self.account_id
        }

        headers = self.headers.copy()
        headers["Content-Type"] = "application/yaml"

        response = requests.post(url, headers=headers, params=params, data=yaml_content)

        if response.status_code in [200, 201]:
            print("✓ Environment recreated successfully")
            return True
        else:
            print(f"✗ Failed to recreate environment: {response.status_code} - {response.text}")
            return False

    def recreate_connector(self, yaml_content: str, org_id: str, project_id: str) -> bool:
        """Recreate a connector from YAML"""
        url = f"{self.base_url}/ng/api/connectors"

        params = {
            "accountIdentifier": self.account_id
        }

        # Convert YAML to JSON for connector API
        try:
            connector_data = yaml.safe_load(yaml_content)

            # Connector API expects JSON format
            headers = self.headers.copy()
            headers["Content-Type"] = "application/json"

            response = requests.post(url, headers=headers, params=params, json=connector_data)

            if response.status_code in [200, 201]:
                print("✓ Connector recreated successfully")
                return True
            else:
                print(f"✗ Failed to recreate connector: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"✗ Failed to parse connector YAML: {e}")
            return False

    def recreate_secret(self, yaml_content: str, org_id: str, project_id: str) -> bool:
        """Recreate a secret from YAML with placeholder value"""
        url = f"{self.base_url}/ng/api/v2/secrets"

        params = {
            "accountIdentifier": self.account_id
        }

        if org_id:
            params["orgIdentifier"] = org_id
        if project_id:
            params["projectIdentifier"] = project_id

        try:
            # Parse YAML and inject placeholder value
            secret_data = yaml.safe_load(yaml_content)

            # Add placeholder value for secret text
            if secret_data and "secret" in secret_data:
                secret_obj = secret_data["secret"]
                if secret_obj.get("type") == "SecretText":
                    if "spec" not in secret_obj:
                        secret_obj["spec"] = {}
                    # Set placeholder value - user must update this manually
                    secret_obj["spec"]["value"] = "PLACEHOLDER_UPDATE_MANUALLY"
                    print("⚠ Secret created with placeholder value - MUST be updated manually")

            # Convert back to YAML
            modified_yaml = yaml.dump(secret_data, default_flow_style=False)

            headers = self.headers.copy()
            headers["Content-Type"] = "application/yaml"

            response = requests.post(url, headers=headers, params=params, data=modified_yaml)

            if response.status_code in [200, 201]:
                print("✓ Secret recreated successfully (with placeholder value)")
                return True
            else:
                print(f"✗ Failed to recreate secret: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"✗ Failed to process secret YAML: {e}")
            return False

    def recreate_template(self, yaml_content: str, org_id: str, project_id: str) -> bool:
        """Recreate a template from YAML"""
        url = f"{self.base_url}/template/api/templates"

        params = {
            "accountIdentifier": self.account_id
        }

        if org_id:
            params["orgIdentifier"] = org_id
        if project_id:
            params["projectIdentifier"] = project_id

        headers = self.headers.copy()
        headers["Content-Type"] = "application/yaml"

        response = requests.post(url, headers=headers, params=params, data=yaml_content)

        if response.status_code in [200, 201]:
            print("✓ Template recreated successfully")
            return True
        else:
            print(f"✗ Failed to recreate template: {response.status_code} - {response.text}")
            return False

    def recreate_project(self, yaml_content: str, org_id: str, project_id: str) -> bool:
        """Recreate a project from YAML"""
        url = f"{self.base_url}/ng/api/projects"

        params = {
            "accountIdentifier": self.account_id
        }

        if org_id:
            params["orgIdentifier"] = org_id

        headers = self.headers.copy()
        headers["Content-Type"] = "application/yaml"

        response = requests.post(url, headers=headers, params=params, data=yaml_content)

        if response.status_code in [200, 201]:
            print("✓ Project recreated successfully")
            return True
        else:
            print(f"✗ Failed to recreate project: {response.status_code} - {response.text}")
            return False

    def recreate_resource(self, audit: Dict[str, Any], dry_run: bool = False) -> bool:
        """Recreate a deleted resource"""
        audit_id = audit.get("auditId")
        resource = audit.get("resource", {})
        resource_type = resource.get("type", "Unknown")
        resource_id = resource.get("identifier", "N/A")

        print(f"\n{'[DRY RUN] ' if dry_run else ''}Processing {resource_type}: {resource_id}")

        # Get the YAML content
        audit_data = self.get_audit_yaml(audit_id)

        if not audit_data or audit_data.get("status") != "SUCCESS":
            print(f"✗ Could not fetch audit YAML for {resource_id}")
            return False

        old_yaml = audit_data.get("data", {}).get("oldYaml")

        if not old_yaml:
            print(f"✗ No YAML content found for {resource_id}")
            return False

        if dry_run:
            print(f"Would recreate {resource_type}:")
            print("-" * 50)
            print(old_yaml[:500] + "..." if len(old_yaml) > 500 else old_yaml)
            print("-" * 50)
            return True

        # Extract org and project identifiers from the resource
        org_id = resource.get("orgIdentifier", "")
        project_id = resource.get("projectIdentifier", "")

        # Determine resource type and recreate
        parsed_type = self.parse_resource_type(old_yaml)

        if not parsed_type:
            print(f"⚠ Could not determine resource type for {resource_id}")
            return False

        # Map to recreation functions
        recreate_map = {
            "pipeline": self.recreate_pipeline,
            "service": self.recreate_service,
            "environment": self.recreate_environment,
            "connector": self.recreate_connector,
            "template": self.recreate_template,
            "secret": self.recreate_secret,
            "project": self.recreate_project
        }

        recreate_func = recreate_map.get(parsed_type)

        if recreate_func:
            return recreate_func(old_yaml, org_id, project_id)
        else:
            print(f"⚠ No recreation handler for resource type: {parsed_type}")
            return False

    def recover_all(self, start_date: str, end_date: str, dry_run: bool = False,
                    resource_filter: Optional[str] = None, include_ephemeral: bool = False,
                    only_core_resources: bool = False, save_metadata: Optional[str] = None,
                    exclude_types: Optional[List[str]] = None):
        """Main recovery function"""
        print(f"\n{'=' * 60}")
        print(f"Harness Resource Recovery Tool")
        print(f"{'=' * 60}")
        print(f"Account ID: {self.account_id}")
        print(f"Date Range: {start_date} to {end_date}")
        print(f"Dry Run: {dry_run}")
        if not include_ephemeral:
            print(f"Skipping: Delegates and Tokens (use --include-ephemeral to include)")
        if only_core_resources:
            print(f"Filtering: Pipelines, Services, Environments, Connectors, and Secrets only")
        if exclude_types:
            print(f"Excluding: {', '.join(exclude_types)}")
        if not self.session_token:
            print(f"⚠  No session token - YAML retrieval will be skipped")
            print(f"   Use --session-token to provide browser JWT for YAML access")
        print(f"{'=' * 60}\n")

        # Set resource types filter if only core resources requested
        resource_types_filter = None
        if only_core_resources:
            resource_types_filter = ["PIPELINE", "SERVICE", "ENVIRONMENT", "CONNECTOR", "SECRET"]

        # Find deleted resources
        deleted = self.find_deleted_resources(start_date, end_date,
                                               skip_ephemeral=not include_ephemeral,
                                               resource_types_filter=resource_types_filter,
                                               exclude_types=exclude_types)

        if not deleted:
            print("\n✓ No deleted resources found in the specified date range")
            return

        print(f"\n{'=' * 60}")
        print(f"Found {len(deleted)} deleted resource(s)")
        print(f"{'=' * 60}\n")

        # Filter by resource type if specified
        if resource_filter:
            deleted = [d for d in deleted if d.get("resource", {}).get("type", "").upper() == resource_filter.upper()]
            print(f"Filtered to {len(deleted)} resource(s) of type {resource_filter}\n")

        # Recreate resources
        success_count = 0
        fail_count = 0

        for audit in deleted:
            try:
                if self.recreate_resource(audit, dry_run):
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                print(f"✗ Error processing resource: {e}")
                fail_count += 1

        # Save metadata if requested
        if save_metadata:
            with open(save_metadata, 'w') as f:
                json.dump({
                    'account_id': self.account_id,
                    'date_range': {'start': start_date, 'end': end_date},
                    'deleted_resources': deleted,
                    'summary': {
                        'total': len(deleted),
                        'success': success_count,
                        'failed': fail_count
                    }
                }, f, indent=2)
            print(f"\n💾 Metadata saved to: {save_metadata}")

        # Summary
        print(f"\n{'=' * 60}")
        print(f"Recovery Summary")
        print(f"{'=' * 60}")
        print(f"Total: {len(deleted)}")
        print(f"Success: {success_count}")
        print(f"Failed: {fail_count}")
        print(f"{'=' * 60}\n")

        if not self.session_token and len(deleted) > 0:
            print(f"💡 To retrieve YAML definitions:")
            print(f"   1. Open browser dev tools (F12)")
            print(f"   2. Go to Network tab")
            print(f"   3. Visit Harness UI")
            print(f"   4. Find any API request")
            print(f"   5. Copy the 'Authorization: Bearer ...' token")
            print(f"   6. Run again with: --session-token 'eyJ0...'")
            print(f"{'=' * 60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Recover deleted Harness resources from audit logs",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--api-key",
        required=True,
        help="Harness API key (SAT token)"
    )

    parser.add_argument(
        "--session-token",
        help="Browser session JWT token for YAML retrieval (extract from browser dev tools)"
    )

    parser.add_argument(
        "--account-id",
        required=True,
        help="Harness account ID"
    )

    parser.add_argument(
        "--start-date",
        required=True,
        help="Start date (YYYY-MM-DD)"
    )

    parser.add_argument(
        "--end-date",
        required=True,
        help="End date (YYYY-MM-DD)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be recovered without actually recreating resources"
    )

    parser.add_argument(
        "--resource-type",
        help="Filter by resource type (e.g., PIPELINE, SERVICE, ENVIRONMENT)"
    )

    parser.add_argument(
        "--base-url",
        default="https://app.harness.io",
        help="Harness base URL (default: https://app.harness.io)"
    )

    parser.add_argument(
        "--include-ephemeral",
        action="store_true",
        help="Include ephemeral resources (delegates and tokens) - these are usually auto-generated"
    )

    parser.add_argument(
        "--only-core",
        action="store_true",
        help="Only recover core resources: pipelines, services, environments, connectors, and secrets"
    )

    parser.add_argument(
        "--save-metadata",
        help="Save deleted resources metadata to JSON file"
    )

    parser.add_argument(
        "--exclude-types",
        nargs="+",
        help="Exclude specific resource types (e.g., ROLE RESOURCE_GROUP)"
    )

    args = parser.parse_args()

    # Validate date format
    try:
        datetime.strptime(args.start_date, "%Y-%m-%d")
        datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError:
        print("Error: Dates must be in YYYY-MM-DD format")
        sys.exit(1)

    # Create recovery instance and run
    recovery = HarnessRecovery(args.api_key, args.account_id, args.base_url, args.session_token)
    recovery.recover_all(args.start_date, args.end_date, args.dry_run, args.resource_type,
                         args.include_ephemeral, args.only_core, args.save_metadata,
                         args.exclude_types)


if __name__ == "__main__":
    main()
