#!/usr/bin/env python3
"""
Build script: packages all VFED Python source and weather cache data
into worker.js as VFS_SOURCE object.  Run from vfed-web/ directory.
"""

import os
import json

VFED_SRC = os.path.join(os.path.dirname(__file__), '..', 'vfed')
ROOT = os.path.join(os.path.dirname(__file__), '..')


def collect_sources():
    sources = {}
    for root, dirs, files in os.walk(VFED_SRC):
        for f in files:
            if f.endswith('.py'):
                path = os.path.join(root, f)
                rel = os.path.relpath(path, os.path.dirname(VFED_SRC))
                rel = rel.replace('\\', '/')
                with open(path, 'r', encoding='utf-8') as fh:
                    sources[rel] = fh.read()
    return sources


def collect_weather_cache():
    """Bundle weather cache CSVs so the worker never calls Open-Meteo.
    
    Maps local ``weather_cache/`` files into the virtual FS at
    ``tmp/weather_cache/{filename}`` — the exact path that both
    ``fetchWeatherToCache`` (JS) and ``_cache_path`` (Python) expect.
    """
    weather = {}
    cache_dir = os.path.join(ROOT, 'weather_cache')
    if not os.path.isdir(cache_dir):
        return weather
    for f in os.listdir(cache_dir):
        if f.endswith('.csv'):
            path = os.path.join(cache_dir, f)
            # VFS_SOURCE keys are relative; worker.js prepends '/'
            vfs_key = 'tmp/weather_cache/' + f
            with open(path, 'r', encoding='utf-8') as fh:
                weather[vfs_key] = fh.read()
    return weather


def main():
    print(f"Collecting Python sources from {VFED_SRC}...")
    sources = collect_sources()
    print(f"Found {len(sources)} Python files:")
    for p in sorted(sources):
        print(f"  {p}")

    print(f"\nCollecting weather cache CSVs...")
    weather_cache = collect_weather_cache()
    if weather_cache:
        total_kb = sum(len(v) for v in weather_cache.values()) / 1024
        print(f"Found {len(weather_cache)} weather CSV files ({total_kb:.0f} KB):")
        for p in sorted(weather_cache):
            print(f"  {p}")
        sources.update(weather_cache)
    else:
        print("No weather cache CSVs found.")

    # Read worker template
    template_path = os.path.join(os.path.dirname(__file__), 'worker.template.js')
    if not os.path.exists(template_path):
        print(f"Error: {template_path} not found!")
        return

    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()

    # Build sources object using JSON for proper escaping
    # We'll output: const VFS_SOURCE = { "path": "content", ... };
    sources_json = json.dumps(sources, ensure_ascii=False)
    # The JSON is an object, we just need to inject it
    worker_js = template.replace('{{SOURCES_JSON}}', sources_json)

    output_path = os.path.join(os.path.dirname(__file__), 'worker.js')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(worker_js)

    print(f"\nGenerated {output_path} ({len(worker_js)} chars)")


if __name__ == '__main__':
    main()