"""check.py : checks manifest.json against roster.json and models/, as CI runs it.

- The manifest is a set of models (schema 1, kind `models`, id `0ad-ancient`, with a name) under CC BY-SA 3.0, with the
  credit its licence asks for (`licence.attribution`), crediting Wildfire Games with a link, from the commit the
  roster names; at the roster's scale.
- Each model in the roster is in the manifest, from the actor, in the pose and at the scale the roster says, and no
  other is. Its file is the one the manifest's SHA-256 says, and records that it was built as the roster says: from that
  actor, pose, atlas size and commit, by tools/convert.py as it is now. (That's what the file says of itself: CI hasn't
  0 A.D.'s art to build it again.)
- Each file is a glTF 2 binary whose JSON and binary chunks are whole, and all of it, reading nothing from outside
  itself (no `uri`) and needing no extension, saying in its copyright
  that it's adapted from Wildfire Games' work under CC BY-SA 3.0. In it:
  - every index (scene, node, mesh, material, texture, sampler, image, buffer view, accessor) is in range, and every
    buffer view within the buffer; nodes are a mesh each, unmoved, with no children; accessors start at their views'
    starts, and views aren't strided;
  - each primitive is triangles: points as floats, finite; normals for each, finite and a unit long; texture
    coordinates for each, within 0 to 1; indices among the points, whole triangles, none with a corner twice; its
    positions' bounds as its accessor says;
  - each image is a PNG (and says so), 8-bit RGBA, its sides powers of two, its pixels all there;
  - its extent is as its points reach, rounded, and as the manifest says.
- Each model's name is one civ.one can serve it by: small letters, digits and hyphens.
- Each unit type is drawn by one model, the one the roster says, as is each plant (by the 3D map's kind, or a kind on a
  terrain of its own), and no file in models/ is left over.
"""
import hashlib
import json
import math
import re
import os
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
problems = []


def problem(text):
    problems.append(text)


class Bad(Exception):
    """What's wrong with a file, stopping its check."""


def in_range(name, what, index, items):
    if not isinstance(index, int) or not 0 <= index < len(items):
        raise Bad(f'{name}: {what} {index!r} is out of range')
    return items[index]


