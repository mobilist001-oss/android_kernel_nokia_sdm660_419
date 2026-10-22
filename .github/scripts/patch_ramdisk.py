#!/usr/bin/env python3
import os
import re
import sys

USER_ADB_KEY = (
    "AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBHzB+5aFw27W4B6q3Qj2hP6u45h7N28nE92/B86z/U/bWcQd7U0r1q5t5oY5lEw2n+q0V6T6R7L6v+w7/b+H4pQ= ok@DESKTOP-8O93B5C\n"
    "QAAAALcm9mH5aPac7/U8NOldtOmV4VP6MIrNoyax3B7tewGaA2s8yaGeDRu5g4gadTU31j0o9VDW4Wr2C+HWGpLT51sAQMc0dXBjGn+alBwrHfkTGYCaYpUqQ15n0BDLhYCY2BLM8bZmr7SA5tvkZq/uOsHC5aLg/30NZnAiPDSsq+xqJopGt4zJIyvmzSuRwShoRhi0aHWEAqsl6a+tQYiiGsnDb1QvFRnntI+uJ9jzgeaN9kPtvFAZcnzeZdKyh+gQsYKpn4jJzIaZPdn3dr9ltM8w5d0xam69oGgZiILO8lnzNCRhLJK1ICZK8Xgl7t8vBVFcrom/s1Rbu4gwDIs+RpQ1Q2fq4f+wQf/y9PVzjJmbulFYHSCiCVdf7hB5PxzaEZH7CgqG5Tcde6MLc7IOMghamtPJJUnpqppI9DvfNejME+HF9Tuk1cwEiI4cujW0DldpTiVgb3oDOh88xVs+/LgKTJFHXNxvfaYHZ7Ci5tYkoWxekvMh9a4pFCNHkqdifdy8pcfw/FIFKsSJ0+9FWRvM8had22IDRnVBwwGT/OJiHGw/sKTylTh7OJyNJoAi2seNY6LqgcxPxeqmR4slMPPtkpZnbuCts3w9iAEAG4qErW9jFYZQ488UhfsSNhekJHXqkHgtaWKTs+WfYffa/0BcpLGUFthogE1mlk8lcBptYT8WPAEAAQA= unknown@unknown\n"
)

