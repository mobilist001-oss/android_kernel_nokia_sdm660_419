#!/usr/bin/env python3
import struct
import sys
import os

def isolate_dtb(input_file, out_kernel_dtb, out_dtb_only):
    print(f"Reading input kernel image: {input_file}")
    if not os.path.exists(input_file):
        print(f"ERROR: Input file {input_file} does not exist!")
        sys.exit(1)

    with open(input_file, "rb") as f:
        data = f.read()

    dtb_magic = b"\xd0\x0d\xfe\xed"
    first_dtb_pos = data.find(dtb_magic)
    if first_dtb_pos == -1:
        print("ERROR: No DTB magic (0xd00dfeed) found in image!")
        sys.exit(1)

    kernel_img = data[:first_dtb_pos]
    print(f"Extracted Image.gz: {len(kernel_img)} bytes (offset 0 to {first_dtb_pos})")

    pos = first_dtb_pos
    dtb_list = []
    while pos < len(data):
        if data[pos:pos+4] != dtb_magic:
            next_pos = data.find(dtb_magic, pos)
            if next_pos == -1:
                break
            pos = next_pos
        if pos + 8 > len(data):
            break
        totalsize = struct.unpack(">I", data[pos+4:pos+8])[0]
        if totalsize <= 0 or pos + totalsize > len(data):
            break
        dtb_slice = data[pos:pos+totalsize]
        dtb_list.append((pos, totalsize, dtb_slice))
        pos += totalsize

    print(f"Found {len(dtb_list)} DTBs in {input_file}")

    chosen_dtb = None
    chosen_idx = -1

    # Priority 1: Match strictly 'PL2 dvt' and r69338 panel
    for i, (p, sz, d) in enumerate(dtb_list):
        has_pl2_dvt = (b"PL2 dvt" in d or b"sdm630-mtp-pl2-dvt" in d)
        has_r69338 = b"fih,mdss_dsi_r69338_1080p_video" in d
        desc = f"DTB #{i+1} (offset {p}, {sz} bytes):"
        if has_pl2_dvt: desc += " [PL2 dvt]"
        if has_r69338: desc += " [r69338]"
        if b"B2N" in d: desc += " [B2N]"
        print(desc)
        if has_pl2_dvt and has_r69338 and chosen_dtb is None:
            chosen_dtb = d
            chosen_idx = i + 1
            print(f"==> Priority 1 Match: sdm630-mtp-pl2-dvt.dtb at DTB #{chosen_idx}")

    # Priority 2: Fallback to any DTB matching PL2 dvt
    if chosen_dtb is None:
        for i, (p, sz, d) in enumerate(dtb_list):
            if b"PL2 dvt" in d or b"sdm630-mtp-pl2-dvt" in d:
                chosen_dtb = d
                chosen_idx = i + 1
                print(f"==> Priority 2 Fallback: 'PL2 dvt' at DTB #{chosen_idx}")
                break

    # Priority 3: Fallback to any DTB with r69338
    if chosen_dtb is None:
        for i, (p, sz, d) in enumerate(dtb_list):
            if b"fih,mdss_dsi_r69338_1080p_video" in d:
                chosen_dtb = d
                chosen_idx = i + 1
                print(f"==> Priority 3 Fallback: 'r69338' at DTB #{chosen_idx}")
                break

    if chosen_dtb is None:
        print("ERROR: Could not locate appropriate PL2 DTB!")
        sys.exit(1)

    with open(out_dtb_only, "wb") as f:
        f.write(chosen_dtb)
    print(f"Saved isolated DTB #{chosen_idx} to {out_dtb_only} ({len(chosen_dtb)} bytes)")

    isolated_kernel = kernel_img + chosen_dtb
    with open(out_kernel_dtb, "wb") as f:
        f.write(isolated_kernel)
    print(f"Saved isolated kernel+DTB to {out_kernel_dtb} ({len(isolated_kernel)} bytes)")

if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "Image.gz-dtb"
    out_k = sys.argv[2] if len(sys.argv) > 2 else "Image.gz-dtb-isolated"
    out_d = sys.argv[3] if len(sys.argv) > 3 else "sdm630-mtp-pl2-dvt.dtb"
    isolate_dtb(inp, out_k, out_d)