def check_glb(name, path, model):
    """What's wrong with the glTF binary at `path`, said as problems: its JSON, if it's whole enough to read."""
    data = open(path, 'rb').read()
    if len(data) < 28:
        raise Bad(f'{name}: too short to be a glTF binary')
    magic, version, length = struct.unpack_from('<III', data)
    if magic != 0x46546C67 or version != 2:
        raise Bad(f'{name}: not a glTF 2 binary')
    if length != len(data):
        raise Bad(f'{name}: says it is {length} bytes, but is {len(data)}')
    json_length, kind = struct.unpack_from('<II', data, 12)
    if kind != 0x4E4F534A or json_length % 4 or 20 + json_length + 8 > len(data):
        raise Bad(f'{name}: no whole JSON chunk')
    gltf = json.loads(data[20 : 20 + json_length])
    bin_length, kind = struct.unpack_from('<II', data, 20 + json_length)
    binary = data[28 + json_length : 28 + json_length + bin_length]
    if kind != 0x004E4942 or bin_length % 4 or len(binary) != bin_length:
        raise Bad(f'{name}: no whole binary chunk')
    if 28 + json_length + bin_length != len(data):
        raise Bad(f'{name}: there is more after its binary chunk')
    buffers = gltf.get('buffers', [])
    if len(buffers) != 1 or not 0 < buffers[0].get('byteLength', -1) <= bin_length or bin_length - buffers[0]['byteLength'] > 3:
        raise Bad(f'{name}: its buffer is not its binary chunk')
    buffer_length = buffers[0]['byteLength']
    # All in the file itself: nothing fetched from elsewhere, which its SHA-256 wouldn't cover.
    if 'uri' in buffers[0] or any('uri' in image for image in gltf.get('images', [])):
        raise Bad(f'{name}: it reads something from outside itself')
    if gltf.get('extensionsRequired') or gltf.get('extensionsUsed'):
        raise Bad(f'{name}: it needs extensions')

    copyright = gltf.get('asset', {}).get('copyright', '')
    for words in (
        'Wildfire Games',
        'https://www.wildfiregames.com/',
        'CC BY-SA 3.0',
        'https://creativecommons.org/licenses/by-sa/3.0/',
    ):
        if words not in copyright:
            problem(f'{name}: its copyright does not say {words}')

    views = gltf.get('bufferViews', [])
    for index, view in enumerate(views):
        in_range(name, 'buffer view buffer', view.get('buffer'), buffers)
        if view.get('byteOffset', 0) + view.get('byteLength', 0) > buffer_length:
            raise Bad(f'{name}: buffer view {index} runs past the buffer')
        if 'byteStride' in view:
            raise Bad(f'{name}: buffer view {index} is strided')
    accessors = gltf.get('accessors', [])
    sizes = {5126: (4, 'f'), 5125: (4, 'I'), 5123: (2, 'H')}
    widths = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3}

    def values(index, type_, kinds=(5126,)):
        accessor = in_range(name, 'accessor', index, accessors)
        if accessor.get('type') != type_ or accessor.get('componentType') not in kinds:
            raise Bad(f'{name}: accessor {index} is not a {type_} of a kind it should be')
        if accessor.get('byteOffset', 0) != 0 or accessor.get('normalized') or 'sparse' in accessor:
            raise Bad(f"{name}: accessor {index} doesn't start at its view's start, or isn't plain")
        view = in_range(name, 'accessor buffer view', accessor.get('bufferView'), views)
        size, code = sizes[accessor['componentType']]
        count = accessor['count'] * widths[type_]
        if count * size > view['byteLength']:
            raise Bad(f'{name}: accessor {index} is longer than its buffer view')
        return accessor, struct.unpack_from(f'<{count}{code}', binary, view.get('byteOffset', 0))

    scene = in_range(name, 'scene', gltf.get('scene', 0), gltf.get('scenes', []))
    if not scene.get('nodes'):
        raise Bad(f'{name}: its scene has nothing in it')
    for node in scene['nodes']:
        each = in_range(name, 'node', node, gltf.get('nodes', []))
        in_range(name, 'node mesh', each.get('mesh'), gltf.get('meshes', []))
        if set(each) - {'mesh', 'name'}:
            raise Bad(f'{name}: node {node} is moved, or has children')
    primitives = [p for mesh in gltf.get('meshes', []) for p in mesh.get('primitives', [])]
    if not primitives:
        raise Bad(f'{name}: nothing to draw')
    for image in gltf.get('images', []):
        view = in_range(name, 'image buffer view', image.get('bufferView'), views)
        png = binary[view.get('byteOffset', 0) : view.get('byteOffset', 0) + view['byteLength']]
        if image.get('mimeType') != 'image/png' or png[:8] != b'\x89PNG\r\n\x1a\n':
            raise Bad(f"{name}: an image is not a PNG, or doesn't say it is")
        at, idat, header = 8, b'', None
        while at + 12 <= len(png):
            length, kind = struct.unpack_from('>I4s', png, at)
            body = png[at + 8 : at + 8 + length]
            if struct.unpack_from('>I', png, at + 8 + length)[0] != zlib.crc32(kind + body) & 0xFFFFFFFF:
                raise Bad(f'{name}: an image\'s {kind.decode(errors="replace")} is not whole')
            if kind == b'IHDR':
                header = struct.unpack('>IIBBBBB', body)
            elif kind == b'IDAT':
                idat += body
            at += 12 + length
        if header is None or header[2:] != (8, 6, 0, 0, 0):
            raise Bad(f'{name}: an image is not 8-bit RGBA, not interlaced')
        width, height = header[:2]
        if width & (width - 1) or height & (height - 1):
            raise Bad(f'{name}: an image\'s sides are not powers of two')
        try:
            # No more than its pixels need, whatever the stream says.
            pixels = zlib.decompressobj().decompress(idat, height * (width * 4 + 1) + 1)
        except zlib.error as error:
            raise Bad(f'{name}: an image\'s pixels can\'t be read: {error}')
        if len(pixels) != height * (width * 4 + 1):
            raise Bad(f'{name}: an image hasn\'t all its pixels')
    for texture in gltf.get('textures', []):
        in_range(name, 'texture image', texture.get('source'), gltf.get('images', []))
        in_range(name, 'texture sampler', texture.get('sampler'), gltf.get('samplers', []))
    for material in gltf.get('materials', []):
        texture = material.get('pbrMetallicRoughness', {}).get('baseColorTexture', {}).get('index')
        in_range(name, 'material texture', texture, gltf.get('textures', []))

    reach = [[math.inf] * 3, [-math.inf] * 3]
    for primitive in primitives:
        in_range(name, 'material', primitive.get('material'), gltf.get('materials', []))
        if primitive.get('mode', 4) != 4:
            raise Bad(f'{name}: a primitive is not triangles')
        attributes = primitive.get('attributes', {})
        if set(attributes) != {'POSITION', 'NORMAL', 'TEXCOORD_0'}:
            raise Bad(f'{name}: a primitive has {sorted(attributes)}, not positions, normals and texture coordinates')
        position, points = values(attributes['POSITION'], 'VEC3')
        count = position['count']
        if count == 0 or not all(math.isfinite(v) for v in points):
            raise Bad(f'{name}: a primitive has no points, or a point is not a number')
        normal, normals = values(attributes['NORMAL'], 'VEC3')
        uv, uvs = values(attributes['TEXCOORD_0'], 'VEC2')
        if normal['count'] != count or uv['count'] != count:
            raise Bad(f'{name}: a primitive has normals or texture coordinates for some of its points and not others')
        for i in range(0, len(normals), 3):
            length = math.sqrt(sum(v * v for v in normals[i : i + 3]))
            if not math.isfinite(length) or abs(length - 1) > 0.01:
                raise Bad(f'{name}: a normal is not a unit long')
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in uvs):
            raise Bad(f'{name}: a texture coordinate is outside 0 to 1')
        for axis in range(3):
            along = points[axis::3]
            if [min(along), max(along)] != [position['min'][axis], position['max'][axis]]:
                problem(f'{name}: its positions\' bounds are not their min and max')
            reach[0][axis] = min(reach[0][axis], min(along))
            reach[1][axis] = max(reach[1][axis], max(along))
        _, indices = values(primitive.get('indices'), 'SCALAR', (5123, 5125))
        if not indices or len(indices) % 3 or max(indices) >= count:
            raise Bad(f'{name}: its indices are not whole triangles of its points')
        if any(len({indices[i], indices[i + 1], indices[i + 2]}) < 3 for i in range(0, len(indices), 3)):
            raise Bad(f'{name}: a triangle has a corner twice')

    extent = scene.get('extras', {}).get('extent')
    reached = {
        'across': [round(reach[0][0], 3), round(reach[1][0], 3)],
        'along': [round(reach[0][2], 3), round(reach[1][2], 3)],
        'height': round(reach[1][1], 3),
    }
    if extent != reached:
        problem(f'{name}: its extent {extent} is not as its points reach, {reached}')
    if extent != model.get('extent'):
        problem(f'{name}: extent {model.get("extent")} in the manifest, {extent} in the file')
    return gltf


