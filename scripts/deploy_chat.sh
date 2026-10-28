#!/usr/bin/env bash
# Deploys the chat backend + UI to Azure Container Apps and grants its managed
# identity access to the Foundry account (ADR-0007).
# Usage: scripts/deploy_chat.sh <resource-group> <foundry-account-name> <foundry-project-name>
# Env: DEMO_SHARED_SECRET (optional) gates /api/chat.
set -euo pipefail
RG="${1:?usage: deploy_chat.sh <rg> <foundry-account> <foundry-project>}"
ACCOUNT="${2:?}"
PROJECT="${3:?}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

SUB="$(az account show --query id -o tsv)"
ACCOUNT_ID="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.CognitiveServices/accounts/$ACCOUNT"
ENDPOINT="https://$ACCOUNT.services.ai.azure.com/api/projects/$PROJECT"
out() { python3 -c "import json,sys;print(json.load(sys.stdin)['$1']['value'])"; }

# Custom role: lets a middle tier send x-ms-user-identity (ADR-0006/0007).
# The JSON holds placeholders for the subscription and resource group, filled in here.
if ! az role definition list --custom-role-only true --query "[?roleName=='Foundry Agent User Identity Delegate'].name" -o tsv | grep -q .; then
  ROLE_JSON="$(mktemp)"
  sed -e "s|<subscription-id>|$SUB|" -e "s|<resource-group>|$RG|" "$ROOT/infra/roles/user-identity-delegate.json" > "$ROLE_JSON"
  az role definition create --role-definition "$ROLE_JSON" -o none
  rm -f "$ROLE_JSON"
fi

# Admin API secret: env ADMIN_SECRET, else the one already on the app, else a new random one.
if [ -z "${ADMIN_SECRET:-}" ]; then
  EXISTING_APP="$(az containerapp list -g "$RG" --query "[?starts_with(name,'fcc-chat')].name | [0]" -o tsv 2>/dev/null || true)"
  if [ -n "$EXISTING_APP" ]; then
    ADMIN_SECRET="$(az containerapp secret show -g "$RG" -n "$EXISTING_APP" --secret-name admin-secret --query value -o tsv 2>/dev/null || true)"
  fi
  if [ -z "${ADMIN_SECRET:-}" ]; then
    ADMIN_SECRET="$(openssl rand -hex 16)"
    echo "Generated admin secret (also stored on the app as secret 'admin-secret'): $ADMIN_SECRET"
  fi
fi
COSMOS_ACCOUNT="$(az cosmosdb list -g "$RG" --query "[0].name" -o tsv)"
COSMOS_ENDPOINT="$(az cosmosdb show -g "$RG" -n "$COSMOS_ACCOUNT" --query documentEndpoint -o tsv)"
# Eval history container (also declared in infra/tools.bicep).
az cosmosdb sql container create -g "$RG" -a "$COSMOS_ACCOUNT" -d callcenter -n evalruns -p /id -o none 2>/dev/null || true

deploy() {
  az deployment group create -g "$RG" -n chat -f "$ROOT/infra/chat.bicep" \
    -p foundryProjectEndpoint="$ENDPOINT" demoSharedSecret="${DEMO_SHARED_SECRET:-}" \
    cosmosEndpoint="$COSMOS_ENDPOINT" adminSecret="$ADMIN_SECRET" captureContent="${CAPTURE_CONTENT:-true}" "$@" \
    --query properties.outputs -o json
}

OUT="$(deploy)"
ACR="$(echo "$OUT" | out acrName)"
LOGIN="$(echo "$OUT" | out acrLoginServer)"
PID="$(echo "$OUT" | out principalId)"
ACR_ID="$(az acr show -n "$ACR" --query id -o tsv)"

az role assignment create --assignee-object-id "$PID" --assignee-principal-type ServicePrincipal \
  --role AcrPull --scope "$ACR_ID" -o none 2>/dev/null || true
for ROLE in "Foundry User" "Cognitive Services User" "Foundry Agent User Identity Delegate"; do
  az role assignment create --assignee-object-id "$PID" --assignee-principal-type ServicePrincipal \
    --role "$ROLE" --scope "$ACCOUNT_ID" -o none 2>/dev/null || true
done

# Admin dashboard: read App Insights (REST API) and read/write the evalruns container.
APPI_ID="$(az resource show -g "$RG" -n "$(echo "$OUT" | out appInsightsName)" --resource-type Microsoft.Insights/components --query id -o tsv)"
az role assignment create --assignee-object-id "$PID" --assignee-principal-type ServicePrincipal \
  --role "Monitoring Reader" --scope "$APPI_ID" -o none 2>/dev/null || true
az cosmosdb sql role assignment create -g "$RG" -a "$COSMOS_ACCOUNT" --principal-id "$PID" \
  --role-definition-id 00000000-0000-0000-0000-000000000002 --scope "/" -o none 2>/dev/null || true

TAG="$(date +%Y%m%d%H%M%S)"
az acr build -r "$ACR" -t "chat:$TAG" -f "$ROOT/src/chat-backend/Dockerfile" "$ROOT" --no-logs -o none
sleep 30 # let the AcrPull assignment propagate
OUT="$(deploy -p useAcr=true image="$LOGIN/chat:$TAG")"
echo "Deployed $(echo "$OUT" | out url)"
