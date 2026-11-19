"""Find Tapo devices on your Wi-Fi and save them to .env (uses the names from the Tapo app)."""
import asyncio
import base64
import re
import subprocess

from jarvis import config


async def main():
    from tapo import ApiClient

    if not (config.TAPO_EMAIL and config.TAPO_PASSWORD):
        print("Fill in TAPO_EMAIL and TAPO_PASSWORD in .env first.")
        return
    ip = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True).stdout.strip()
    broadcast = ".".join(ip.split(".")[:3]) + ".255"
    print(f"Searching {broadcast} ...")
    client = ApiClient(config.TAPO_EMAIL, config.TAPO_PASSWORD)
    found = {}
    async for result in await client.discover_devices(broadcast, 5):
        try:
            dev = result.get()
            info = dev.device_info.to_dict()
            name = info.get("nickname") or info["model"]
            if not re.search(r"\s", name) and name.endswith("="):  # older firmware base64-encodes names
                name = base64.b64decode(name).decode()
            found[name.lower().replace(",", " ")] = info["ip"]
            print(f"  found {name} ({info['model']}) at {info['ip']}")
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "Unauthorized" in msg:
                ip_m = re.search(r'ip: "([\d.]+)"', msg)
                print(f"  {ip_m.group(1) if ip_m else 'a device'} rejected the login (wrong password, or needs Third-Party Compatibility on in the Tapo app)")
            else:
                print(f"  skipped a device: {msg[:120]}")
    if not found:
        print("No Tapo devices found. Check the email/password and that the Mac is on the same Wi-Fi.")
        return
    line = "TAPO_DEVICES=" + ",".join(f"{k}={v}" for k, v in found.items())
    env = config.ROOT / ".env"
    env.write_text(re.sub(r"^TAPO_DEVICES=.*$", line, env.read_text(), flags=re.M))
    print(f"Saved {len(found)} devices to .env. Restart JARVIS to use them.")


asyncio.run(main())