roster = json.load(open(os.path.join(ROOT, 'roster.json')))
manifest = json.load(open(os.path.join(ROOT, 'manifest.json')))
source = roster['source']
converter = hashlib.sha256(open(os.path.join(ROOT, 'tools', 'convert.py'), 'rb').read()).hexdigest()[:16]

for key, expected in (('schema', 1), ('kind', 'models'), ('id', '0ad-ancient'), ('source', 'hosted')):
    if manifest.get(key) != expected:
        problem(f'manifest {key} is {manifest.get(key)!r}, not {expected!r}')

if not isinstance(manifest.get('name'), str) or not manifest['name']:
    problem('manifest has no name')

licence = manifest.get('licence', {})
if [licence.get('name'), licence.get('url')] != ['CC BY-SA 3.0', 'https://creativecommons.org/licenses/by-sa/3.0/']:
    problem('manifest does not give CC BY-SA 3.0 as its licence')
attribution = licence.get('attribution', '') if isinstance(licence.get('attribution'), str) else ''
for words in ('Wildfire Games', 'https://www.wildfiregames.com/', 'CC BY-SA 3.0', 'https://creativecommons.org/licenses/by-sa/3.0/'):
    if words not in attribution:
        problem(f'manifest attribution does not say {words}')

credited = [credit for credit in manifest.get('credits', []) if credit.get('author') == 'Wildfire Games']
if not credited or not credited[0].get('url') or not credited[0].get('licence', {}).get('url'):
    problem('manifest does not credit Wildfire Games with a link and the licence')
