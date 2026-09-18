"""Provision a test device + patient on kneespa-cloud and print env vars.

Usage:
    python scripts/cloud_setup.py --url https://kneespa-cloud.onrender.com \
        --email admin@example.com --password 'secret'
"""
import argparse
import json
import sys
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import (
    HTTPCookieProcessor,
    Request,
    build_opener,
)

BASE = ""
OPENER = None


def init(url):
    global BASE, OPENER
    BASE = url.rstrip("/")
    jar = CookieJar()
    OPENER = build_opener(HTTPCookieProcessor(jar))


def api(method, path, body=None, expect_err=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = Request(url, data=data, headers=headers, method=method)
    try:
        resp = OPENER.open(req, timeout=90)
        return json.loads(resp.read().decode())
    except HTTPError as e:
        if expect_err and e.code in expect_err:
            return {"_error": e.code}
        print(f"  HTTP {e.code}: {e.read().decode()}", file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description="Bootstrap kneespa-cloud test data")
    parser.add_argument("--url", required=True, help="Cloud base URL")
    parser.add_argument("--email", required=True, help="Admin email")
    parser.add_argument("--password", required=True, help="Admin password")
    parser.add_argument("--device-id", default="drx2-bench-01", help="Device ID slug")
    parser.add_argument("--device-name", default="DRX-2 Bench Unit", help="Device display name")
    parser.add_argument("--patient-name", default="Test Patient", help="Patient display name")
    parser.add_argument("--patient-ref", default="TP-001", help="Patient external ref")
    args = parser.parse_args()

    init(args.url)

    print("1. Logging in …")
    api("POST", "/api/v1/admin/login", {"email": args.email, "password": args.password})
    print("   OK")

    print("\n2. Existing devices:")
    devices = api("GET", "/api/v1/admin/devices")
    for d in devices:
        print(f"   - {d['device_id']} ({d['name']})  revoked={d.get('revoked')}")

    device_token = None
    existing = [d for d in devices if d["device_id"] == args.device_id]
    if existing:
        print(f"\n   Device '{args.device_id}' already exists — rotating token …")
        db_id = existing[0]["id"]
        rot = api("POST", f"/api/v1/admin/devices/{db_id}/rotate-token")
        device_token = rot["token"]
    else:
        print(f"\n3. Registering device '{args.device_id}' …")
        reg = api("POST", "/api/v1/admin/devices", {
            "device_id": args.device_id,
            "name": args.device_name,
        }, expect_err={409})
        if "_error" in reg:
            print("   409 conflict — device exists, rotating token")
            for d in api("GET", "/api/v1/admin/devices"):
                if d["device_id"] == args.device_id:
                    rot = api("POST", f"/api/v1/admin/devices/{d['id']}/rotate-token")
                    device_token = rot["token"]
                    break
        else:
            device_token = reg["token"]
            print(f"   Registered: {reg['id']}")

    print("\n4. Existing patients:")
    patients = api("GET", "/api/v1/admin/patients")
    for p in patients:
        print(f"   - {p['display_name']} (ref={p['external_ref']}, status={p['status']}, sessions={p['session_count']})")

    pin = None
    existing_pat = [p for p in patients if p["external_ref"] == args.patient_ref]
    if existing_pat:
        print(f"\n   Patient '{args.patient_ref}' already exists — regenerating PIN …")
        pat_id = existing_pat[0]["id"]
        regen = api("POST", f"/api/v1/admin/patients/{pat_id}/regenerate-pin")
        pin = regen["pin"]
    else:
        print(f"\n5. Creating patient '{args.patient_name}' …")
        pat = api("POST", "/api/v1/admin/patients", {
            "external_ref": args.patient_ref,
            "display_name": args.patient_name,
            "protocol_number": 1,
            "max_pressure_lb": 50.0,
            "max_left_deg": 15.0,
            "max_right_deg": 15.0,
            "pulse_rate_hz": 0.5,
            "duration_min": 10,
        })
        pin = pat["pin"]
        print(f"   Created: {pat['id']}")

    print("\n" + "=" * 60)
    print("Done!  Set these env vars on the Pi (or in .env):\n")
    print(f"  KNEESPA_CLOUD_URL={args.url}")
    print(f"  KNEESPA_DEVICE_ID={args.device_id}")
    print(f"  KNEESPA_DEVICE_TOKEN={device_token}")
    print(f"\nPatient PIN (enter on treatment screen): {pin}")
    print("=" * 60)


if __name__ == "__main__":
    main()
