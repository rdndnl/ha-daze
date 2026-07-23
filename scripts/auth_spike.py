"""Standalone spike: determine how to authenticate against the Daze Cognito backend.

Not part of the shipped Home Assistant integration. Run this once, by hand, to decide
which DazeAuthStrategy custom_components/daze/auth.py should implement.

Usage:
    export DAZE_EMAIL="you@example.com"
    export DAZE_PASSWORD="your-password"
    python3 scripts/auth_spike.py

Credentials are read from environment variables only (never CLI args) so they don't
end up in shell history or `ps` output.

What this does, in order, stopping at the first strategy that works end-to-end
(i.e. the resulting access token is actually accepted by the real backend, not just
by Cognito):

  1. Strategy A1: cognito-idp InitiateAuth with AuthFlow=USER_PASSWORD_AUTH.
  2. Strategy A2: cognito-idp InitiateAuth with AuthFlow=USER_SRP_AUTH (via pycognito),
     tried only if A1 is rejected as "flow not enabled".
  3. If both A1 and A2 are rejected, prints guidance for Strategy B (scripting the
     Managed Login hosted page) since that requires interactive HTML inspection this
     script can't do headlessly.

Requires: boto3, pycognito (pip install boto3 pycognito requests)
"""

from __future__ import annotations

import os
import sys

import requests

REGION = "eu-central-1"
USER_POOL_ID = "eu-central-1_vXrLKLO3t"
CLIENT_ID = "4m0rp7oqarbrc3hn67ivvonba8"
WEBAPI_BASE = "https://webapi.dazeservice.com"


def verify_access_token(email: str, access_token: str) -> bool:
    """The real success criterion: does the backend REST API accept this token?"""
    resp = requests.get(
        f"{WEBAPI_BASE}/v3/users/{email}/",
        params={"appName": 1},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    print(f"  -> GET /v3/users/{{email}}/?appName=1 => HTTP {resp.status_code}")
    if resp.ok:
        print(f"  -> body: {resp.text[:300]}")
        return True
    print(f"  -> body: {resp.text[:300]}")
    return False


def try_user_password_auth(email: str, password: str) -> dict | None:
    import boto3
    from botocore.exceptions import ClientError

    print("\n=== Strategy A1: USER_PASSWORD_AUTH ===")
    client = boto3.client("cognito-idp", region_name=REGION)
    try:
        resp = client.initiate_auth(
            ClientId=CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": email, "PASSWORD": password},
        )
    except ClientError as err:
        print(f"  Rejected: {err.response['Error']['Code']}: {err.response['Error']['Message']}")
        return None

    if "ChallengeName" in resp:
        print(f"  Got a challenge instead of tokens: {resp['ChallengeName']} (not handled by this spike)")
        return None

    result = resp["AuthenticationResult"]
    print("  Success: got AuthenticationResult directly from InitiateAuth.")
    return result


def try_user_srp_auth(email: str, password: str) -> dict | None:
    print("\n=== Strategy A2: USER_SRP_AUTH (via pycognito) ===")
    try:
        from pycognito import Cognito
    except ImportError:
        print("  pycognito not installed (pip install pycognito) - skipping.")
        return None

    try:
        user = Cognito(USER_POOL_ID, CLIENT_ID, user_pool_region=REGION, username=email)
        user.authenticate(password=password)
    except Exception as err:  # noqa: BLE001 - spike script, want to see anything that goes wrong
        print(f"  Rejected: {type(err).__name__}: {err}")
        return None

    print("  Success: SRP authentication completed.")
    return {
        "AccessToken": user.access_token,
        "IdToken": user.id_token,
        "RefreshToken": user.refresh_token,
    }


def main() -> int:
    email = os.environ.get("DAZE_EMAIL")
    password = os.environ.get("DAZE_PASSWORD")
    if not email or not password:
        print("Set DAZE_EMAIL and DAZE_PASSWORD environment variables first.", file=sys.stderr)
        return 2

    result = try_user_password_auth(email, password)
    strategy = "USER_PASSWORD_AUTH"

    if result is None:
        result = try_user_srp_auth(email, password)
        strategy = "USER_SRP_AUTH"

    if result is None:
        print(
            "\n=== Both direct strategies rejected ===\n"
            "Cognito app client likely only allows the Managed Login hosted-page flow.\n"
            "Strategy B (scripting /oauth2/authorize -> /login -> /oauth2/token) will be\n"
            "needed instead - see the plan's section 7 step B for what that involves.\n"
        )
        return 1

    access_token = result["AccessToken"]
    print(f"\n=== Verifying access token against real backend (strategy: {strategy}) ===")
    ok = verify_access_token(email, access_token)

    if ok:
        print(
            f"\nSUCCESS: {strategy} works end-to-end. "
            "Use CognitoDirectAuthStrategy in auth.py with this AuthFlow."
        )
        return 0

    print(
        "\nCognito accepted the login but webapi.dazeservice.com rejected the token - "
        "unexpected, needs investigation before picking this strategy."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