elif credited[0].get('from') != f"{source['repository']} at {source['commit']}":
    problem(f'manifest credits {credited[0].get("from")}, roster names {source["repository"]} at {source["commit"]}')

if manifest.get('scale') != roster.get('scale'):
    problem(f'manifest scale {manifest.get("scale")}, roster {roster.get("scale")}')

models = manifest.get('models', {})

for name, entry in roster['models'].items():
    model = models.get(name)
    if model is None:
        problem(f'{name}: in roster.json, not in manifest.json')
        continue
    pose = entry.get('pose', ['Idle', 0])
    if model.get('from') != {'actor': entry['actor'], 'pose': pose}:
        problem(f'{name}: manifest says it is from {model.get("from")}, roster says {entry["actor"]} in {pose}')
    if model.get('scale') != entry.get('scale'):
        problem(f'{name}: scale {model.get("scale")} in the manifest, {entry.get("scale")} in the roster')
    if model.get('file') != f'models/{name}.glb':
        problem(f'{name}: its file is {model.get("file")}, not models/{name}.glb')
        continue
    path = os.path.join(ROOT, model['file'])
    if not os.path.exists(path):
        problem(f'{name}: {model["file"]} is missing')
        continue
    if hashlib.sha256(open(path, 'rb').read()).hexdigest() != model.get('sha256'):
        problem(f'{name}: {model["file"]} is not the file the manifest says')
    try:
        gltf = check_glb(name, path, model)
    except (Bad, KeyError, TypeError, ValueError, struct.error) as error:
        problem(str(error) if isinstance(error, Bad) else f'{name}: {model["file"]} can\'t be read: {error!r}')
        continue
    built = gltf['scenes'][gltf.get('scene', 0)].get('extras', {})
    if [built.get(key) for key in ('actor', 'pose', 'atlas', 'source', 'converter')] != [
        entry['actor'],
        pose,
        entry.get('atlas', roster['atlas']),
        source['commit'],
        converter,
    ]:
        problem(f'{name}: {model["file"]} was built otherwise than roster.json says, or by another converter')

for name in models:
    if name not in roster['models']:
        problem(f'{name}: in manifest.json, not in roster.json')
    # As civ.one names a hosted set's files by its models' names: small letters, digits and hyphens.
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', name):
        problem(f'{name}: not a name civ.one can serve a model by (small letters, digits and hyphens)')

drawn_by = {}
grown_by = {}
for name, entry in roster['models'].items():
    for unit in entry.get('units', []):
        if unit in drawn_by:
            problem(f'unit {unit}: drawn by both {drawn_by[unit]} and {name} in roster.json')
        drawn_by.setdefault(unit, name)
    for plant in entry.get('plants', []):
        if plant in grown_by:
            problem(f'plant {plant}: drawn by both {grown_by[plant]} and {name} in roster.json')
        grown_by.setdefault(plant, name)

units = manifest.get('names', {}).get('unit', {})
if units != drawn_by:
    problem(f'manifest draws unit types {units}, roster says {drawn_by}')

plants = manifest.get('names', {}).get('plant', {})
if plants != grown_by:
    problem(f'manifest draws plants {plants}, roster says {grown_by}')

folder = os.path.join(ROOT, 'models')
files = {os.path.join('models', f) for f in os.listdir(folder)} if os.path.isdir(folder) else set()
for left in sorted(files - {model.get('file') for model in models.values()}):
    problem(f'{left}: no model in the manifest')

if problems:
    print('\n'.join(problems))
    sys.exit(1)

print(f'ok: {len(models)} models, {len(units)} unit types, {len(plants)} plants')
