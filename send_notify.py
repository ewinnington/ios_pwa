#!/usr/bin/env python3
"""CLI tool to send a push notification via the CloudPlush server."""

import argparse
import requests


def main():
    parser = argparse.ArgumentParser(description="Send a CloudPlush push notification")
    parser.add_argument("-t", "--title", required=True, help="Notification title")
    parser.add_argument("-b", "--body", required=True, help="Notification body")
    parser.add_argument(
        "-d", "--device", type=int, nargs="+",
        help="Device ID(s) to target (omit to send to all)",
    )
    parser.add_argument(
        "-l", "--list-devices", action="store_true",
        help="List subscribed devices and exit",
    )
    parser.add_argument(
        "-s", "--server", default="http://localhost:8899", help="Server URL",
    )
    args = parser.parse_args()

    if args.list_devices:
        resp = requests.get(f"{args.server}/api/subscriptions/count", timeout=10)
        resp.raise_for_status()
        print(resp.json())
        return

    payload = {"title": args.title, "body": args.body}
    if args.device:
        payload["device_ids"] = args.device

    resp = requests.post(
        f"{args.server}/api/send", json=payload, timeout=15,
    )
    resp.raise_for_status()
    result = resp.json()

    print(f"Sent to {result['sent']} device(s)", end="")
    if result["failed"]:
        print(f", {result['failed']} failed", end="")
    print()


if __name__ == "__main__":
    main()
