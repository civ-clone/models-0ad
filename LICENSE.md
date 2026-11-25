# Licence

This repository holds two kinds of work under two licences.

## The models: CC BY-SA 3.0

`models/` and `manifest.json` are adapted from the art of [0 A.D.](https://play0ad.com/), Copyright © 2009
[Wildfire Games](https://www.wildfiregames.com/). They're licensed under the Creative Commons Attribution-ShareAlike 3.0
licence: https://creativecommons.org/licenses/by-sa/3.0/

I made these changes, which are under the same licence:
- **Variants:** of each unit's variants, only the first of each kind is used (its clothes, face, shield and so on).
- **Pose:** each unit is posed as it stands still, as its idle animation's first frame has it. Each tree stands as
  it's modelled.
- **Parts:** its parts and what it carries are put together in one model. A part with no place on it to go (the
  onager's stone, which it holds only as it throws) is left out.
- **Format:** it's converted from COLLADA to glTF, its up axis turned.
- **Textures:** only the base colour textures are kept, without their normal and specular maps. They're halved till
  no side is over 128 px (256 px for the trees), and packed into an atlas, with the rest of the atlas in their mean
  colour. Where a part's texture coordinates reach past its texture's edge, as the beech's leaves do, they're stopped
  at it, so less of the texture shows on those parts.
- **Colours:** the colour a part is tinted by its actor (`objectcolor`, such as hair) is baked into its texture. The
  alpha is used as the mask for its owner's colour, as 0 A.D. uses it, and made solid everywhere else.
  What 0 A.D. blends as see-through (`basic_trans`: units' tails and manes, and the trees, leaves and trunks) is cut
  out where it's less than half solid.

You may use, change and share them, for any purpose, if you:
- credit Wildfire Games as the original author, with a link to https://www.wildfiregames.com/ and to the licence;
- share what you make from them under the same licence.

A credit you can copy:

> Copyright (C) 2009 Wildfire Games. Adapted from 0 A.D. by Wildfire Games (https://www.wildfiregames.com/), CC BY-SA
> 3.0 (https://creativecommons.org/licenses/by-sa/3.0/): posed, put together, converted and atlased by dom111.

0 A.D.'s own notice for its art, which covers these, is in [NOTICE-0AD.txt](NOTICE-0AD.txt) as it is. That includes
what it says of the textures derived from CGTextures' material.

## The tools: MIT

`tools/`, `roster.json` (what's built, and how), and the files about the repository (`README.md`, `LICENSE.md`,
`package.json`, `.github/`, `.gitignore`, `.gitattributes`) are mine:

MIT License

Copyright (c) 2026 dom111

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
