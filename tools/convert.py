"""convert.py <art_dir> <actor_rel> <out.glb> [--anim NAME|none] [--frame N] [--max N] [--report]

Turns one 0 A.D. actor (art/actors/<actor_rel>) into a static glTF binary, posed: its mesh and its props at their
points (nested), drawn from one texture atlas (and a second for what's see-through). Reads the files as data only
(XML, COLLADA, PNG, DDS), and only under <art_dir>.

- Variants: the first of each group, with `file=` includes merged in (deterministic).
- Pose: frame N (default 0) of the actor's first animation called NAME (default Idle), or the bind pose with `none`.
  The actor must have one called NAME; its props are posed by theirs, where they have one.
- Axes: each file's up axis turned to Z up, then the whole turned to glTF's Y up.
- The atlas: each part's base texture, halved till no side is over --max (default 128), and packed. Its alpha is the
  owner's colour's mask (rgb *= mix(colour, 1, a)) where the part's material is `player_trans*`, and solid elsewhere:
  an `objectcolor*` part's colour (the actor's <color>, hair) baked in by its own mask. The glTF material carries
  extras.playerColour.
- See-through parts (`basic_trans*`: tails, manes) go in a second atlas, cut out where their alpha is under a half.

It fails, writing nothing, where a file the actor names is missing, can't be read, or is still a Git LFS pointer, and
where it would draw nothing.
"""
import argparse
import hashlib
import os
import struct
import sys
import xml.etree.ElementTree as ET
import zlib

parser = argparse.ArgumentParser(description='Turns one 0 A.D. actor into a static glTF binary.')
parser.add_argument('art')
parser.add_argument('actor')
parser.add_argument('out')
parser.add_argument('--anim', default='Idle')
parser.add_argument('--frame', type=int, default=0)
parser.add_argument('--max', type=int, default=128)
parser.add_argument('--report', action='store_true')
parser.add_argument('--source', default='', help="the 0 A.D. commit the art is from, recorded in what's written")
OPTIONS = parser.parse_args()
ART = OPTIONS.art
ACTOR = OPTIONS.actor
OUT = OPTIONS.out
ANIM = OPTIONS.anim
FRAME = OPTIONS.frame
MAX = OPTIONS.max
ART_ROOT = os.path.realpath(ART)
# This converter, by its contents: recorded in what it writes, so a model built by another is known to be.
CONVERTER = hashlib.sha256(open(os.path.abspath(__file__), 'rb').read()).hexdigest()[:16]
# How deep props may sit in props, how many there may be in all, and how big a texture may be: what no unit comes near.
DEEPEST = 8
MOST_PROPS = 512
WIDEST = 8192

if not os.path.isdir(ART_ROOT):
    sys.exit(f'{ART}: no such directory')
if FRAME < 0 or MAX < 1:
    sys.exit('--frame must be 0 or more, and --max 1 or more')


def fail(message):
    """Stops, writing nothing."""
    sys.exit(f'{ACTOR}: {message}')


def readable(*parts):
    """A file under the art root that the actor names, or a failure: missing, outside it, or a Git LFS pointer."""
    path = under_art(*parts)
    if path is None:
        fail(f'{"/".join(parts)} is outside the art directory')
    if not os.path.isfile(path):
        fail(f'{"/".join(parts)} is missing')
    with open(path, 'rb') as f:
        if f.read(24).startswith(b'version https://git-lfs'):
            fail(f'{"/".join(parts)} is a Git LFS pointer: fetch the LFS files')
    return path


def under_art(*parts):
    """A path under the art root, or None for one that would leave it."""
    path = os.path.realpath(os.path.join(ART_ROOT, *parts))
    return path if path.startswith(ART_ROOT + os.sep) else None


REPORT = OPTIONS.report

# ---- matrices: row-major 4x4 lists, column vectors (M x v), as COLLADA writes them.

I4 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def mul(a, b):
    return [
        sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4))
        for r in range(4)
        for c in range(4)
    ]


def point(m, v):
    x, y, z = v
    return (
        m[0] * x + m[1] * y + m[2] * z + m[3],
        m[4] * x + m[5] * y + m[6] * z + m[7],
        m[8] * x + m[9] * y + m[10] * z + m[11],
    )


def vector(m, v):
    x, y, z = v
    return (
        m[0] * x + m[1] * y + m[2] * z,
        m[4] * x + m[5] * y + m[6] * z,
        m[8] * x + m[9] * y + m[10] * z,
    )


def floats(text):
    return [float(t) for t in (text or '').split()]


