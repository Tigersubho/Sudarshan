
import os
import time
import requests

from flask import Flask, render_template, request, Response, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

CLIENT_ID = os.getenv("SENTINEL_CLIENT_ID")
CLIENT_SECRET = os.getenv("SENTINEL_CLIENT_SECRET")
INSTANCE_ID = os.getenv("SENTINEL_INSTANCE_ID")

TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/"
    "auth/realms/CDSE/protocol/openid-connect/token"
)

WMS_URL = (
    f"https://sh.dataspace.copernicus.eu/"
    f"ogc/wms/{INSTANCE_ID}"
)

access_token = None
token_expiry = 0


def get_access_token():
    global access_token, token_expiry

    if access_token and time.time() < token_expiry:
        return access_token

    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError("Missing Sentinel Hub OAuth credentials")

    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        },
        timeout=30
    )

    response.raise_for_status()

    token_data = response.json()
    access_token = token_data["access_token"]
    token_expiry = time.time() + token_data.get("expires_in", 3600) - 60

    return access_token


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/radar")
def radar():
    if not INSTANCE_ID:
        return jsonify({
            "error": "Sentinel Hub Configuration Instance ID is missing."
        }), 503

    try:
        token = get_access_token()

        params = request.args.to_dict()
        params["SERVICE"] = "WMS"
        params["REQUEST"] = "GetMap"
        params["LAYERS"] = "S1_GRD_VV_VH"

        response = requests.get(
            WMS_URL,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=60
        )

        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers.get("Content-Type", "image/png")
        )

    except requests.RequestException:
        app.logger.exception("Sentinel Hub radar request failed")
        return jsonify({
            "error": "Could not retrieve radar imagery."
        }), 502

    except Exception:
        app.logger.exception("Radar service error")
        return jsonify({
            "error": "Radar service configuration or authentication error."
        }), 500


@app.route("/api/capabilities")
def capabilities():
    if not INSTANCE_ID:
        return jsonify({
            "error": "Sentinel Hub Configuration Instance ID is missing."
        }), 503

    try:
        token = get_access_token()

        response = requests.get(
            WMS_URL,
            params={
                "SERVICE": "WMS",
                "REQUEST": "GetCapabilities"
            },
            headers={
                "Authorization": f"Bearer {token}"
            },
            timeout=60
        )

        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers.get(
                "Content-Type",
                "application/xml"
            )
        )

    except requests.RequestException:
        app.logger.exception("Sentinel Hub capabilities request failed")
        return jsonify({
            "error": "Could not retrieve Sentinel Hub layer information."
        }), 502

    except Exception:
        app.logger.exception("Capabilities service error")
        return jsonify({
            "error": "Authentication or configuration error."
        }), 500


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
