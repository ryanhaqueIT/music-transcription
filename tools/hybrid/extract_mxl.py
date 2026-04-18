#!/usr/bin/env python3
"""Extract MusicXML from all .mxl files in a directory."""
import sys
import zipfile
from pathlib import Path

out_dir = Path(sys.argv[1])
for mxl in out_dir.glob('*.mxl'):
    with zipfile.ZipFile(str(mxl), 'r') as z:
        for name in z.namelist():
            if name.endswith('.xml') and not name.startswith('META-INF'):
                content = z.read(name)
                out_path = out_dir / name.replace('/', '_')
                out_path.write_bytes(content)
                print(f"Extracted: {out_path.name} ({len(content)} bytes)")

print("\nFiles in output dir:")
for f in sorted(out_dir.iterdir()):
    print(f"  {f.name}: {f.stat().st_size} bytes")