# Y up to Z up: (x, y, z) -> (x, -z, y).
Y_TO_Z = [1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1]

# ---- COLLADA


class Dae:
    cache = {}

    @classmethod
    def load(cls, path):
        if path not in cls.cache:
            cls.cache[path] = Dae(path)
        return cls.cache[path]

    def __init__(self, path):
        self.path = path
        root = ET.parse(path).getroot()
        self.ns = root.tag.split('}')[0] + '}'
        self.root = root
        up = root.find(self.q('asset/up_axis'))
        self.up = (up.text or 'Z_UP').strip() if up is not None else 'Z_UP'
        self.axis = Y_TO_Z if self.up == 'Y_UP' else I4
        self.by_id = {e.get('id'): e for e in root.iter() if e.get('id')}
        # The scene's nodes, with their parents.
        self.parent = {}
        self.nodes = []
        scene = root.find(self.q('library_visual_scenes/visual_scene'))
        if scene is not None:
            for node in scene.findall(self.q('node')):
                self._walk(node, None)

    def q(self, path):
        return '/'.join(self.ns + part for part in path.split('/'))

    def _walk(self, node, parent):
        self.parent[node] = parent
        self.nodes.append(node)
        for child in node.findall(self.q('node')):
            self._walk(child, node)

    def local(self, node):
        m = I4
        for child in node:
            tag = child.tag.replace(self.ns, '')
            values = floats(child.text)
            if tag == 'matrix':
                m = mul(m, values)
            elif tag == 'translate':
                x, y, z = values
                m = mul(m, [1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1])
            elif tag == 'scale':
                x, y, z = values
                m = mul(m, [x, 0, 0, 0, 0, y, 0, 0, 0, 0, z, 0, 0, 0, 0, 1])
            elif tag == 'rotate':
                import math

                x, y, z, angle = values
                c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
                t = 1 - c
                m = mul(
                    m,
                    [
                        t * x * x + c, t * x * y - s * z, t * x * z + s * y, 0,
                        t * x * y + s * z, t * y * y + c, t * y * z - s * x, 0,
                        t * x * z - s * y, t * y * z + s * x, t * z * z + c, 0,
                        0, 0, 0, 1,
                    ],
                )
        return m

    def world(self, node, posed=None):
        """The node's matrix in the scene, with posed local matrices by node name where given."""
        chain = []
        while node is not None:
            chain.append(node)
            node = self.parent[node]
        m = I4
        for n in reversed(chain):
            name = n.get('name') or n.get('sid') or n.get('id')
            local = posed.get(name) if posed else None
            m = mul(m, local if local is not None else self.local(n))
        return m

    def node_named(self, name):
        for n in self.nodes:
            if name in (n.get('name'), n.get('sid'), n.get('id')):
                return n
        return None

    def source(self, url):
        src = self.by_id[url.lstrip('#')]
        arr = src.find(self.q('float_array'))
        if arr is None:
            arr = src.find(self.q('Name_array'))
            return (arr.text or '').split()
        acc = src.find(self.q('technique_common/accessor'))
        stride = int(acc.get('stride', '1')) if acc is not None else 1
        values = floats(arr.text)
        return [values[i : i + stride] for i in range(0, len(values), stride)]

    def geometry(self, geom):
        """Triangles of a geometry: per-corner (position index, normal, uv), positions."""
        mesh = geom.find(self.q('mesh'))
        verts = mesh.find(self.q('vertices'))
        pos_url = next(i.get('source') for i in verts.findall(self.q('input')) if i.get('semantic') == 'POSITION')
        positions = self.source(pos_url)
        corners = []
        for prim in mesh:
            tag = prim.tag.replace(self.ns, '')
            if tag not in ('triangles', 'polylist', 'polygons'):
                continue
            inputs = prim.findall(self.q('input'))
            width = max(int(i.get('offset')) for i in inputs) + 1
            sources = {}
            for i in inputs:
                sem = i.get('semantic')
                if sem == 'VERTEX':
                    sources['V'] = (int(i.get('offset')), None)
                elif sem == 'NORMAL':
                    sources['N'] = (int(i.get('offset')), self.source(i.get('source')))
                elif sem == 'TEXCOORD' and 'T' not in sources:
                    sources['T'] = (int(i.get('offset')), self.source(i.get('source')))
            if tag == 'polygons':
                # A <p> for each polygon.
                polys = [[int(x) for x in e.text.split()] for e in prim.findall(self.q('p')) if e.text]
                p = [x for poly in polys for x in poly]
                counts = [len(poly) // width for poly in polys]
            else:
                p = [int(x) for x in prim.find(self.q('p')).text.split()]
            if tag == 'polylist':
                counts = [int(x) for x in prim.find(self.q('vcount')).text.split()]
            elif tag == 'triangles':
                counts = [3] * (len(p) // (3 * width))
            at = 0
            for count in counts:
                poly = []
                for k in range(count):
                    idx = p[(at + k) * width : (at + k + 1) * width]
                    v = idx[sources['V'][0]]
                    n = sources['N'][1][idx[sources['N'][0]]] if 'N' in sources else [0, 0, 1]
                    t = sources['T'][1][idx[sources['T'][0]]][:2] if 'T' in sources else [0, 0]
                    poly.append((v, tuple(n), tuple(t)))
                for k in range(1, count - 1):
                    corners += [poly[0], poly[k], poly[k + 1]]
                at += count
        return corners, [tuple(x[:3]) for x in positions]

    def posed_from_animation(self, frame):
        """Each animated node's local matrix at `frame`, by node name."""
        posed = {}
        for channel in self.root.iter(self.ns + 'channel'):
            target = channel.get('target', '')
            node_id = target.split('/')[0]
            node = self.by_id.get(node_id)
            if node is None:
                continue
            sampler = self.by_id[channel.get('source').lstrip('#')]
            out = next(i.get('source') for i in sampler.findall(self.q('input')) if i.get('semantic') == 'OUTPUT')
            values = self.source(out)
            if not values:
                continue
            if frame >= len(values):
                raise IndexError(f'frame {frame}: the animation has {len(values)}')
            m = values[frame]
            if len(m) == 16:
                posed[node.get('name') or node.get('sid') or node_id] = m
        return posed


# ---- actors


def actor_path(rel):
    return readable('actors', rel)


def merge(into, variant, including=()):
    """Folds a variant's settings into `into`, its `file=` include first."""
    inc = variant.get('file')
    if inc:
        if inc in including:
            fail(f'variants/{inc} includes itself')
        merge(into, ET.parse(readable('variants', inc)).getroot(), including + (inc,))
    for child in variant:
        if child.tag == 'mesh' and child.text:
            into['mesh'] = child.text.strip()
        elif child.tag == 'textures':
            for t in child.findall('texture'):
                into['textures'][t.get('name')] = t.get('file')
        elif child.tag == 'props':
            for prop in child.findall('prop'):
                into['props'][prop.get('attachpoint')] = prop.get('actor') or ''
        elif child.tag == 'animations':
            for a in child.findall('animation'):
                into['animations'].append((a.get('name'), a.get('file')))
        elif child.tag == 'color' and child.text:
            into['color'] = [int(x) / 255 for x in child.text.split()]


def actor(rel):
    root = ET.parse(actor_path(rel)).getroot()
    out = {'rel': rel, 'mesh': None, 'textures': {}, 'props': {}, 'animations': [], 'color': None, 'material': ''}
    for group in root.findall('group'):
        variants = group.findall('variant')
        if variants:
            merge(out, variants[0])
    mat = root.find('material')
    out['material'] = (mat.text or '').strip() if mat is not None else ''
    return out


# ---- images


def png(width, height, rgba):
    raw = b''.join(b'\x00' + bytes(rgba[y * width * 4 : (y + 1) * width * 4]) for y in range(height))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(raw, 9))
        + chunk(b'IEND', b'')
    )


