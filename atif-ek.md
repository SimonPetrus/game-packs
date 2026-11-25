## NOTICE (özgün metin)

```
CouchSubs
Copyright (C) 2026 Sinan Yorulmaz
https://github.com/yorulmazsinan/couchsubs

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU Affero General Public License version 3 (see LICENSE).

If you distribute a modified version or a fork of CouchSubs, the AGPL-3.0
requires you to, among other things:
  - keep this copyright notice and the license notices intact (section 4);
  - carry prominent notices stating that you modified the work and giving a
    relevant date, e.g. "Based on CouchSubs by Sinan Yorulmaz
    (https://github.com/yorulmazsinan/couchsubs), modified on YYYY-MM-DD"
    (section 5a);
  - license the whole work under the AGPL-3.0 and provide its source code
    (sections 5c and 6).
```

## THIRD-PARTY-NOTICES.md, "Game translation packs" bölümü (özgün metin)

## Game translation packs

The packs in `core/Sources/CouchSubsCore/Resources/packs` contain only hashed keys and Turkish text; no game text is
included. The Elden Ring pack (`elden-ring.json.gz`) was translated with Claude (Claude ile çevrildi) from the
English text dumps of the [Carian Archive](https://github.com/AsteriskAmpersand/Carian-Archive) (base game) and
[Impaler's Archive](https://github.com/ividyon/Impalers-Archive) (Shadow of the Erdtree). Its terminology follows the
glossary of the Elden Ring Turkish fan translation by mehmetkrn
([elden-ring-turkce-yama](https://github.com/mehmetkrn/elden-ring-turkce-yama), MIT License, Copyright (c) mehmetkrn).
ELDEN RING is a trademark of FromSoftware, Inc. and BANDAI NAMCO Entertainment Inc.

The Death Stranding Director's Cut pack (`death-stranding-directors-cut.json.gz`) was translated with Claude (Claude ile
çevrildi) from the fan-made English transcript at
[Game Scripts Wiki](https://game-scripts-wiki.blogspot.com/2019/12/death-stranding-full-transcript.html); its terms
follow the Death Stranding 2 pack. DEATH STRANDING is a trademark of Kojima Productions Co., Ltd. / Sony Interactive
Entertainment LLC.

The Marvel's Spider-Man 2 pack (`marvels-spider-man-2.json.gz`) was translated with Claude (Claude ile çevrildi) from
the English [Marvel's Spider-Man 2 script](https://marvels-spider-man.fandom.com/wiki/Marvel%27s_Spider-Man_2_script)
and [menu transcript](https://marvels-spider-man.fandom.com/wiki/Marvel%27s_Spider-Man_2_menu_transcript) on the
Marvel's Spider-Man Wiki (Fandom, text under [CC BY-SA](https://creativecommons.org/licenses/by-sa/3.0/), by its
contributors), and from English lines CouchSubs users read on screen (shared subtitle pool). Marvel's Spider-Man 2 is
a trademark of Marvel and Sony Interactive Entertainment LLC.

## Grand Theft Auto VI ek paketleri (`katki/gta-6.json.gz`, `ek/gta-6-ar.json.gz`)

`gta-6` paketine `katki/gta-6.json.gz` satırları eklenir; ortak satırlarda bu paketin çevirisi kullanılır, değer başındaki
ve cümle aralarındaki dil etiketleri ("İspanyolca: …") ayıklanır. `ek/gta-6-ar.json.gz` Arapça pakettir (`v1/packs-ar`);
dil etiketleri ayıklanmıştır. İki paketin kaynağı (paketlerin `source` alanı, özgün hâliyle):

```
GameTranslator, Codex (gpt-6.2-sol), 2026-11-22; English text: GTA 6 Xbox 1.0.2.1 dump
```
