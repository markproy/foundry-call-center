#!/usr/bin/env bash
# Creates (idempotently) the Entra app registration that represents the tools API,
# restricts it to explicitly assigned principals, and grants access to the given ones.
#
# Usage: scripts/setup_tools_auth.sh <principal-object-id>...
# Prints the app (client) id on stdout's last line.
#
# Needs permission to create app registrations and assign app roles in the tenant.
set -euo pipefail
NAME="fcc-tools-api"
DEFAULT_ROLE="00000000-0000-0000-0000-000000000000" # "default access" role

APP_ID="$(az ad app list --display-name "$NAME" --query '[0].appId' -o tsv)"
if [ -z "$APP_ID" ]; then
  APP_ID="$(az ad app create --display-name "$NAME" --sign-in-audience AzureADMyOrg --query appId -o tsv)"
  az ad app update --id "$APP_ID" --identifier-uris "api://$APP_ID"
fi
SP_ID="$(az ad sp list --filter "appId eq '$APP_ID'" --query '[0].id' -o tsv)"
if [ -z "$SP_ID" ]; then
  SP_ID="$(az ad sp create --id "$APP_ID" --query id -o tsv)"
fi
# Only assigned principals may obtain a token for this API.
az ad sp update --id "$SP_ID" --set appRoleAssignmentRequired=true

for PRINCIPAL in "$@"; do
  EXISTING="$(az rest --method GET \
    --url "https://graph.microsoft.com/v1.0/servicePrincipals/$SP_ID/appRoleAssignedTo" \
    --query "value[?principalId=='$PRINCIPAL'] | length(@)" -o tsv)"
  if [ "$EXISTING" = "0" ]; then
    az rest --method POST \
      --url "https://graph.microsoft.com/v1.0/servicePrincipals/$SP_ID/appRoleAssignedTo" \
      --body "{\"principalId\":\"$PRINCIPAL\",\"resourceId\":\"$SP_ID\",\"appRoleId\":\"$DEFAULT_ROLE\"}" >/dev/null
    echo "Granted $PRINCIPAL" >&2
  fi
done
echo "$APP_ID"