def colour565(c):
    return (((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31)


def dds_decode(data):
    height, width = struct.unpack_from('<II', data, 12)
    if not 0 < width <= WIDEST or not 0 < height <= WIDEST:
        raise ValueError(f'{width}x{height}: no texture is that big')
    fourcc = data[84:88]
    if fourcc not in (b'DXT1', b'DXT3', b'DXT5'):
        raise ValueError(f'DDS {fourcc!r}, not DXT1, DXT3 or DXT5')
    rgba = bytearray(width * height * 4)
    block = 8 if fourcc == b'DXT1' else 16
    at = 128
    for by in range(0, height, 4):
        for bx in range(0, width, 4):
            b = data[at : at + block]
            at += block
            alphas = [255] * 16
            colour_at = 0
            if fourcc == b'DXT3':
                bits = int.from_bytes(b[0:8], 'little')
                alphas = [((bits >> (4 * i)) & 15) * 17 for i in range(16)]
                colour_at = 8
            elif fourcc == b'DXT5':
                a0, a1 = b[0], b[1]
                table = [a0, a1]
                if a0 > a1:
                    table += [((6 - i) * a0 + (i + 1) * a1) // 7 for i in range(6)]
                else:
                    table += [((4 - i) * a0 + (i + 1) * a1) // 5 for i in range(4)] + [0, 255]
                bits = int.from_bytes(b[2:8], 'little')
                alphas = [table[(bits >> (3 * i)) & 7] for i in range(16)]
                colour_at = 8
            c0, c1 = struct.unpack_from('<HH', b, colour_at)
            p0, p1 = colour565(c0), colour565(c1)
            if c0 > c1 or fourcc != b'DXT1':
                palette = [p0, p1, tuple((2 * x + y) // 3 for x, y in zip(p0, p1)), tuple((x + 2 * y) // 3 for x, y in zip(p0, p1))]
                transparent = None
            else:
                palette = [p0, p1, tuple((x + y) // 2 for x, y in zip(p0, p1)), (0, 0, 0)]
                transparent = 3
            bits = struct.unpack_from('<I', b, colour_at + 4)[0]
            for i in range(16):
                x, y = bx + i % 4, by + i // 4
                if x >= width or y >= height:
                    continue
                index = (bits >> (2 * i)) & 3
                r, g, bl = palette[index]
                a = 0 if index == transparent else alphas[i]
                o = (y * width + x) * 4
                rgba[o : o + 4] = bytes((r, g, bl, a))
    return width, height, rgba


def png_decode(data):
    """Width, height and RGBA bytes of a PNG: grey, RGB, palette, grey and alpha, or RGBA; 1 to 16 bits; interlaced
    (Adam7) or not."""
    at = 8
    idat = b''
    palette = None
    trns = None
    while at < len(data):
        length, kind = struct.unpack_from('>I4s', data, at)
        body = data[at + 8 : at + 8 + length]
        at += 12 + length
        if kind == b'IHDR':
            width, height, depth, colour, _, _, interlace = struct.unpack('>IIBBBBB', body)
        elif kind == b'PLTE':
            palette = [tuple(body[i : i + 3]) for i in range(0, len(body), 3)]
        elif kind == b'tRNS':
            trns = body
        elif kind == b'IDAT':
            idat += body
        elif kind == b'IEND':
            break
    if not 0 < width <= WIDEST or not 0 < height <= WIDEST:
        raise ValueError(f'{width}x{height}: no texture is that big')
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    # A grey or RGB image's one see-through colour, compared as samples are read (the high byte of 16 bits).
    grey_key = rgb_key = None
    if trns and colour == 0:
        grey_key = struct.unpack('>H', trns[:2])[0] >> (8 if depth == 16 else 0)
    elif trns and colour == 2:
        rgb_key = tuple(v >> (8 if depth == 16 else 0) for v in struct.unpack('>HHH', trns[:6]))
    bits = depth * channels
    step = max(1, bits // 8)
    # No more than its pixels can need, at 64 bits each and with an interlaced image's extra rows, whatever the stream
    #  says.
    raw = zlib.decompressobj().decompress(idat, 2 * height * ((width * 64 + 7) // 8 + 1) + 1024)
    rgba = bytearray(width * height * 4)
    passes = (
        [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]
        if interlace
        else [(0, 0, 1, 1)]
    )
    pos = 0

    def pixel(line, x):
        if depth < 8:
            per = 8 // depth
            byte = line[x // per]
            samples = [(byte >> (8 - depth * (x % per + 1))) & ((1 << depth) - 1)]
        else:
            width_bytes = depth // 8
            o = x * channels * width_bytes
            samples = [line[o + c * width_bytes] for c in range(channels)]
        if colour == 3:
            r, g, b = palette[samples[0]]
            return r, g, b, trns[samples[0]] if trns and samples[0] < len(trns) else 255
        if colour == 0:
            v = samples[0] * 255 // ((1 << depth) - 1) if depth < 8 else samples[0]
            return v, v, v, 0 if grey_key is not None and samples[0] == grey_key else 255
        if colour == 4:
            return samples[0], samples[0], samples[0], samples[1]
        if colour == 2:
            return samples[0], samples[1], samples[2], 0 if rgb_key == tuple(samples[:3]) else 255
        return tuple(samples)

    for x0, y0, dx, dy in passes:
        pw = (width - x0 + dx - 1) // dx
        ph = (height - y0 + dy - 1) // dy
        if pw <= 0 or ph <= 0:
            continue
        stride = (pw * bits + 7) // 8
        prev = bytearray(stride)
        for row in range(ph):
            kind = raw[pos]
            line = bytearray(raw[pos + 1 : pos + 1 + stride])
            pos += 1 + stride
            if kind == 1:
                for i in range(step, stride):
                    line[i] = (line[i] + line[i - step]) & 255
            elif kind == 2:
                for i in range(stride):
                    line[i] = (line[i] + prev[i]) & 255
            elif kind == 3:
                for i in range(stride):
                    left = line[i - step] if i >= step else 0
                    line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
            elif kind == 4:
                for i in range(stride):
                    a = line[i - step] if i >= step else 0
                    b = prev[i]
                    c = prev[i - step] if i >= step else 0
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
            prev = line
            y = y0 + row * dy
            for col in range(pw):
                x = x0 + col * dx
                o = (y * width + x) * 4
                rgba[o : o + 4] = bytes(pixel(line, col))
    return width, height, rgba


def image_rgba(rel):
    """A texture's width, height and RGBA: a failure where it's missing or can't be read."""
    if not rel:
        fail('a part has no base texture')
    data = open(readable('textures', 'skins', rel), 'rb').read()
    try:
        if data[:4] == b'DDS ':
            return dds_decode(data)
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return png_decode(data)
    except Exception as error:  # noqa: BLE001 - said, and the actor fails.
        fail(f'textures/skins/{rel}: {error}')
    fail(f'textures/skins/{rel}: neither DDS nor PNG')


def halve(width, height, rgba, weighted=False):
    """Half the size, each pixel the mean of four: by how solid each is (`weighted`), so what's see-through doesn't
    darken what isn't."""
    w, h = max(1, width // 2), max(1, height // 2)
    out = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            texels = [
                rgba[i : i + 4]
                for i in (
                    (min(height - 1, 2 * y + dy) * width + min(width - 1, 2 * x + dx)) * 4
                    for dy in (0, 1)
                    for dx in (0, 1)
                )
            ]
            alpha = sum(t[3] for t in texels)
            o = (y * w + x) * 4
            for c in range(3):
                if weighted and alpha > 0:
                    out[o + c] = (sum(t[c] * t[3] for t in texels) + alpha // 2) // alpha
                else:
                    out[o + c] = sum(t[c] for t in texels) // 4
            out[o + 3] = alpha // 4
    return w, h, out


# ---- building


class Builder:
    def __init__(self):
        # How many actors have been placed, the unit's own and its props'.
        self.placed = 0
        # Primitives by material key: positions, normals, uvs.
        self.prims = {}
        self.materials = {}
        self.tris = 0

    def add(self, key, material, corners_world):
        if not corners_world:
            if REPORT:
                print('    (no triangles)')
            return
        prim = self.prims.setdefault(key, [])
        self.materials[key] = material
        prim.extend(corners_world)
        self.tris += len(corners_world) // 3


def place(builder, rel, at, depth=0):
    """Adds actor `rel`'s mesh and its props, its model origin at `at` (a matrix in the unit's Z-up space)."""
    a = actor(rel)
    note = '  ' * depth + f'{rel}: mesh={a["mesh"]} base={a["textures"].get("baseTex")} material={a["material"]}'
    if REPORT:
        print(note)
    if depth > DEEPEST:
        fail(f'props nest more than {DEEPEST} deep, at {rel}')
    builder.placed += 1
    if builder.placed > MOST_PROPS:
        fail(f'more than {MOST_PROPS} props in all')
    dae = Dae.load(readable('meshes', a['mesh'])) if a['mesh'] else None
    posed = {}
    if dae is not None and ANIM != 'none':
        files = [f for name, f in a['animations'] if (name or '').lower() == ANIM.lower()]
        if files:
            try:
                posed = Dae.load(readable('animation', files[0])).posed_from_animation(FRAME)
            except IndexError as error:
                fail(f'animation/{files[0]}: {error}')
        elif depth == 0:
            fail(f'no {ANIM} animation: pose it with --anim none')
    if dae is not None:
        base = a['textures'].get('baseTex')
        material = {
            'texture': base,
            'player': a['material'].startswith('player_trans'),
            'object': a['color'] if a['material'].startswith('objectcolor') else None,
            'transparent': a['material'].startswith('basic_trans'),
        }
        key = (base, material['player'], tuple(material['object'] or ()), material['transparent'])
        for inst in dae.nodes:
            for ic in inst.findall(dae.q('instance_controller')):
                ctrl = dae.by_id[ic.get('url').lstrip('#')]
                skin = ctrl.find(dae.q('skin'))
                geom = dae.by_id[skin.get('source').lstrip('#')]
                corners, positions = dae.geometry(geom)
                bsm = floats(skin.find(dae.q('bind_shape_matrix')).text) if skin.find(dae.q('bind_shape_matrix')) is not None else I4
                joints_url = next(i.get('source') for i in skin.find(dae.q('joints')).findall(dae.q('input')) if i.get('semantic') == 'JOINT')
                ibm_url = next(i.get('source') for i in skin.find(dae.q('joints')).findall(dae.q('input')) if i.get('semantic') == 'INV_BIND_MATRIX')
                names = dae.source(joints_url)
                ibms = dae.source(ibm_url)
                vw = skin.find(dae.q('vertex_weights'))
                vinputs = {i.get('semantic'): (int(i.get('offset')), i.get('source')) for i in vw.findall(dae.q('input'))}
                weights = [w[0] for w in dae.source(vinputs['WEIGHT'][1])]
                vcount = [int(x) for x in vw.find(dae.q('vcount')).text.split()]
                v = [int(x) for x in vw.find(dae.q('v')).text.split()]
                width = max(o for o, _ in vinputs.values()) + 1
                # Each joint's skinning matrix: its world (posed) x its inverse bind x the bind shape.
                skinning = []
                for name, ibm in zip(names, ibms):
                    node = dae.node_named(name)
                    jw = dae.world(node, posed) if node is not None else I4
                    skinning.append(mul(mul(jw, ibm), bsm))
                influences = []
                at_v = 0
                for count in vcount:
                    pairs = []
                    for k in range(count):
                        pair = v[(at_v + k) * width : (at_v + k + 1) * width]
                        j = pair[vinputs['JOINT'][0]]
                        w = weights[pair[vinputs['WEIGHT'][0]]]
                        pairs.append((j, w))
                    at_v += count
                    influences.append(pairs)
                posed_pos = {}
                for index, p in enumerate(positions):
                    acc = [0.0, 0.0, 0.0]
                    total = 0.0
                    for j, w in influences[index]:
                        if j < 0:
                            m = bsm
                        else:
                            m = skinning[j]
                        x, y, z = point(m, p)
                        acc[0] += w * x
                        acc[1] += w * y
                        acc[2] += w * z
                        total += w
                    # Weighted by none: where its bind shape puts it.
                    posed_pos[index] = [c / total for c in acc] if total > 0 else list(point(bsm, p))
                out = []
                for vi, n, t in corners:
                    # The normal by the vertex's heaviest joint.
                    pairs = influences[vi]
                    j = max(pairs, key=lambda jw: jw[1])[0] if pairs else -1
                    m = skinning[j] if j >= 0 else bsm
                    world = mul(at, dae.axis)
                    out.append((point(world, posed_pos[vi]), vector(mul(world, m), n), t))
                builder.add(key, material, out)
            for ig in inst.findall(dae.q('instance_geometry')):
                geom = dae.by_id[ig.get('url').lstrip('#')]
                corners, positions = dae.geometry(geom)
                nw = mul(at, mul(dae.axis, dae.world(inst, posed)))
                builder.add(key, material, [(point(nw, positions[vi]), vector(nw, n), t) for vi, n, t in corners])
    for attach, prop in a['props'].items():
        if not prop:
            continue
        if attach == 'root' or dae is None:
            where = at
        else:
            node = dae.node_named('prop-' + attach)
            if node is None:
                node = dae.node_named('prop_' + attach)
            if node is None:
                if REPORT:
                    print('  ' * depth + f'  ! no point {attach}')
                continue
            where = mul(at, mul(dae.axis, dae.world(node, posed)))
        place(builder, prop, where, depth + 1)


def bake(material):
    """A part's texture as it goes in an atlas: RGBA, no side over MAX, its alpha the owner's colour's mask or solid
    (or, see-through, as it is), with an object colour baked in by its mask."""
    width, height, rgba = image_rgba(material['texture'])
    rgba = bytearray(rgba)
    while max(width, height) > MAX:
        width, height, rgba = halve(width, height, rgba, weighted=material['transparent'])
    if material['transparent']:
        return width, height, rgba
    colour = material['object']
    for i in range(0, len(rgba), 4):
        a = rgba[i + 3] / 255
        if colour:
            for c in range(3):
                rgba[i + c] = min(255, int(rgba[i + c] * (colour[c] + (1 - colour[c]) * a) + 0.5))
        if not material['player']:
            rgba[i + 3] = 255
    return width, height, rgba


def next_power(value):
    power = 1
    while power < value:
        power *= 2
    return power


def pack(images, pad, fill):
    """Lays `images` ({key: (w, h, rgba)}) out in shelves, tallest first, each with `pad` px of its own edges round
    it, on `fill` (RGBA): the atlas's size and RGBA, and each image's place (x, y of its own corner, w, h)."""
    order = sorted(images, key=lambda k: (-images[k][1], str(k)))
    area = sum((images[k][0] + 2 * pad) * (images[k][1] + 2 * pad) for k in order)
    width = next_power(max(int(area ** 0.5), max(images[k][0] + 2 * pad for k in order)))
    while True:
        places = {}
        x = y = shelf = 0
        for k in order:
            w, h, _ = images[k]
            if x + w + 2 * pad > width:
                x, y, shelf = 0, y + shelf, 0
            places[k] = (x + pad, y + pad, w, h)
            x += w + 2 * pad
            shelf = max(shelf, h + 2 * pad)
        height = next_power(y + shelf)
        if height <= width:
            break
        width *= 2
    atlas = bytearray(bytes(fill) * (width * height))
    for k, (px, py, w, h) in places.items():
        _, _, rgba = images[k]
        for ty in range(-pad, h + pad):
            sy = min(h - 1, max(0, ty))
            for tx in range(-pad, w + pad):
                sx = min(w - 1, max(0, tx))
                o = ((py + ty) * width + px + tx) * 4
                i = (sy * w + sx) * 4
                atlas[o : o + 4] = rgba[i : i + 4]
    return width, height, atlas, places


def write_glb(builder, path):
    bin_parts = []
    views = []
    accessors = []
    images = []
    textures = []
    materials = []
    primitives = []
    # Enough of each part's own edges round it that the smaller copies of the atlas a map far off is drawn with don't
    #  mix in much of what's beside it.
    pad = 8

    def push(data, target=None):
        while sum(len(b) for b in bin_parts) % 4:
            bin_parts.append(b'\x00')
        offset = sum(len(b) for b in bin_parts)
        bin_parts.append(data)
        view = {'buffer': 0, 'byteOffset': offset, 'byteLength': len(data)}
        if target:
            view['target'] = target
        views.append(view)
        return len(views) - 1

    # Z up to glTF's Y up: (x, y, z) -> (x, z, -y).
    def yup(p):
        return (p[0], p[2], -p[1])

    bounds = [[1e9, 1e9, 1e9], [-1e9, -1e9, -1e9]]
    atlas_bytes = 0
    for transparent in (False, True):
        keys = [k for k in builder.prims if builder.prims[k] and builder.materials[k]['transparent'] == transparent]
        if not keys:
            continue
        baked = {k: bake(builder.materials[k]) for k in keys}
        # The rest of the atlas in the parts' mean colour, solid where they are, so it doesn't darken their edges far
        #  off: see-through, too, where theirs is.
        texels = [(rgba, i) for _, _, rgba in baked.values() for i in range(0, len(rgba), 4 * 7)]
        count = max(1, len(texels))
        fill = [sum(rgba[i + c] for rgba, i in texels) // count for c in range(3)] + [0 if transparent else 255]
        width, height, atlas, places = pack(baked, pad, fill)
        image = png(width, height, atlas)
        atlas_bytes += len(image)
        if REPORT:
            print(f'  atlas {"see-through" if transparent else "solid"}: {width}x{height}, {len(image)} bytes, {len(keys)} parts')
        index = {}
        overshot = set()
        pos, nor, uv, ids = [], [], [], []
        for k in keys:
            px, py, w, h = places[k]
            for p, n, t in builder.prims[k]:
                p = yup(p)
                n = yup(n)
                length = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5 or 1
                n = (n[0] / length, n[1] / length, n[2] / length)
                # Within the part's own texture: a little over its edge is taken as its edge, and more is said.
                if (min(t) < -0.02 or max(t) > 1.02) and k not in overshot:
                    overshot.add(k)
                    print(f'  ! {k[0]}: drawn from past its texture\'s edge, which the atlas stops at', file=sys.stderr)
                u = min(1.0, max(0.0, t[0]))
                v = min(1.0, max(0.0, 1 - t[1]))
                t = ((px + u * w) / width, (py + v * h) / height)
                key = (tuple(round(c, 5) for c in p), tuple(round(c, 3) for c in n), tuple(round(c, 6) for c in t))
                if key not in index:
                    index[key] = len(pos)
                    pos.append(p)
                    nor.append(n)
                    uv.append(t)
                ids.append(index[key])
        # As stored: their bounds as the file's.
        pos = [struct.unpack('<3f', struct.pack('<3f', *p)) for p in pos]
        for p in pos:
            for i in range(3):
                bounds[0][i] = min(bounds[0][i], p[i])
                bounds[1][i] = max(bounds[1][i], p[i])
        count = len(pos)
        pa = push(b''.join(struct.pack('<3f', *p) for p in pos), 34962)
        accessors.append({
            'bufferView': pa, 'componentType': 5126, 'count': count, 'type': 'VEC3',
            'min': [min(p[i] for p in pos) for i in range(3)], 'max': [max(p[i] for p in pos) for i in range(3)],
        })
        na = push(b''.join(struct.pack('<3f', *n) for n in nor), 34962)
        accessors.append({'bufferView': na, 'componentType': 5126, 'count': count, 'type': 'VEC3'})
        ta = push(b''.join(struct.pack('<2f', *t) for t in uv), 34962)
        accessors.append({'bufferView': ta, 'componentType': 5126, 'count': count, 'type': 'VEC2'})
        big = count > 65535
        ia = push(b''.join(struct.pack('<I' if big else '<H', i) for i in ids), 34963)
        accessors.append({'bufferView': ia, 'componentType': 5125 if big else 5123, 'count': len(ids), 'type': 'SCALAR'})
        iv = push(image)
        images.append({'bufferView': iv, 'mimeType': 'image/png'})
        textures.append({'source': len(images) - 1, 'sampler': 0})
        mat = {
            'name': 'see-through' if transparent else 'solid',
            'pbrMetallicRoughness': {
                'baseColorTexture': {'index': len(textures) - 1},
                'metallicFactor': 0,
                'roughnessFactor': 0.85,
            },
            'extras': {},
        }
        if transparent:
            mat['alphaMode'] = 'MASK'
            mat['alphaCutoff'] = 0.5
            mat['doubleSided'] = True
        elif any(builder.materials[k]['player'] for k in keys):
            mat['extras']['playerColour'] = True
        materials.append(mat)
        primitives.append({
            'attributes': {'POSITION': len(accessors) - 4, 'NORMAL': len(accessors) - 3, 'TEXCOORD_0': len(accessors) - 2},
            'indices': len(accessors) - 1,
            'material': len(materials) - 1,
        })

    binary = b''.join(bin_parts)
    while len(binary) % 4:
        binary += b'\x00'
    # How far the model reaches across and how high from its origin, on the ground: for fitting it to its stand.
    extent = {
        'across': [round(bounds[0][0], 3), round(bounds[1][0], 3)],
        'along': [round(bounds[0][2], 3), round(bounds[1][2], 3)],
        'height': round(bounds[1][1], 3),
    }
    gltf = {
        'asset': {
            'version': '2.0',
            'generator': 'civ-clone 0 A.D. converter',
            'copyright': (
                'Copyright (C) 2009 Wildfire Games. '
                'Adapted from 0 A.D. by Wildfire Games (https://www.wildfiregames.com/), '
                'CC BY-SA 3.0 (https://creativecommons.org/licenses/by-sa/3.0/): '
                'posed, put together, converted and atlased by dom111'
            ),
        },
        'scene': 0,
        'scenes': [
            {
                'nodes': [0],
                'extras': {
                    'actor': ACTOR,
                    'pose': [ANIM, FRAME],
                    'atlas': MAX,
                    'source': OPTIONS.source,
                    'converter': CONVERTER,
                    'extent': extent,
                },
            }
        ],
        'nodes': [{'mesh': 0, 'name': ACTOR}],
        'meshes': [{'primitives': primitives}],
        'materials': materials,
        'samplers': [{'magFilter': 9729, 'minFilter': 9987, 'wrapS': 33071, 'wrapT': 33071}],
        'buffers': [{'byteLength': len(binary)}],
        'bufferViews': views,
        'accessors': accessors,
        'images': images,
        'textures': textures,
    }
    import json

    text = json.dumps(gltf, separators=(',', ':')).encode()
    while len(text) % 4:
        text += b' '
    # Written beside it and then put in its place, so a failure leaves what was there.
    with open(path + '.part', 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(text) + 8 + len(binary)))
        f.write(struct.pack('<II', len(text), 0x4E4F534A) + text)
        f.write(struct.pack('<II', len(binary), 0x004E4942) + binary)
    os.replace(path + '.part', path)
    return extent, atlas_bytes


builder = Builder()
place(builder, ACTOR, I4)
if builder.tris == 0:
    fail('nothing to draw')
extent, atlas_bytes = write_glb(builder, OUT)
print(f'{os.path.basename(OUT)}: {builder.tris} tris, {os.path.getsize(OUT)} bytes ({atlas_bytes} of atlas), extent {extent}')
