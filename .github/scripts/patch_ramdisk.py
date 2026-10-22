#!/usr/bin/env python3
import os
import re
import sys

USER_ADB_KEY = (
    "QAAAALcm9mH5aPac7/U8NOldtOmV4VP6MIrNoyax3B7tewGaA2s8yaGeDRu5g4gadTU31j0o9VDW4Wr2C+HWGpLT51sAQMc0dXBjGn+alBwrHfkTGYCaYpUqQ15n0BDLhYCY2BLM8bZmr7SA5tvkZq/uOsHC5aLg/30NZnAiPDSsq+xqJopGt4zJIyvmzSuRwShoRhi0aHWEAqsl6a+tQYiiGsnDb1QvFRnntI+uJ9jzgeaN9kPtvFAZcnzeZdKyh+gQsYKpn4jJzIaZPdn3dr9ltM8w5d0xam69oGgZiILO8lnzNCRhLJK1ICZK8Xgl7t8vBVFcrom/s1Rbu4gwDIs+RpQ1Q2fq4f+wQf/y9PVzjJmbulFYHSCiCVdf7hB5PxzaEZH7CgqG5Tcde6MLc7IOMghamtPJJUnpqppI9DvfNejME+HF9Tuk1cwEiI4cujW0DldpTiVgb3oDOh88xVs+/LgKTJFHXNxvfaYHZ7Ci5tYkoWxekvMh9a4pFCNHkqdifdy8pcfw/FIFKsSJ0+9FWRvM8had22IDRnVBwwGT/OJiHGw/sKTylTh7OJyNJoAi2seNY6LqgcxPxeqmR4slMPPtkpZnbuCts3w9iAEAG4qErW9jFYZQ488UhfsSNhekJHXqkHgtaWKTs+WfYffa/0BcpLGUFthogE1mlk8lcBptYT8WPAEAAQA= ok@DESKTOP-8O93B5C\n"
)

def patch_ramdisk(rd_dir):
    print(f"Patching ramdisk at: {rd_dir}")
    if not os.path.exists(rd_dir):
        print(f"ERROR: Directory {rd_dir} does not exist!")
        sys.exit(1)

    # 1. Bake host RSA public key into recovery rootfs so device trusts host automatically
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

    # 2. Properties: Set root & permissive ADB properties (without baking sys.usb.config so trigger fires)
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
        "sys.usb.configfs=1\n"
        "sys.usb.controller=a800000.dwc3\n"
        "ro.recovery.usb.vid=18D1\n"
        "ro.recovery.usb.adb.pid=D001\n"
    )

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

    root_prop = os.path.join(rd_dir, "prop.default")
    if not os.path.exists(root_prop):
        with open(root_prop, "w", encoding="utf-8") as f:
            f.write(props_to_add)
        print(f"Created {root_prop}")

    # 3. Patch init.rc to trigger clean USB bringup, neutralize charger, enable console & persistent flash logging
    init_rc_candidates = [
        "init.rc",
        "system/etc/init/hw/init.rc",
        "etc/init/hw/init.rc"
    ]
    patched_init_count = 0

    failsafe_services = """
# --- 4.19 Bringup Failsafe Services ---
service dump_dmesg /system/bin/sh /dump_dmesg.sh
    seclabel u:r:recovery:s0
"""

    for rel_path in init_rc_candidates:
        rc_path = os.path.join(rd_dir, rel_path)
        if os.path.exists(rc_path):
            with open(rc_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Neutralize charger service: remove critical and mark disabled so off-mode charger timeout never reboots device
            def neutralize_charger(m):
                block = m.group(0)
                lines = [l for l in block.splitlines(keepends=True) if l.strip() != "critical"]
                if not any(l.strip() == "disabled" for l in lines):
                    lines.insert(1, "    disabled\n")
                return "".join(lines)

            content = re.sub(
                r"service charger /system/bin/charger.*?(?=\n\S|\Z)",
                neutralize_charger,
                content,
                flags=re.DOTALL
            )

            # Enable console service with root permissions
            def make_console_root(m):
                block = m.group(0)
                block = re.sub(r"\buser shell\b", "user root", block)
                block = re.sub(r"\bgroup shell\b", "group root shell", block)
                block = re.sub(r"\bseclabel u:r:shell:s0\b", "seclabel u:r:recovery:s0", block)
                return block

            content = re.sub(
                r"service console /system/bin/sh.*?(?=\n\S|\Z)",
                make_console_root,
                content,
                flags=re.DOTALL
            )

            # Clean trigger on boot: sets sys.usb.config once after ConfigFS is mounted and starts failsafe services & console
            if "on boot\n" in content and "setprop sys.usb.config adb" not in content:
                content = content.replace(
                    "on boot\n",
                    "on boot\n    setprop sys.usb.config adb\n    start dump_dmesg\n    start console\n",
                    1
                )

            # Append failsafe services
            if "service dump_dmesg" not in content:
                content += failsafe_services

            with open(rc_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Injected clean boot triggers & services into {rc_path}")
            patched_init_count += 1

    # 4. Inject live diagnostic & failsafe helper scripts
    dump_dmesg_sh = """#!/system/bin/sh
while true; do
    dmesg > /tmp/dmesg_419.txt 2>/dev/null
    dmesg > /dev/block/bootdevice/by-name/logdump 2>/dev/null
    sync
    sleep 2
done
"""
    diag_fb_sh = """#!/system/bin/sh
echo "=== Display & FB0 Diagnostics ==="
ls -l /dev/graphics/
for prop in virtual_size modes bits_per_pixel; do
    if [ -f /sys/class/graphics/fb0/$prop ]; then
        echo -n "$prop: "
        cat /sys/class/graphics/fb0/$prop
    fi
done
echo "Testing fb0 read (first 1024 bytes)..."
head -c 1024 /dev/graphics/fb0 | wc -c
echo "Done fb0 read test."
"""
    test_recovery_sh = """#!/system/bin/sh
echo "=== Launching Recovery in Show Text Mode ==="
/system/bin/recovery --show_text 2>&1 | tee /tmp/rec.log
"""

    for sname, scontent in [("dump_dmesg.sh", dump_dmesg_sh), ("diag_fb.sh", diag_fb_sh), ("test_recovery.sh", test_recovery_sh)]:
        for base in [rd_dir, os.path.join(rd_dir, "system", "bin")]:
            if os.path.exists(base):
                spath = os.path.join(base, sname)
                with open(spath, "w", encoding="utf-8") as sf:
                    sf.write(scontent)
                try:
                    os.chmod(spath, 0o755)
                except Exception:
                    pass
                print(f"Injected helper script: {spath}")

    print(f"Patched {patched_init_count} main init.rc files successfully.")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    patch_ramdisk(target)

