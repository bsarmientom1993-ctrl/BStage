#!/usr/bin/env python3
"""
BSplayer Package Tool (.bsp)
============================
Creates, validates, and unpacks single-file .bsp packages for BSplayer.
A .bsp file is a structured ZIP container containing:
- project.json (descriptor with track routing, markers, bpm, lyrics, video, midi cues)
- *.wav (48kHz 24-bit PCM mono stems)
- *.mid (MIDI cue events for pedals/synths/DMX lights)
- *.mp4 / *.mov (Synchronized background video)
- *.lrc (LRC lyrics with timestamped sync)
"""

import sys
import os
import json
import zipfile
import argparse
from pathlib import Path

def create_bsp_from_folder(source_dir: Path, output_file: Path = None, remove_source: bool = False) -> Path:
    source_dir = Path(source_dir).resolve()
    if not source_dir.is_dir():
        raise ValueError(f"Source folder '{source_dir}' does not exist.")

    project_json = source_dir / "project.json"
    if not project_json.exists():
        raise ValueError(f"No project.json found in '{source_dir}'.")

    with open(project_json, "r", encoding="utf-8") as f:
        meta = json.load(f)

    song_id = meta.get("id", source_dir.name)
    title = meta.get("title", source_dir.name)

    if output_file is None:
        output_file = source_dir.parent / f"{song_id}.bsp"
    else:
        output_file = Path(output_file).resolve()

    print(f"[BSP Packager] Packaging song '{title}' ({song_id}) into {output_file.name}...")

    # Write into temporary zip then rename to .bsp
    temp_zip = output_file.with_suffix(".tmp.zip")
    
    with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        # 1. Add project.json
        z.write(project_json, arcname="project.json")
        print(f"  + Added: project.json")

        # 2. Add all audio stems, midi, video, lrc
        for item in source_dir.rglob("*"):
            if item.is_file() and item.name != "project.json" and not item.name.endswith(".bsp"):
                rel_path = item.relative_to(source_dir)
                z.write(item, arcname=str(rel_path).replace("\\", "/"))
                size_mb = item.stat().st_size / (1024 * 1024)
                print(f"  + Added: {rel_path} ({size_mb:.2f} MB)")

    # Atomic rename to .bsp
    if output_file.exists():
        output_file.unlink()
    temp_zip.rename(output_file)

    total_mb = output_file.stat().st_size / (1024 * 1024)
    print(f"[BSP Packager] SUCCESS: Created '{output_file}' ({total_mb:.2f} MB)")

    if remove_source:
        import shutil
        shutil.rmtree(source_dir)
        print(f"[BSP Packager] Cleaned up staging directory: {source_dir}")

    return output_file

def inspect_bsp(bsp_file: Path):
    bsp_file = Path(bsp_file).resolve()
    if not bsp_file.is_file():
        print(f"Error: {bsp_file} does not exist.")
        return

    with zipfile.ZipFile(bsp_file, "r") as z:
        names = z.namelist()
        print(f"\n==================================================")
        print(f"  BSP Package: {bsp_file.name}")
        print(f"  File size: {bsp_file.stat().st_size / (1024 * 1024):.2f} MB")
        print(f"==================================================")
        
        if "project.json" in names:
            with z.open("project.json") as f:
                data = json.load(f)
                print(f"  Title:     {data.get('title')}")
                print(f"  Artist:    {data.get('artist')}")
                print(f"  BPM:       {data.get('bpm')}")
                print(f"  Duration:  {data.get('duration_seconds')}s")
                print(f"  Tracks:    {len(data.get('tracks', []))}")
                for trk in data.get("tracks", []):
                    ch = trk.get("output_channel", 0) + 1
                    click = " [CLICK]" if trk.get("is_click") else ""
                    print(f"    - {trk.get('name')}: Out {ch} (Vol: {trk.get('volume')}){click}")
                print(f"  Markers:   {len(data.get('markers', []))}")
                print(f"  Lyrics:    {len(data.get('lyrics', []))} lines")
                if data.get("video_file"):
                    print(f"  Video:     {data.get('video_file')}")
                if data.get("midi_file"):
                    print(f"  MIDI:      {data.get('midi_file')}")
        else:
            print("  [WARNING] No project.json found in package!")

        print(f"\n  Package Contents ({len(names)} files):")
        for item in z.infolist():
            print(f"    - {item.filename} ({item.file_size / (1024*1024):.2f} MB)")
        print(f"==================================================\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BSplayer Package (.bsp) Tool")
    parser.add_argument("path", help="Folder to pack or .bsp file to inspect/unpack")
    parser.add_argument("-o", "--output", help="Output .bsp file path", default=None)
    parser.add_argument("--inspect", action="store_true", help="Inspect contents of .bsp file")
    parser.add_argument("--remove-source", action="store_true", help="Delete source folder after packing")

    args = parser.parse_args()
    target = Path(args.path)

    if args.inspect or (target.is_file() and target.suffix.lower() == ".bsp"):
        inspect_bsp(target)
    elif target.is_dir():
        create_bsp_from_folder(target, args.output, args.remove_source)
    else:
        print(f"Error: Target '{target}' is not a valid folder or .bsp file.")