def patch_ramdisk(rd_dir):
    print(f"Patching ramdisk at: {rd_dir}")
    if not os.path.exists(rd_dir):
        print(f"ERROR: Directory {rd_dir} does not exist!")
        sys.exit(1)

    # 1. Bake ADB host public key into recovery rootfs so device trusts host automatically
    key_targets = [
        os.path.join(rd_dir, "adb_keys"),
        os.path.join(rd_dir, "system", "etc", "security", "adbd_keys"),
        os.path.join(rd_dir, "data", "misc", "adb", "adb_keys")
    ]
    for kt in key_targets:
        try:
            if os.path.islink(kt) or os.path.lexists(kt):
                os.remove(kt)
            os.makedirs(os.path.dirname(os.path.abspath(kt)), exist_ok=True)
            with open(kt, "w", encoding="utf-8") as f:
                f.write(USER_ADB_KEY)
            print(f"Injected host ADB public key to {kt}")
        except Exception as e:
            print(f"Warning: could not write {kt}: {e}")

    # 2. Properties: Strip any conflicting ro.secure / ro.adb.secure / sys.usb props
    prop_candidates = [
        "prop.default",
        "default.prop",
        "system/etc/prop.default"
    ]
    props_to_add = (
        "\n# --- 4.19 Bringup Root & USB Config ---\n"
        "ro.adb.secure=0\n"
        "ro.adb.secure.recovery=0\n"
        "ro.debuggable=1\n"
        "ro.secure=0\n"
        "security.perf_harden=0\n"
        "persist.service.adb.enable=1\n"
        "persist.service.debuggable=1\n"
        "service.adb.root=1\n"
        "persist.sys.usb.config=adb\n"
        "sys.usb.config=adb\n"
        "sys.usb.configfs=1\n"
        "sys.usb.controller=a800000.dwc3\n"
        "ro.recovery.usb.vid=18D1\n"
        "ro.recovery.usb.adb.pid=D001\n"
    )

    found_prop = False
    for rel_path in prop_candidates:
        full_path = os.path.join(rd_dir, rel_path)
        if os.path.exists(full_path):
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            clean_lines = [
                l for l in lines 
                if not re.match(r"^(sys\.usb\.config|persist\.sys\.usb\.config|ro\.adb\.secure|ro\.secure|ro\.debuggable|service\.adb\.root|security\.perf_harden)=", l.strip())
            ]
            with open(full_path, "w", encoding="utf-8") as f:
                f.writelines(clean_lines)
                f.write(props_to_add)
            print(f"Updated properties in {full_path}")
            found_prop = True

    # Ensure prop.default at root
    root_prop = os.path.join(rd_dir, "prop.default")
    if not os.path.exists(root_prop):
        with open(root_prop, "w", encoding="utf-8") as f:
            f.write(props_to_add)
        print(f"Created {root_prop}")

    # 3. Patch all .rc files to un-disable adbd
    rc_count = 0
    adbd_patched_count = 0
    for root, dirs, files in os.walk(rd_dir):
        for file in files:
            if file.endswith(".rc"):
                rc_count += 1
                rc_path = os.path.join(root, file)
                with open(rc_path, "r", encoding="utf-8", errors="ignore") as fp:
                    lines = fp.readlines()

                modified = False
                in_adbd = False
                new_lines = []
                for line in lines:
                    if re.match(r"^service\s+adbd\b", line):
                        in_adbd = True
                    elif in_adbd and re.match(r"^(service|on)\s+", line):
                        in_adbd = False

                    if in_adbd and re.match(r"^\s+disabled\b", line):
                        line = re.sub(r"^\s+disabled\b", "    # disabled (bringup auto-start)", line)
                        modified = True
                    new_lines.append(line)

                if modified:
                    adbd_patched_count += 1
                    print(f"Un-disabled service adbd in {rc_path}")
                    with open(rc_path, "w", encoding="utf-8") as fp:
                        fp.writelines(new_lines)

    print(f"Scanned {rc_count} .rc files, un-disabled adbd in {adbd_patched_count} files")

    # 4. Patch init.rc to inject triggers and failsafe services
    init_rc_candidates = [
        "init.rc",
        "system/etc/init/hw/init.rc",
        "etc/init/hw/init.rc"
    ]
    patched_init_count = 0

    failsafe_services = """
# --- 4.19 Bringup Failsafe Services ---
service dump_dmesg /system/bin/sh -c "while true; do dmesg > /tmp/dmesg_419.txt 2>/dev/null; for p in /dev/block/bootdevice/by-name/cache /dev/block/platform/soc/*/by-name/cache /dev/block/by-name/cache; do if [ -b $p ]; then mount -t ext4 $p /cache 2>/dev/null && dmesg > /cache/dmesg_419.txt 2>/dev/null && sync; fi; done; sleep 2; done"
    seclabel u:r:recovery:s0
"""

    for rel_path in init_rc_candidates:
        rc_path = os.path.join(rd_dir, rel_path)
        if os.path.exists(rc_path):
            with open(rc_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Inject watchdogd start into 'on init'
            if "on init\n" in content and "start watchdogd" not in content:
                content = content.replace(
                    "on init\n",
                    "on init\n    start watchdogd\n",
                    1
                )

            # Trigger USB config and failsafe in 'on boot' (when ConfigFS & FunctionFS are mounted)
            if "on boot\n" in content and "start dump_dmesg" not in content:
                content = content.replace(
                    "on boot\n",
                    "on boot\n    setprop sys.usb.config none\n    setprop sys.usb.config adb\n    start dump_dmesg\n",
                    1
                )

            # Append failsafe services
            if "service dump_dmesg" not in content:
                content += failsafe_services

            with open(rc_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Injected clean boot triggers & services into {rc_path}")
            patched_init_count += 1

    print(f"Patched {patched_init_count} main init.rc files successfully.")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    patch_ramdisk(target)
