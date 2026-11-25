# models-0ad

Units and trees for [civ.one](https://civ.one)'s 3D map, converted from [0 A.D.](https://play0ad.com/)'s art by
[Wildfire Games](https://www.wildfiregames.com/), under
[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).

0 A.D.'s units are realistic and finely made, but they're all ancient: soldiers, ships and siege engines up to the
Roman era. So this set covers the early units, and the 3D map draws the rest with its own figures, or with other
sets. Its trees are as finely made, and few-sided enough to stand by the thousand in a forest: a pine, a beech, a
teak, a date palm and a dead tree.

## What's here

- **`models/*.glb`:** one glTF binary for each model, standing on its origin and facing `+z`. Each is posed as it
  stands still (the first frame of its idle animation, or as it's modelled where it has none), with what it carries,
  wears and rides on it. Each draws from a texture atlas, and from a second for what's see-through, such as a horse's
  tail.
- **The owner's colour:** where 0 A.D. paints a unit in its player's colour, the atlas's alpha is the mask. Colour is
  `rgb × mix(owner, white, alpha)`, as 0 A.D. does it, and the solid atlas's material says so (`extras.playerColour`).
  Everywhere else the alpha is solid. Load the atlas with its alpha as it is, not premultiplied, or the colour under the
  mask is lost.
- **`manifest.json`:** the set, as civ.one's library describes a set of models:
  - its licence, with the credit to show wherever it's used (`licence.attribution`), and its credits;
  - the scale it's drawn at, and any model's own where it isn't the set's;
  - each model's file and its SHA-256, how far it reaches (`extent`, in its own units), and its source;
  - which unit types each model draws (`names.unit`, by the engine's names for them);
  - which plants each model draws (`names.plant`), by the 3D map's kinds of plant: here the trees, `conifer`,
    `broadleaf`, `palm` and `deadTree`, or a kind on a terrain of its own, as `Jungle:broadleaf`, which is meant to be
    looked up first. A tree is meant to be drawn as tall as the map's own trees of its kind, by its height over its
    origin (`extent.height`), not at the set's scale. A tree stands on its origin, as 0 A.D. plants it, though the
    teak's and the dead tree's roots reach below it.
- **`roster.json`:** what's built:
  - the 0 A.D. commit it's built from;
  - each model's 0 A.D. actor;
  - the unit types it draws, each by one model, and the plants, each by one model;
  - a scale where it isn't the set's own, a pose where it isn't the first frame of its idle animation, and the
    largest a texture may be in its atlas (`atlas`) where it isn't the roster's.

  The set no longer draws `Warrior`, `Settlers`, `Knight`, `Explorer` or `Sail`. civ.one draws those with the models
  in [models-realistic-cc0](https://github.com/civ-clone/models-realistic-cc0), which fit Civilization's units better
  than the stand-ins here did: a javelin-thrower, a citizen, Roman heavy cavalry, a mounted scout and a knarr. Their
  models are in this repository's history, and the roster from then builds them again.

  The horseman and the chariot are drawn at three-quarters of the set's scale, close to the trader's own (`0.03`). The
  3D map draws units bigger than life, as a tabletop game's figures are, and at the set's own scale a horse towered
  over the later units' vehicles.
- **`tools/`:** the converter that builds them (`convert.py`, `build.py`) and the check CI runs (`check.py`).

## Building them again

The models are built from 0 A.D.'s art at the commit `roster.json` names, with its Git LFS files fetched. You only need
the art under `binaries/data/mods/public/art`. A model whose files are missing, or still LFS pointers, fails to build,
and nothing's written for it. Then:

```bash
python3 -I tools/build.py <0ad>/binaries/data/mods/public/art
python3 -I tools/check.py
```

The tools need only Python 3, with nothing to install. They read 0 A.D.'s files as data (XML, COLLADA, PNG, DDS) and
run nothing from them. Each model records the 0 A.D. commit it's from and the converter that built it, so a change to
either means building them all again. The same build makes the same files with the same zlib; another zlib may
compress the atlases differently, though their pixels are the same.

`convert.py` builds one model from one actor:
- **Variants:** it takes the first variant of each of the actor's groups.
- **Props:** it puts the actor's props at their points.
- **Pose:** it poses the skinned meshes as the animation says; a tree, which has none, stands as it's modelled
  (`none`).
- **Axes:** it turns each file's up axis to glTF's.
- **Atlas:** it packs each part's base texture into the atlas, halved till no side is over 128 px (256 for the
  trees, whose leaves are cut out of theirs, and thin out when halved further). A texture's coordinates are stopped
  at its edge: the beech's leaves reach past theirs, so less of its texture shows on them than in 0 A.D. Each part has 8 px
  of its own edges round it, and the rest of the atlas is the parts' mean colour, so the smaller copies a far-off map
  is drawn with don't darken their edges.

## Licence

- **The models and the manifest** (`models/`, `manifest.json`) are adapted from 0 A.D.'s art by Wildfire Games.
  They're under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/), as 0 A.D.'s art is. 0 A.D.'s own
  notice for its art directory is in [NOTICE-0AD.txt](NOTICE-0AD.txt), as it is. Anything made from them must credit
  Wildfire Games, with a link to https://www.wildfiregames.com/ and to the licence, and be shared under the same
  licence. Each file says so in its glTF `asset.copyright`.
- **The tools and the roster** (`tools/`, `roster.json`) are mine, under the MIT licence.

See [LICENSE.md](LICENSE.md).
