"""build.py <art_dir> [--only id,id] : builds models/*.glb and manifest.json from roster.json.

<art_dir> is `binaries/data/mods/public/art` in a checkout of 0 A.D. at the commit roster.json names, its Git LFS
files fetched. Each model is converted by convert.py, posed as roster.json says (the first frame of its Idle
animation unless it says otherwise), and the manifest says what each is, where it came from, and its file's SHA-256.
With --only, just those are built, and the rest are taken as they are, if they were built as the roster says.

Run it with `python3 -I`: it reads 0 A.D.'s files as data, and runs nothing from them.
"""
import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# A plant as the 3D map names it: a kind, as `conifer` or `deadTree`, or a kind on a terrain (`Jungle:broadleaf`).
PLANT = r'([A-Z][A-Za-z]*:)?[a-z][A-Za-z]*'
ROOT = os.path.dirname(HERE)

parser = argparse.ArgumentParser(description='Builds the models and the manifest from roster.json.')
parser.add_argument('art', help="0 A.D.'s binaries/data/mods/public/art, at the roster's commit")
parser.add_argument('--only', help='the models to build, by name, comma-separated')
options = parser.parse_args()

roster = json.load(open(os.path.join(ROOT, 'roster.json')))
source = roster['source']
only = options.only.split(',') if options.only else None

if not os.path.isdir(options.art):
    sys.exit(f'{options.art}: no such directory')

if only is not None:
    unknown = [name for name in only if name not in roster['models']]
    if unknown:
        sys.exit(f'not in roster.json: {", ".join(unknown)}')

drawn_by = {}
grown_by = {}
for name, entry in roster['models'].items():
    if not entry.get('units') and not entry.get('plants'):
        sys.exit(f'{name}: draws no unit and no plant in roster.json')
    for unit in entry.get('units', []):
        if unit in drawn_by:
            sys.exit(f'unit {unit}: drawn by both {drawn_by[unit]} and {name} in roster.json')
        drawn_by[unit] = name
    # The plants it draws, by the 3D map's kinds (`conifer`), or a kind on a terrain of its own (`Jungle:broadleaf`).
    for plant in entry.get('plants', []):
        if not re.fullmatch(PLANT, plant):
            sys.exit(f'plant {plant}: not a kind of plant (`conifer`), or one on a terrain (`Jungle:broadleaf`)')
        if plant in grown_by:
            sys.exit(f'plant {plant}: drawn by both {grown_by[plant]} and {name} in roster.json')
        grown_by[plant] = name

# The converter, by its contents, as it records itself in what it writes.
converter = hashlib.sha256(open(os.path.join(HERE, 'convert.py'), 'rb').read()).hexdigest()[:16]


def glb_json(path):
    """The JSON chunk of a glTF binary."""
    with open(path, 'rb') as f:
        magic, _, _ = struct.unpack('<III', f.read(12))
        if magic != 0x46546C67:
            raise ValueError(f'{path} is not a glTF binary')
        length, kind = struct.unpack('<II', f.read(8))
        return json.loads(f.read(length))


def pose_of(entry):
    return entry.get('pose', ['Idle', 0])


def atlas_of(entry):
    return entry.get('atlas', roster['atlas'])


models = {}

for name, entry in roster['models'].items():
    out = os.path.join(ROOT, 'models', f'{name}.glb')
    anim, frame = pose_of(entry)
    if only is None or name in only:
        result = subprocess.run(
            [
                sys.executable,
                '-I',
                os.path.join(HERE, 'convert.py'),
                options.art,
                entry['actor'],
                out,
                '--anim',
                anim,
                '--frame',
                str(frame),
                '--max',
                str(atlas_of(entry)),
                '--source',
                source['commit'],
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            sys.exit(f'{name}: {result.stderr.strip() or result.stdout.strip()}')
        print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
    elif not os.path.exists(out):
        sys.exit(f'{name}: models/{name}.glb is missing: build it')
    built = glb_json(out)['scenes'][0]['extras']
    # Taken as it is: it must have been built from the actor, in the pose and with the atlas the roster says, from the
    #  commit it names, by this converter.
    if [built.get(key) for key in ('actor', 'pose', 'atlas', 'source', 'converter')] != [
        entry['actor'],
        [anim, frame],
        atlas_of(entry),
        source['commit'],
        converter,
    ]:
        sys.exit(f'{name}: models/{name}.glb was built otherwise than roster.json says, or by another converter: build it')
    models[name] = {
        'file': f'models/{name}.glb',
        **({'scale': entry['scale']} if 'scale' in entry else {}),
        'sha256': hashlib.sha256(open(out, 'rb').read()).hexdigest(),
        'extent': built['extent'],
        'from': {'actor': entry['actor'], 'pose': [anim, frame]},
    }

licence = {'name': 'CC BY-SA 3.0', 'url': 'https://creativecommons.org/licenses/by-sa/3.0/'}
manifest = {
    'schema': 1,
    'kind': 'models',
    'id': '0ad-ancient',
    'name': '0 A.D.: ancient units',
    'source': 'hosted',
    # As it's shown wherever the set is: the credit CC BY-SA asks for.
    'licence': {
        **licence,
        'attribution': (
            'Copyright (C) 2009 Wildfire Games. '
            'Adapted from 0 A.D. by Wildfire Games (https://www.wildfiregames.com/), '
            'CC BY-SA 3.0 (https://creativecommons.org/licenses/by-sa/3.0/): '
            'posed, put together, converted and atlased by dom111.'
        ),
    },
    'credits': [
        {
            'work': source['name'],
            'author': source['author'],
            'url': source['url'],
            'licence': licence,
            'from': f"{source['repository']} at {source['commit']}",
        }
    ],
    # How big a model is drawn: the 3D map's squares to each of 0 A.D.'s units, a person as tall as the built-in set's.
    #  A tree is drawn by its height (`extent`), as tall as the map's own trees, not at this scale.
    'scale': roster['scale'],
    'models': models,
    'names': {
        'unit': {
            unit: drawn_by[unit] for unit in drawn_by
        },
        'plant': {
            plant: grown_by[plant] for plant in grown_by
        },
    },
}

with open(os.path.join(ROOT, 'manifest.json'), 'w') as f:
    f.write(json.dumps(manifest, indent=2) + '\n')

print(
    f'manifest.json: {len(models)} models, {len(manifest["names"]["unit"])} unit types, '
    f'{len(manifest["names"]["plant"])} plants'
)
