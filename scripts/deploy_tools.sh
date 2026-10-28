#!/usr/bin/env bash
# Deploys the tool backends: infra (Cosmos + Function App) then the function code.
# Usage: scripts/deploy_tools.sh <resource-group> [principal-object-id ...]
# Principals (e.g. agent identities) are granted access to the tools API; the
# signed-in user is always granted so the API can be tested locally.
set -euo pipefail
RG="${1:?usage: deploy_tools.sh <resource-group> [principal-object-id ...]}"
shift
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

PRINCIPAL_ID="$(az ad signed-in-user show --query id -o tsv)"
API_CLIENT_ID="$("$ROOT/scripts/setup_tools_auth.sh" "$PRINCIPAL_ID" "$@" | tail -1)"
OUT="$(az deployment group create -g "$RG" -n tools -f "$ROOT/infra/tools.bicep" \
  -p loaderPrincipalId="$PRINCIPAL_ID" toolsApiClientId="$API_CLIENT_ID" --query properties.outputs -o json)"
FUNC="$(echo "$OUT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["functionAppName"]["value"])')"

# Flex Consumption runs Linux/py3.11: vendor wheels for that target, not this machine.
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD" "$BUILD.zip"' EXIT
cp -R "$ROOT/tools/callcenter_tools" "$ROOT/tools/function_app.py" "$ROOT/tools/host.json" "$ROOT/tools/requirements.txt" "$BUILD/"
pip install -q -r "$ROOT/tools/requirements.txt" --target "$BUILD/.python_packages/lib/site-packages" \
  --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.11 --implementation cp
(cd "$BUILD" && zip -qr "$BUILD.zip" . -x '*/__pycache__/*')
az functionapp deployment source config-zip -g "$RG" -n "$FUNC" --src "$BUILD.zip"
echo "Deployed $FUNC"
