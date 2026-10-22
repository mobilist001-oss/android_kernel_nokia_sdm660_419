#!/usr/bin/env python3
import os
import re
import sys

def patch_ramdisk(rd_dir):
    print(f"Patching ramdisk at: {rd_dir}")
    if not os.path.exists(rd_dir):
        print(f"ERROR: Directory {rd_dir} does not exist!")
        sys.exit(1)

    # 1. Properties
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
            clean_lines = [l for l in lines if not re.match(r"^(sys\.usb\.config|persist\.sys\.usb\.config|ro\.adb\.secure|service\.adb\.root)=", l.strip())]
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

    # 2. Patch all .rc files to remove 'disabled' from service adbd
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

    # 3. Patch init.rc to inject triggers and failsafe services
    init_rc_candidates = [
        "init.rc",
        "system/etc/init/hw/init.rc",
        "etc/init/hw/init.rc"
    ]
    patched_init_count = 0

    failsafe_services = """
# --- 4.19 Bringup Failsafe Services ---
service dump_dmesg /system/bin/sh -c "mkdir -p /cache; mount -t ext4 /dev/block/bootdevice/by-name/cache /cache 2>/dev/null || mount /dev/block/by-name/cache /cache 2>/dev/null || true; while true; do dmesg > /cache/dmesg_419.txt; sync; sleep 5; done"
    oneshot
    seclabel u:r:recovery:s0

service pet_watchdog /system/bin/sh -c "while true; do echo V > /dev/watchdog 2>/dev/null || true; sleep 5; done"
    oneshot
    seclabel u:r:recovery:s0

service adbd_failsafe /system/bin/sh -c "sleep 1; setprop sys.usb.config none; sleep 1; setprop sys.usb.config adb; /system/bin/start adbd 2>/dev/null || true"
    oneshot
    seclabel u:r:recovery:s0
"""

    for rel_path in init_rc_candidates:
        rc_path = os.path.join(rd_dir, rel_path)
        if os.path.exists(rc_path):
            with open(rc_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Inject into 'on init'
            if "on init\n" in content and "start dump_dmesg" not in content:
                content = content.replace(
                    "on init\n",
                    "on init\n    setprop sys.usb.config adb\n    start adbd\n    start dump_dmesg\n    start pet_watchdog\n    start adbd_failsafe\n",
                    1
                )

            # Inject into 'on boot'
            if "on boot\n" in content and "setprop sys.usb.config adb" not in content:
                content = content.replace(
                    "on boot\n",
                    "on boot\n    setprop sys.usb.config adb\n    start adbd\n",
                    1
                )

            # Inject into 'on post-fs'
            if "on post-fs\n" in content and "start adbd" not in content:
                content = content.replace(
                    "on post-fs\n",
                    "on post-fs\n    setprop sys.usb.config adb\n    start adbd\n",
                    1
                )

            # Append failsafe services
            if "service dump_dmesg" not in content:
                content += failsafe_services

            with open(rc_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Injected failsafe triggers & services into {rc_path}")
            patched_init_count += 1

    print(f"Patched {patched_init_count} main init.rc files successfully.")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    patch_ramdisk(target)
