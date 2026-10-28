import json

import azure.functions as func

from callcenter_tools.logic import dispatch
from callcenter_tools.repo import CosmosRepo

# Access is enforced by App Service authentication (Entra), see infra/tools.bicep.
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

_repo = None


def _get_repo():
    global _repo
    if _repo is None:
        _repo = CosmosRepo()
    return _repo


@app.route(route="tools/{action}", methods=["POST"])
def call_tool(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(json.dumps({"error": "Body must be JSON"}), status_code=400, mimetype="application/json")
    status, payload = dispatch(_get_repo(), req.route_params["action"], body)
    return func.HttpResponse(json.dumps(payload), status_code=status, mimetype="application/json")
