#!/usr/bin/env python3
"""Oyun ceviri paketlerini birlestirir: pool-<kimlik> (ek satirlar) + <kimlik> (asil) -> tek paket.

Yalniz standart kitaplik. Kullanim:
  python3 -I paket_birlestir.py --girdi KLASOR [--girdi ...] [--cikti KLASOR] [--surum N] [--v1]
  python3 -I paket_birlestir.py --denetle [--girdi ...] [--cikti ...]
  python3 -I paket_birlestir.py --kendini-sina
  python3 -I paket_birlestir.py --indir https://kaynak --kaynak kaynak --cikti yayin   (GitHub Actions)

--girdi birden cok verilebilir; ayni kimlik birden cok klasorde varsa ILK klasordeki kazanir.
--v1: ek olarak uygulamanin adres duzenini de yazar (GitHub Pages icin): Turkce paketler v1/packs (liste) ve
      v1/packs/<kimlik>; obur diller v1/packs-<dil> ve v1/packs-<dil>/<kimlik> (ana liste yalniz Turkce).
--paket-dili KIMLIK=DIL: paketi elle bir dile koyar; yoksa paketin "lang" alani, o da yoksa tr.
Cikti belirlenimcidir: sirali anahtarlar, gzip mtime=0, dosya adi yok, sabit sikistirma duzeyi.
"""
import argparse
import base64
import glob
import gzip
import hashlib
import io
import json
import os
import random
import re
import sys

VARSAYILAN_CIKTI = "yayin"
ATIF_EK = None  # --atif-ek ile verilen sabit atif metni dosyasi
# Havuz kimligi ana kimlikle ayni degilse acik eslesme (kimlik -> ana kimlik).
TAKMA = {"pool-gta-5": "gta-v", "pool-rdr-2": "red-dead-redemption-2"}
EK_SONEKI = " (ek satırlar)"
ANAHTAR = re.compile(r"^[0-9a-f]{16}$")
KIMLIK = re.compile(r"^[a-z0-9-]{1,64}$")  # uygulamanin PackStore.isSafeId kurali
# Paket dili: Turkce paketler ana listede (v1/packs, eski uygulamalar dahil), obur diller ayri agacta (v1/packs-<dil>).
# Eski uygulama listede dil bilmedigi icin ana listeye Turkce disi paket asla girmez. "lang" alani olmayan paket Turkcedir.
VARSAYILAN_DIL = "tr"
DIL_KODU = re.compile(r"^[a-z]{2,3}$")
DIL_ZORLA = {}  # --paket-dili kimlik=dil
# --katki: depoda sabit duran ek paketler (kimlik -> (yol, ham, json)). Ayni kimlikli uretilen pakete --ekle-eksik kurali
# uygulanir (ortakta katkinin cevirisi, dil etiketi soyma, konusmaci onegi uyumu). Kaynak guncellense de her kosuda
# yeniden uygulanir; boylece aynalama katkiyi ezmez.
KATKI = {}


def bloom_bits(uzunluk):
    """PackFuzzy.bits: uzunluga gore Bloom boyu (bit)."""
    b = 64
    while b < 256 and uzunluk * 3 > b:
        b *= 2
    return b


def gz_yaz(ham):
    tampon = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=tampon, compresslevel=9, mtime=0) as g:
        g.write(ham)
    return tampon.getvalue()


def json_bayt(nesne):
    return json.dumps(nesne, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha(b):
    return hashlib.sha256(b).hexdigest()


def oku(yol):
    with open(yol, "rb") as f:
        ham = f.read()
    return ham, json.loads(gzip.decompress(ham).decode("utf-8-sig"))


def dil_kodu(x):
    """Gecerli dil kodu, bossa None, gecersizse "?"."""
    if not isinstance(x, str) or not x.strip():
        return None
    x = x.strip().lower()
    return x if DIL_KODU.match(x) else "?"


def paket_dili(kimlik, d, liste_dili=None):
    """Paketin dili: --paket-dili > liste ya da dosyadaki Turkce disi dil > "tr". Gecersiz kod: None (hicbir listeye girmez).
    Liste ile dosya celisirse Turkce disi olan kazanir: kuskulu paket ana listeye girmesin."""
    if kimlik in DIL_ZORLA:
        return DIL_ZORLA[kimlik]
    adaylar = [c for c in (dil_kodu(liste_dili), dil_kodu(d.get("lang") if isinstance(d, dict) else None)) if c]
    if "?" in adaylar:
        return None
    tr_disi = [c for c in adaylar if c != VARSAYILAN_DIL]
    return tr_disi[0] if tr_disi else VARSAYILAN_DIL


def agac_adi(dil):
    return "packs" if dil == VARSAYILAN_DIL else "packs-" + dil


def dil_klasoru(hedef, dil):
    """Turkce: hedef klasorun kendisi (bugunku duzen); obur diller: hedef/packs-<dil>."""
    return hedef if dil == VARSAYILAN_DIL else os.path.join(hedef, agac_adi(dil))


def dillere_ayir(paketler, liste_dilleri=None):
    """{dil: {kimlik: paket}}; "tr" her zaman vardir (bos olabilir)."""
    gruplar = {VARSAYILAN_DIL: {}}
    for k in sorted(paketler):
        dil = paket_dili(k, paketler[k][2], (liste_dilleri or {}).get(k))
        if dil is None:
            print("ATLANDI (geçersiz dil kodu): " + k, file=sys.stderr)
            continue
        gruplar.setdefault(dil, {})[k] = paketler[k]
    return gruplar


def dil_sirasi(diller):
    return sorted(diller, key=lambda x: (x != VARSAYILAN_DIL, x))


def girdileri_tara(klasorler):
    """kimlik -> (yol, ham baytlar, json). Ilk klasor kazanir. Dosya adi kimliktir."""
    sonuc = {}
    for k in klasorler:
        for yol in sorted(glob.glob(os.path.join(k, "*.json.gz"))):
            kimlik = os.path.basename(yol)[: -len(".json.gz")]
            if kimlik in sonuc:
                continue
            ham, d = oku(yol)
            if not isinstance(d, dict) or not isinstance(d.get("entries"), dict):
                print("ATLANDI (paket degil): " + yol, file=sys.stderr)
                continue
            sonuc[kimlik] = (yol, ham, d)
    return sonuc


def eslestir(paketler):
    """pool paketlerini ana pakete eslestirir. Doner: {ana_kimlik: (havuz_kimligi, yontem)}, bagimsiz_havuzlar."""
    ana = {k: v for k, v in paketler.items() if not k.startswith("pool-")}
    basliklar = {}
    for k, (_, _, d) in ana.items():
        basliklar.setdefault((d.get("title") or k).strip().lower(), []).append(k)
    cift, yalniz = {}, []
    for k in sorted(paketler):
        if not k.startswith("pool-"):
            continue
        d = paketler[k][2]
        hedef = yontem = None
        if k[5:] in ana:
            hedef, yontem = k[5:], "kimlik"
        elif TAKMA.get(k) in ana:
            hedef, yontem = TAKMA[k], "takma ad tablosu"
        else:
            t = (d.get("title") or "")
            if t.endswith(EK_SONEKI):
                t = t[: -len(EK_SONEKI)]
            adaylar = basliklar.get(t.strip().lower(), [])
            if len(adaylar) == 1:
                hedef, yontem = adaylar[0], "baslik"
        if hedef is None or hedef in cift:
            yalniz.append(k)
        else:
            cift[hedef] = (k, yontem)
    return cift, yalniz


def tum_anahtarlar(d):
    """Uygulamanin 'order' dizisi: entries + segments anahtarlari (bos degerliler dahil), tekrarsiz, sirali."""
    return sorted(set(d.get("entries", {})) | set(d.get("segments", {})))


def fuzzy_coz(d):
    """Gecerli fuzzy -> {anahtar: (uzunluk, bloom baytlari)}; yoksa/bozuksa None (uygulama da yok sayar)."""
    fz = d.get("fuzzy")
    if not isinstance(fz, dict):
        return None
    try:
        mask = base64.b64decode(fz["mask"], validate=True)
        lens = base64.b64decode(fz["lengths"], validate=True)
        bl = base64.b64decode(fz["blooms"], validate=True)
    except Exception:
        return None
    sira = tum_anahtarlar(d)
    if fz.get("version") != 1 or fz.get("count") != len(sira) or len(mask) != (len(sira) + 7) // 8:
        return None
    if sum(bloom_bits(l) // 8 for l in lens) != len(bl):
        return None
    imza, i, ofs = {}, 0, 0
    for idx, k in enumerate(sira):
        if (mask[idx >> 3] >> (idx & 7)) & 1:
            if i >= len(lens):
                return None
            n = bloom_bits(lens[i]) // 8
            imza[k] = (lens[i], bl[ofs: ofs + n])
            ofs += n
            i += 1
    if i != len(lens):
        return None
    return imza


def fuzzy_yaz(sira, imza):
    mask = bytearray((len(sira) + 7) // 8)
    lens, bl = bytearray(), bytearray()
    for idx, k in enumerate(sira):
        if k in imza:
            mask[idx >> 3] |= 1 << (idx & 7)
            lens.append(imza[k][0])
            bl += imza[k][1]
    return {
        "version": 1,
        "count": len(sira),
        "mask": base64.b64encode(bytes(mask)).decode("ascii"),
        "lengths": base64.b64encode(bytes(lens)).decode("ascii"),
        "blooms": base64.b64encode(bytes(bl)).decode("ascii"),
    }


def dolu(v):
    return isinstance(v, str) and v.strip() != ""


def tablo_birlestir(ana, ek):
    """Ana kazanir; ana degeri bos/yoksa ek kullanilir. Doner: (tablo, cakisma_sayisi)."""
    cikti = dict(ana)
    cakisma = 0
    for k, v in ek.items():
        if k in ana and dolu(ana[k]):
            cakisma += 1
            continue
        cikti[k] = v
    return dict(sorted(cikti.items())), cakisma


def guvenli_mi(ana, ek):
    """Guvenle birlesmiyorsa neden metni, birlesirse None."""
    for ad, d in (("ana", ana), ("ek", ek)):
        if d.get("format") != 2:
            return ad + " paketin biçimi 2 değil"
        for t in ("entries", "segments"):
            if not isinstance(d.get(t, {}), dict):
                return ad + " paketin " + t + " yapısı sözlük değil"
            for k, v in d.get(t, {}).items():
                if not ANAHTAR.match(k) or not isinstance(v, str):
                    return ad + " paketin " + t + " içinde geçersiz anahtar/değer"
    if "fuzzy" in ana and fuzzy_coz(ana) is None:
        return "ana paketin bulanık imzası çözülemedi (uygulama da yok sayıyor); imzalar korunamaz"
    if "fuzzy" in ek and fuzzy_coz(ek) is None:
        return "ek paketin bulanık imzası çözülemedi"
    return None


# Konusmaci adlari: degerlerin basindaki "Ad: " oneki (1-3 sozcuk, her sozcuk buyuk harf + kucuk harfler, yalniz ASCII;
# basta 2-3 harflik buyuk harfli unvan olabilir: "DJ Pooh"). Yalniz geri kalani konusma gibi olan degerler sayilir (en az
# iki sozcuk ve cumle sonu isareti ya da en az dort sozcuk). Alan etiketleri ve Turkce rol/genel sozcukler (DUR) alinmaz.
# Uygulama alani "bilinen konusmaci" olarak kullanir; Runner/Core/GamePacks.swift PackSpeakers ayni kurali uygular.
KONUSMACI = re.compile(r"^((?:[A-Z]{2,3} )?[A-Z][a-z]+(?: [A-Z][a-z]+){0,2}): (.+)$", re.S)
KONUSMACI_ESIK = 8
KONUSMACI_EN_COK = 300
KONUSMACI_DUR = frozenset("""
adedi adet alici anchor barmen bilgi bilinmeyen boyut club destesi dil dinamik ebat galibiyet gardiyan gonderen hedef hesap
kasiyer kat kime kimden kingfishers konu kopya kreyolce language merkez mesaj mud no not offshore personel pilot polis
protestocu right rusty serseri silah sponsorlu tarih tezgahtar turist turistler unknown veznedar wing yazan yazar yem
yerel yerli yerliler
""".split())


def temiz_deger(v):
    """Uygulamanin GamePack.cleaned kurali: etiketler atilir, bosluklar teklenir, bas/son kirpilir."""
    if "<" in v:
        v = re.sub(r"<[^<>]{0,40}>", "", v)
        v = " ".join(p for p in v.split(" ") if p)
    return v.strip()


def konusmaci_oneki(v):
    """Degerin basindaki konusmaci adi (kurala uyuyorsa), yoksa None."""
    m = KONUSMACI.match(temiz_deger(v)) if isinstance(v, str) else None
    if not m:
        return None
    ad, kalan = m.group(1), m.group(2).strip()
    if len(ad.split(" ")) > 3 or any(s.lower() in KONUSMACI_DUR for s in ad.split(" ")):
        return None
    sozcuk = kalan.split()
    if len(sozcuk) < 2 or not (kalan[-1] in ".!?\u2026" or len(sozcuk) >= 4):
        return None
    return ad


def konusmaci_adlari(d):
    """Degerlerden konusmaci adlari: en az KONUSMACI_ESIK kez, siklik azalan sonra ada gore, en cok KONUSMACI_EN_COK."""
    sayac = {}
    for tablo in ("entries", "segments"):
        for v in d.get(tablo, {}).values():
            ad = konusmaci_oneki(v)
            if ad:
                sayac[ad] = sayac.get(ad, 0) + 1
    adlar = sorted((a for a, n in sayac.items() if n >= KONUSMACI_ESIK), key=lambda a: (-sayac[a], a))
    return adlar[:KONUSMACI_EN_COK]


def birlestir(ana, ek, kimlik, ana_baslik_yoksa):
    entries, c1 = tablo_birlestir(ana["entries"], ek["entries"])
    segments, c2 = tablo_birlestir(ana.get("segments", {}), ek.get("segments", {}))
    sira = sorted(set(entries) | set(segments) | set(tum_anahtarlar(ana)) | set(tum_anahtarlar(ek)))
    # Imza yalniz Ingilizce anahtara bagli (cevirisiyle degil): ana oncelikli, yoksa ek.
    imza = {}
    for kaynak in (ek, ana):
        c = fuzzy_coz(kaynak) if "fuzzy" in kaynak else None
        if c:
            imza.update(c)
    cikti = {
        "format": 2,
        "id": ana.get("id") or kimlik,
        "title": ana.get("title") or ana_baslik_yoksa,
    }
    kaynaklar = [s for s in (ana.get("source"), ("ek satırlar: " + ek["source"]) if ek.get("source") else None) if s]
    if kaynaklar:
        cikti["source"] = "; ".join(kaynaklar)
    cikti["entries"] = entries
    cikti["segments"] = segments
    if imza:
        cikti["fuzzy"] = fuzzy_yaz(sira, imza)
    adlar = konusmaci_adlari(cikti)
    if adlar:
        cikti["speakers"] = adlar
    return cikti, c1 + c2, (c1, c2)


def plan_yap(paketler):
    """Her cikti icin (kimlik, tur, dosya baytlari, json|None, bilgi) listesi + birlestirilemeyenler."""
    cift, yalniz = eslestir(paketler)
    birlesik_havuzlar = {h for h, _ in cift.values()}
    sonuc, ayri = [], []
    for kimlik in sorted(paketler):
        if kimlik in birlesik_havuzlar and kimlik.startswith("pool-"):
            continue
        yol, ham, d = paketler[kimlik]
        if kimlik in cift:
            havuz, yontem = cift[kimlik]
            neden = guvenli_mi(d, paketler[havuz][2])
            if neden:
                ayri.append((kimlik, havuz, neden))
                sonuc.append((kimlik, "ayri", ham, d, {}))
                sonuc.append((havuz, "ayri", paketler[havuz][1], paketler[havuz][2], {}))
                continue
            j, cak, (c1, c2) = birlestir(d, paketler[havuz][2], kimlik, kimlik)
            bayt = gz_yaz(json_bayt(j))
            bilgi = {"havuz": havuz, "yontem": yontem, "cakisma": cak, "cakisma_entries": c1, "cakisma_segments": c2,
                     "ana_satir": len(d["entries"]), "ek_satir": len(paketler[havuz][2]["entries"])}
            sonuc.append((kimlik, "birlesik", bayt, j, bilgi))
        else:
            sonuc.append((kimlik, "oldugu gibi", ham, d, {}))
    # Birlestirilen havuzlar sonuc listesinde yok; "ayri" ikilileri tekrar eklenmesin
    gorulen, tekil = set(), []
    for s in sonuc:
        if s[0] in gorulen:
            continue
        gorulen.add(s[0])
        tekil.append(s)
    return tekil, ayri


def atif_yaz(yol, cikti_paketler, paketler, birlesikler):
    satir = ["# Atıf ve lisans notları", "",
             "Bu klasördeki paketler yalnızca özetlenmiş anahtarlar (SHA-256) ve Türkçe metin içerir; oyun metni yoktur.",
             "Aşağıdaki kaynak satırları paket dosyalarının içindeki `source` alanından, atıf metinleri",
             "özgün hâliyle `atif-ek.md` dosyasından aktarılmıştır.", "",
             "## Paketlerin kaynağı (paketlerin `source` alanı)", ""]
    for kimlik, tur, _, d, bilgi in cikti_paketler:
        satir.append("- `%s` (%s): %s" % (kimlik, d.get("title", kimlik), d.get("source", "(kaynak belirtilmemiş)")))
        if tur == "birlesik":
            h = bilgi["havuz"]
            satir.append("  - ek satırlar `%s` paketinden birleştirildi; kaynağı: %s" % (h, paketler[h][2].get("source", "(yok)")))
    satir.append("")
    if ATIF_EK and os.path.isfile(ATIF_EK):
        satir.append(open(ATIF_EK, encoding="utf-8").read().rstrip("\n"))
    satir.append("")
    with open(yol, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(satir))


def onceki_surumler(klasor):
    try:
        with open(os.path.join(klasor, "index.json"), "rb") as f:
            return {p["id"]: p for p in json.loads(f.read())["packs"]}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def onceki_tum(hedef):
    """{dil: {kimlik: dizin girdisi}}: hedef/index.json (tr) ve hedef/packs-<dil>/index.json."""
    sonuc = {VARSAYILAN_DIL: onceki_surumler(hedef)}
    for yol in sorted(glob.glob(os.path.join(hedef, "packs-*"))):
        dil = os.path.basename(yol)[len("packs-"):]
        if os.path.isdir(yol) and DIL_KODU.match(dil):
            sonuc[dil] = onceki_surumler(yol)
    return sonuc


def katki_uygula(plan, dil):
    """Plandaki paketlere KATKI'yi --ekle-eksik kuralıyla uygular. Uygulanamazsa calisma durur (yayin degismez)."""
    sonuc = []
    for kimlik, tur, bayt, d, bilgi in plan:
        if kimlik in KATKI:
            kd = KATKI[kimlik][2]
            kdil = dil_kodu(kd.get("lang")) or VARSAYILAN_DIL
            if kdil != dil:
                sys.exit("KATKI UYGULANAMADI: %s katkısının dili (%s) paketin diliyle (%s) aynı değil" % (kimlik, kdil, dil))
            neden = guvenli_mi(d, kd)
            if neden:
                sys.exit("KATKI UYGULANAMADI: %s: %s" % (kimlik, neden))
            j, say, _, _ = ekle_eksik(d, kd)
            bilgi = dict(bilgi, katki_oncesi=d)
            print("  katkı %s: eklenen=%d ortak değişen=%d istisna=%d (kaynakla aynı konuşma: entries %d, segments %d) soyulan etiket=%d" % (
                kimlik, say["eklenen_anahtar"], say["ortak_degisen"], say["istisna"], say["kaynakla_ayni_entries"],
                say["kaynakla_ayni_segments"], say["soyulan_etiket"]))
            sonuc.append((kimlik, tur + "+katkı", gz_yaz(json_bayt(j)), j, bilgi))
        else:
            sonuc.append((kimlik, tur, bayt, d, bilgi))
    return sonuc


def uret_hedefe(paketler, hedef, onceki, ilk_surum, v1, liste_dilleri=None):
    """Paketleri dile gore hedef klasore yazar. tr: hedef/*.json.gz + hedef/index.json (+ v1/packs); obur dil:
    hedef/packs-<dil>/ (+ v1/packs-<dil>). onceki: {dil: {kimlik: girdi}}. Hedefteki eski paket dosyalari ve artik
    olmayan dil agaclari silinir. Doner: ({dil: dizin listesi}, butun plan, ayri)."""
    gruplar = dillere_ayir(paketler, liste_dilleri)
    os.makedirs(hedef, exist_ok=True)
    import shutil
    for kok in [hedef] + ([os.path.join(hedef, "v1")] if v1 else []):
        for yol in glob.glob(os.path.join(kok, "packs-*")):
            if os.path.isdir(yol) and os.path.basename(yol)[len("packs-"):] not in gruplar:
                shutil.rmtree(yol)
    dizinler, tum_plan, tum_ayri = {}, [], []
    for dil in dil_sirasi(gruplar):
        klasor = dil_klasoru(hedef, dil)
        plan, ayri = plan_yap(gruplar[dil])
        plan = katki_uygula(plan, dil)
        os.makedirs(klasor, exist_ok=True)
        for eski in glob.glob(os.path.join(klasor, "*.json.gz")):
            os.remove(eski)
        dizin = []
        for kimlik, tur, bayt, d, bilgi in plan:
            with open(os.path.join(klasor, kimlik + ".json.gz"), "wb") as f:
                f.write(bayt)
            h = sha(bayt)
            o = onceki.get(dil, {}).get(kimlik)
            # Surum: icerik ayniysa onceki surum, degistiyse bir fazlasi (belirlenimci); app yalniz esitlige bakar.
            surum = ilk_surum if not o else (o["version"] if o.get("sha256") == h else int(o["version"]) + 1)
            dizin.append({"id": kimlik, "title": d.get("title") or kimlik, "version": surum, "sha256": h,
                          "size": len(bayt), "entries": len(d["entries"]), "lang": dil})
            print("%-34s %-3s %-12s satır=%d boyut=%d%s" % (kimlik, dil, tur, len(d["entries"]), len(bayt),
                  (" ana=%d ek=%d çakışma=%d [%s]" % (bilgi["ana_satir"], bilgi["ek_satir"], bilgi["cakisma"], bilgi["yontem"])) if "ana_satir" in bilgi else ""))
        ind = json_bayt({"packs": dizin})
        with open(os.path.join(klasor, "index.json"), "wb") as f:
            f.write(ind)
        if v1:  # uygulamanin adresleri: GET /v1/<agac> (liste) ve /v1/<agac>/<kimlik> (paket)
            kok = os.path.join(hedef, "v1", agac_adi(dil))
            shutil.rmtree(kok, ignore_errors=True)
            os.makedirs(kok)
            with open(os.path.join(kok, "index.html"), "wb") as f:  # /v1/<agac>/ -> JSON (Pages dizin dosyasi)
                f.write(ind)
            for kimlik, _, bayt, _, _ in plan:
                with open(os.path.join(kok, kimlik), "wb") as f:
                    f.write(bayt)
        dizinler[dil] = dizin
        tum_plan += plan
        tum_ayri += ayri
    eksik = sorted(set(KATKI) - {x[0] for x in tum_plan})
    if eksik:
        print("UYARI: uygulanacak paketi olmayan katkı: " + ",".join(eksik))
    atif_yaz(os.path.join(hedef, "ATIF.md"), tum_plan, paketler, None)
    return dizinler, tum_plan, tum_ayri


def uret(args):
    paketler = girdileri_tara(args.girdi)
    for k in paketler:
        if not KIMLIK.match(k):
            sys.exit("Güvenli olmayan kimlik: " + k)
    dizinler, plan, ayri = uret_hedefe(paketler, args.cikti, onceki_tum(args.cikti), args.surum, args.v1)
    for kimlik, havuz, neden in ayri:
        print("BİRLEŞTİRİLEMEDİ: %s + %s -> %s" % (kimlik, havuz, neden))
    for dil in dil_sirasi(dizinler):
        klasor = dil_klasoru(args.cikti, dil)
        print("%s listesi (%s): %d paket, %d bayt" % (dil, agac_adi(dil), len(dizinler[dil]),
              sum(os.path.getsize(p) for p in glob.glob(os.path.join(klasor, "*.json.gz")))))


# ---------------------------------------------------------------- --indir (GitHub Actions icin)

class KaynakHatasi(Exception):
    pass


def http_al(url, zaman_asimi, etag=None, deneme=2, bekle=2.0):
    """GET; 304 -> (None, etag). Hata olursa en cok `deneme` kez yeniden dener, sonra KaynakHatasi."""
    import time
    import urllib.error
    import urllib.request
    son = None
    for sira in range(deneme + 1):
        istek = urllib.request.Request(url, headers={"User-Agent": "game-packs-updater", "Accept-Encoding": "identity"})
        if etag:
            istek.add_header("If-None-Match", etag)
        try:
            with urllib.request.urlopen(istek, timeout=zaman_asimi) as r:
                return r.read(), r.headers.get("ETag")
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return None, etag
            son = e
            if 400 <= e.code < 500 and e.code != 429:
                break
        except Exception as e:  # ag, zaman asimi
            son = e
        time.sleep(bekle * (sira + 1))
    raise KaynakHatasi("%s: %s" % (url, son))


def kaynak_indir(taban, klasor, bekle, zaman_asimi):
    """Kaynak index'ini alir, yalniz degisen paketleri indirir. Doner: (indirilen kimlikler, {kimlik: listedeki dil}).
    Hata -> KaynakHatasi. Gecersiz dil kodlu paket alinmaz."""
    import time
    taban = taban.rstrip("/")
    govde, _ = http_al(taban + "/v1/packs", zaman_asimi)
    try:
        liste = json.loads(govde)["packs"]
        assert isinstance(liste, list) and liste
        liste = [{"id": p["id"], "sha256": str(p["sha256"]).lower(), "size": int(p.get("size", 0)), "lang": p.get("lang")}
                 for p in liste]
    except Exception:
        raise KaynakHatasi("kaynak index'i bozuk")
    liste = [p for p in liste if KIMLIK.match(p["id"]) and re.fullmatch(r"[0-9a-f]{64}", p["sha256"])
             and dil_kodu(p["lang"]) != "?"]
    if not liste:
        raise KaynakHatasi("kaynak index'inde geçerli paket yok")
    os.makedirs(klasor, exist_ok=True)
    durum_yol = os.path.join(klasor, "durum.json")
    try:
        with open(durum_yol, encoding="utf-8") as f:
            durum = json.load(f)
    except (OSError, ValueError):
        durum = {}
    indirilen = []
    for p in liste:
        k = p["id"]
        yol = os.path.join(klasor, k + ".json.gz")
        eski = durum.get(k, {})
        yerel_ok = os.path.isfile(yol) and eski.get("sha256") == p["sha256"] and sha(open(yol, "rb").read()) == p["sha256"]
        if yerel_ok and (not p["size"] or p["size"] == os.path.getsize(yol)):
            continue
        time.sleep(bekle)
        veri, etag = http_al(taban + "/v1/packs/" + k, zaman_asimi, etag=eski.get("etag") if os.path.isfile(yol) else None)
        if veri is None:  # 304: yerel dosya gecerli; ozet yine de dogrulanir
            veri = open(yol, "rb").read()
        if sha(veri) != p["sha256"]:
            raise KaynakHatasi("%s: indirilen paketin sha256'sı index ile tutmuyor" % k)
        gzip.decompress(veri)  # bozuk gzip burada patlar
        gecici = yol + ".indiriliyor"
        with open(gecici, "wb") as f:
            f.write(veri)
        os.replace(gecici, yol)
        durum[k] = {"sha256": p["sha256"], "etag": etag, "lang": p["lang"]}
        indirilen.append(k)
    # kaynaktan kalkan paketlerin yerel kopyasi silinir (yayindan da kalkar; sayi kapisi ayrica korur)
    gecerli = {p["id"] for p in liste}
    for yol in glob.glob(os.path.join(klasor, "*.json.gz")):
        if os.path.basename(yol)[:-8] not in gecerli:
            os.remove(yol)
    durum = {k: v for k, v in durum.items() if k in gecerli}
    for p in liste:  # listedeki dil her kosuda yazilir (denetim de ayni dil ayrimini kullanir)
        durum.setdefault(p["id"], {})["lang"] = p["lang"]
    gecici = durum_yol + ".tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(durum, f, sort_keys=True)
    os.replace(gecici, durum_yol)
    return indirilen, {p["id"]: p["lang"] for p in liste}


def cikisa_yaz(degisti):
    yol = os.environ.get("GITHUB_OUTPUT")
    if yol:
        with open(yol, "a", encoding="utf-8") as f:
            f.write("degisti=%s\n" % ("true" if degisti else "false"))


def dizin_dosyalari(hedef):
    """{goreli yol: bayt}: tr ve obur dil listeleri (degisiklik karsilastirmasi icin)."""
    sonuc = {}
    for yol in [os.path.join(hedef, "index.json")] + sorted(glob.glob(os.path.join(hedef, "packs-*", "index.json"))):
        if os.path.isfile(yol):
            with open(yol, "rb") as f:
                sonuc[os.path.relpath(yol, hedef)] = f.read()
    return sonuc


def kapi_denetle(onceki, dizinler):
    """Guvenlik kapisi, her dil listesi icin ayri. Doner: sorun listesi."""
    sorun = []
    for dil in dil_sirasi(set(onceki) | set(dizinler)):
        o_dil, dizin = onceki.get(dil, {}), dizinler.get(dil, [])
        ad = agac_adi(dil)
        # Baska dil listesine tasinan paket (ör. ana listeye yanlislikla girmis ar paketi packs-ar'a) kayip sayilmaz.
        baska = {p["id"] for d2, l2 in dizinler.items() if d2 != dil for p in l2}
        tasinan = (set(o_dil) - {p["id"] for p in dizin}) & baska
        if tasinan:
            print("UYARI: %s listesinden başka dil listesine taşınan: %s" % (ad, ",".join(sorted(tasinan))))
        if o_dil and len(dizin) + len(tasinan) < len(o_dil):
            sorun.append("%s: paket sayısı azaldı: %d -> %d" % (ad, len(o_dil), len(dizin)))
        kayip = sorted(set(o_dil) - {p["id"] for p in dizin} - tasinan)
        if kayip:
            sorun.append("%s: önceki yayındaki paket(ler) kayboldu: %s" % (ad, ",".join(kayip)))
        for p in dizin:
            o = o_dil.get(p["id"])
            if o and p["entries"] < 0.8 * int(o.get("entries", 0)):
                sorun.append("%s: %s: satır sayısı %%80'in altına düştü (%s -> %d)" % (ad, p["id"], o.get("entries"), p["entries"]))
            if p.get("lang") != dil:
                sorun.append("%s: %s listede yanlış dilde" % (ad, p["id"]))
    return sorun


def indir_kipi(args):
    import shutil
    try:
        indirilen, liste_dilleri = kaynak_indir(args.indir, args.kaynak, args.bekle, args.zaman_asimi)
    except KaynakHatasi as e:
        print("UYARI: kaynak alınamadı, hiçbir şey değiştirilmedi: %s" % e)
        cikisa_yaz(False)
        return
    print("kaynaktan indirilen (değişen) paket: %d %s" % (len(indirilen), ",".join(indirilen)))
    paketler = girdileri_tara([args.kaynak] + (args.girdi_ek or []))
    onceki = onceki_tum(args.cikti)
    if getattr(args, "onceki_gerekli", False) and not onceki.get(VARSAYILAN_DIL):
        cikisa_yaz(False)
        sys.exit("YAYINLANMADI: önceki yayının listesi okunamadı (sürümler geri gidebilirdi)")
    yeni = args.cikti.rstrip("/") + ".yeni"
    shutil.rmtree(yeni, ignore_errors=True)
    dizinler, plan, ayri = uret_hedefe(paketler, yeni, onceki, args.surum, True, liste_dilleri)
    # Guvenlik kapilari (dil basina): bozuk kaynak yayini bozmasin
    sorun = kapi_denetle(onceki, dizinler)
    if sorun:
        shutil.rmtree(yeni, ignore_errors=True)
        cikisa_yaz(False)
        sys.exit("YAYINLANMADI (güvenlik kapısı): " + "; ".join(sorun))
    if any(onceki.values()) and dizin_dosyalari(yeni) == dizin_dosyalari(args.cikti):
        shutil.rmtree(yeni, ignore_errors=True)
        print("değişiklik yok")
        cikisa_yaz(False)
        return
    os.makedirs(args.cikti, exist_ok=True)
    for ad in os.listdir(args.cikti):
        yol = os.path.join(args.cikti, ad)
        shutil.rmtree(yol) if os.path.isdir(yol) else os.remove(yol)
    for ad in os.listdir(yeni):
        shutil.move(os.path.join(yeni, ad), os.path.join(args.cikti, ad))
    shutil.rmtree(yeni, ignore_errors=True)
    print("DEĞİŞİKLİK VAR: " + ", ".join("%s %d paket" % (agac_adi(d), len(dizinler[d])) for d in dil_sirasi(dizinler)))
    cikisa_yaz(True)


def liste_dilleri_oku(klasorler):
    """--indir onbellegindeki durum.json'dan kaynak listesinin dilleri (yoksa bos)."""
    sonuc = {}
    for k in klasorler:
        try:
            with open(os.path.join(k, "durum.json"), encoding="utf-8") as f:
                for kimlik, v in json.load(f).items():
                    if isinstance(v, dict) and kimlik not in sonuc:
                        sonuc[kimlik] = v.get("lang")
        except (OSError, ValueError):
            pass
    return sonuc


def denetle(args):
    paketler = girdileri_tara(args.girdi)
    gruplar = dillere_ayir(paketler, liste_dilleri_oku(args.girdi))
    hata = []
    ok = 0
    rnd = random.Random(20260123)
    v1 = os.path.isdir(os.path.join(args.cikti, "v1"))
    agaclar = {os.path.basename(y)[len("packs-"):] for y in glob.glob(os.path.join(args.cikti, "packs-*")) if os.path.isdir(y)}
    if agaclar - set(gruplar):
        hata.append("girdide olmayan dil ağacı var: %s" % sorted(agaclar - set(gruplar)))
    for dil in dil_sirasi(gruplar):
        grup = gruplar[dil]
        klasor = dil_klasoru(args.cikti, dil)
        cift, yalniz = eslestir(grup)
        plan = katki_uygula(plan_yap(grup)[0], dil)
        planlar = {x[0]: x for x in plan}
        try:
            with open(os.path.join(klasor, "index.json"), "rb") as f:
                ind = f.read()
            dizin = {p["id"]: p for p in json.loads(ind)["packs"]}
        except (OSError, ValueError, KeyError):
            hata.append("%s: liste okunamadı" % agac_adi(dil))
            continue
        havuzlar = {h for h, _ in cift.values()}
        beklenen = {k for k in grup if k not in havuzlar}
        if set(dizin) != beklenen:
            hata.append("%s: index.json kimlikleri beklenenle aynı değil: fark=%s" % (agac_adi(dil), sorted(set(dizin) ^ beklenen)))
        if any(p.get("lang") != dil for p in dizin.values()):
            hata.append("%s: listede başka dilde paket var" % agac_adi(dil))
        if v1:
            kok = os.path.join(args.cikti, "v1", agac_adi(dil))
            try:
                if open(os.path.join(kok, "index.html"), "rb").read() != ind:
                    hata.append("%s: v1 listesi index.json ile aynı değil" % agac_adi(dil))
                fazla = set(os.listdir(kok)) - set(dizin) - {"index.html"}
                if fazla:
                    hata.append("%s: v1 ağacında listede olmayan dosya: %s" % (agac_adi(dil), sorted(fazla)))
            except OSError:
                hata.append("%s: v1 ağacı eksik" % agac_adi(dil))
        for kimlik, p in sorted(dizin.items()):
            yol = os.path.join(klasor, kimlik + ".json.gz")
            ham, d = oku(yol)
            if sha(ham) != p["sha256"] or len(ham) != p["size"] or len(d["entries"]) != p["entries"]:
                hata.append(kimlik + ": index.json sha/boyut/satır sayısı dosyayla uyuşmuyor")
            if v1 and (not os.path.isfile(os.path.join(args.cikti, "v1", agac_adi(dil), kimlik))
                       or open(os.path.join(args.cikti, "v1", agac_adi(dil), kimlik), "rb").read() != ham):
                hata.append(kimlik + ": v1 paket dosyası index'teki dosyayla aynı değil")
            if kimlik in KATKI:  # katkili paket: --ekle-eksik denetimi (katki oncesi hali + katki -> dosya)
                h2, _ = ekle_eksik_denetle(planlar[kimlik][4]["katki_oncesi"], KATKI[kimlik][2], d)
                hata += [kimlik + ": katkı: " + x for x in h2]
                print("  %-28s katkı denetimi %s" % (kimlik, "geçti" if not h2 else "BAŞARISIZ: " + "; ".join(h2)))
                ok += 1
                continue
            if kimlik not in cift:
                if ham != grup[kimlik][1]:
                    hata.append(kimlik + ": birleştirilmeyen paket girdiyle bayt bayt aynı değil")
                ok += 1
                continue
            a = grup[kimlik][2]
            e = grup[cift[kimlik][0]][2]
            if d["id"] != a.get("id") or d["title"] != a.get("title") or "ek satır" in d["title"]:
                hata.append(kimlik + ": kimlik/başlık ana paketinki değil")
            for tablo in ("entries", "segments"):
                A, E, D = a.get(tablo, {}), e.get(tablo, {}), d.get(tablo, {})
                beklenen_sayi = len(set(A) | set(E))
                if len(D) != beklenen_sayi:
                    hata.append("%s.%s: anahtar sayısı %d != ana∪ek %d" % (kimlik, tablo, len(D), beklenen_sayi))
                if list(D) != sorted(D):
                    hata.append("%s.%s: anahtarlar sıralı değil" % (kimlik, tablo))
                ortak = [k for k in A if k in E and dolu(A[k])]
                for k in ortak:
                    if D[k] != A[k]:
                        hata.append("%s.%s: çakışmada ana kazanmadı (%s)" % (kimlik, tablo, k))
                        break
                tum = list(set(A) | set(E))
                ornek = rnd.sample(tum, min(200, len(tum)))
                kotu = 0
                for k in ornek:
                    bekle = A[k] if (k in A and dolu(A[k])) else E.get(k, A.get(k))
                    if D.get(k) != bekle:
                        kotu += 1
                if kotu:
                    hata.append("%s.%s: 200 örnekten %d anahtarda çeviri kaynağıyla aynı değil" % (kimlik, tablo, kotu))
                print("  %-28s %-9s ana=%d ek=%d birleşik=%d çakışma=%d örnek=%d" % (kimlik, tablo, len(A), len(E), len(D), len(ortak), len(ornek)))
            # konuşmacı adları: değerlerden yeniden çıkarılanla aynı, dize listesi, sınır içinde
            sp = d.get("speakers", [])
            if not isinstance(sp, list) or not all(isinstance(x, str) and KONUSMACI.match(x + ": a b.") for x in sp):
                hata.append(kimlik + ": speakers alanı geçersiz")
            elif sp != konusmaci_adlari(d) or len(sp) > KONUSMACI_EN_COK:
                hata.append(kimlik + ": speakers alanı değerlerden çıkarılanla aynı değil")
            else:
                print("  %-28s speakers  %d ad" % (kimlik, len(sp)))
            # bulanık imza tutarlılığı: ana imzaları aynen korunmuş mu
            if "fuzzy" in a:
                ia, ib = fuzzy_coz(a), fuzzy_coz(d)
                if ib is None:
                    hata.append(kimlik + ": birleşik paketin bulanık imzası çözülemiyor")
                elif ia != {k: v for k, v in ib.items() if k in ia} or len(ib) != len(ia):
                    hata.append(kimlik + ": ana paketin imzaları korunmadı")
            ok += 1
        # ikinci kez ayni girdiden uretince bayt bayt ayni mi
        for kimlik, tur, bayt, _, _ in plan:
            if kimlik in dizin and sha(bayt) != dizin[kimlik]["sha256"]:
                hata.append(kimlik + ": yeniden üretim bayt bayt aynı değil (belirlenimsizlik ya da bayat çıktı)")
        print("  %s listesi: %d paket" % (agac_adi(dil), len(dizin)))
    if hata:
        print("DENETİM BAŞARISIZ:")
        for h in hata:
            print(" - " + h)
        sys.exit(1)
    print("DENETİM GEÇTİ: %d paket" % ok)


def kendini_sina():
    """Sentetik: cakisma, bos ana degeri, imza yeniden dizilimi."""
    A = {"entries": {"%016x" % 1: "a1", "%016x" % 5: " ", "%016x" % 9: "a9"}, "segments": {"%016x" % 3: "s3"}}
    E = {"entries": {"%016x" % 1: "e1", "%016x" % 5: "e5", "%016x" % 2: "e2"}, "segments": {"%016x" % 3: "se3", "%016x" % 4: "se4"}}
    sira_a = sorted(set(A["entries"]) | set(A["segments"]))
    A["fuzzy"] = fuzzy_yaz(sira_a, {sira_a[0]: (20, bytes(range(8))), sira_a[3]: (40, bytes(range(8, 24)))})
    A.update(format=2, id="x", title="X")
    E.update(format=2, id="pool-x", title="X (ek satırlar)")
    assert guvenli_mi(A, E) is None
    j, cak, _ = birlestir(A, E, "x", "x")
    assert j["entries"]["%016x" % 1] == "a1" and j["entries"]["%016x" % 5] == "e5" and j["entries"]["%016x" % 2] == "e2"
    assert j["segments"]["%016x" % 3] == "s3" and cak == 2, cak
    ic = fuzzy_coz(j)
    assert ic == fuzzy_coz(A), (ic, fuzzy_coz(A))
    assert j["fuzzy"]["count"] == 6
    assert "speakers" not in j, "adsız pakete alan yazılmaz"
    # konuşmacı adları: eşik, sıra, ASCII kuralı, birleşikte alan
    soz = " ne oldu simdi?"
    K = {"entries": {"%016x" % i: v for i, v in enumerate(
        ["Lucia:" + soz] * 9 + ["Jason:" + soz] * 9 + ["Cal:" + soz] * 8 + ["Brian:" + soz] * 7 + ["UYARI:" + soz] * 9
        + ["Muhafız:" + soz] * 9 + ["Raul Bautista:" + soz] * 8 + ["lucia:" + soz] * 9 + ["Bir Iki Uc Dort:" + soz] * 9
        + ["DJ Pooh:" + soz] * 8 + ["Polis:" + soz] * 9 + ["Kimden: Lucia"] * 9 + ["Tarih: 12 Mart"] * 9
        + ["Kenny: <b>bu</b> ne simdi?"] * 8)}}
    assert konusmaci_adlari(K) == ["Jason", "Lucia", "Cal", "DJ Pooh", "Kenny", "Raul Bautista"], konusmaci_adlari(K)
    assert konusmaci_oneki("Kopya No: 4") is None and konusmaci_oneki("Bilgi: Bu bir deneme metnidir.") is None
    K.update(format=2, id="k", title="K")
    jk, _, _ = birlestir(K, {"format": 2, "id": "pool-k", "entries": {}}, "k", "k")
    assert jk["speakers"] == ["Jason", "Lucia", "Cal", "DJ Pooh", "Kenny", "Raul Bautista"]
    print("kendini sınama geçti")


# ---------------------------------------------------------------- --ekle-eksik (iki ayri paketin tek pakette birlesmesi)
# Kural: yalniz bizde olan anahtar aynen kalir; yalniz onlarda olan eklenir; ortak anahtarda onlarin (temizlenmis,
# dil etiketi soyulmus, konusmaci onegi bizimkiyle uyumlu) degeri alinir, denetimden gecmezse bizimki kalir.
# Onlarin degeri Ingilizce kaynakla ayniysa (kaynakla_ayni: uygulama boyle satiri gostermez), bizimki degilse ve deger
# konusma/cumle ise (konusma_mi) bizimki kalir ("Hey." -> bizim "Selam.", onlarin "Hey!"). Ozel ad (kisi, yer, mekan,
# gorev adi: "Port Gellhorn Motel") onlarinki kalir: ekranda oyunun kendi yazisi gorunur. Bizimki de ayniysa ya da
# anahtar yalniz onlardaysa kural islemez.
# Arama sirasi (GamePacks.lookup): once butun paketlerin entries'i, sonra segments'i. Capraz anahtar (bizde bir tabloda,
# onlarda obur tabloda) BIZIM tablomuzda tek deger olarak kalir: obur tabloya ekleme ya bizimkini golgeler
# (entries once okunur) ya da hic okunmaz.
# Dil etiketleri onlarin paketindeki deger basi oneklerinin sikligindan cikarildi (kanit: onek-sikligi.tsv).
DIL_ETIKETLERI = ("İspanyolca", "İtalyanca", "Kreolce", "Filipince", "Rusça", "Fransızca", "Arnavutça", "Portekizce",
                  "Sırpça", "Kreyolce", "Bilinmeyen dil", "Bilinmeyen Dil")
_AD = r"(?:[A-Z]{2,3} )?[A-Z][a-z]+(?: [A-Z][a-z]+){0,2}"  # PackSpeakers / KONUSMACI ad kalibi
DIL_ONEKI = re.compile(r"^(?:(%s): )?(?:%s)\s*:\s+" % (_AD, "|".join(DIL_ETIKETLERI)))
# Satir ortasi: cumle sinirindan (. ! ? … ve ardindan gelebilen tirnak/parantez) hemen sonra, istege bagli konusmaci
# onekiyle "Dil: ". Iki noktasiz gecis ("İspanyolca konuşuyor") ve Ingilizce kalintilar ("In Spanish:") alinmaz.
DIL_ORTA = re.compile(r"([.!?\u2026][\"\u201d\u2019\u00bb)\]]*)[ \t]+(?:(%s): )?(?:%s)[ \t]*:[ \t]+(?=\S)" % (_AD, "|".join(DIL_ETIKETLERI)))
DIL_IKI_NOKTASIZ = re.compile(r"(?:%s)\b(?![ \t]*:)" % "|".join(DIL_ETIKETLERI))
DIL_INGILIZCE = re.compile(r"(?i)\b(?:spanish|italian|creole|french|russian|filipino|tagalog|portuguese|albanian|serbian)[ \t.]*:")
# Arapca paket (gta-6-ar) icin ayni kural: deger basi sikligindan cikarilan kesin dil adlari ("بالإسبانية" = İspanyolca).
DIL_ETIKETLERI_AR = ("بالإسبانية", "بلغة غير معروفة", "بالإيطالية", "بالكريولية", "بالفلبينية", "بالروسية", "بالفرنسية",
                     "بالألبانية", "بالبرتغالية", "بالصربية", "بالإنجليزية")
_AD_AR = r"[^\s:.!?\u061f\u2026\u060c]+(?: [^\s:.!?\u061f\u2026\u060c]+){0,2}"  # en cok uc sozcuk, noktalamasiz
DIL_KALIPLARI = {
    "tr": (DIL_ONEKI, DIL_ORTA),
    "ar": (re.compile(r"^(?:(%s): )?(?:%s)\s*:\s+" % (_AD_AR, "|".join(DIL_ETIKETLERI_AR))),
           re.compile(r"([.!?\u061f\u2026][\"\u201d\u2019\u00bb)\]]*)[ \t]+(?:(%s): )?(?:%s)[ \t]*:[ \t]+(?=\S)"
                      % (_AD_AR, "|".join(DIL_ETIKETLERI_AR)))),
}
DIL_IKI_NOKTASIZ_AR = re.compile(r"(?:%s)(?![ \t]*:)" % "|".join(DIL_ETIKETLERI_AR))
GENEL_ONEK = re.compile(r"^([^:\n]{1,32}): \S")  # konusmaci olsun olmasin herhangi bir "Etiket: " basi
EN_UZUN_BAYT = 4096


def dil_soy(v, dil="tr"):
    """Deger basindaki (konusmaci onekinden sonraki dahil) dil etiketlerini atar. Doner: (deger, soyulan sayisi)."""
    soyuldu = 0
    bas_k = DIL_KALIPLARI[dil][0]
    m = bas_k.match(v)
    while m:  # "İspanyolca: İspanyolca: ..." gibi yinelenen etiket de atilir
        kalan = v[m.end():]
        v = (m.group(1) + ": " + kalan) if m.group(1) else kalan
        soyuldu += 1
        m = bas_k.match(v)
    return v, soyuldu


def dil_temizle(v, dil="tr"):
    """Bastaki ve cumle sinirindan sonraki dil etiketlerini atar. Doner: (deger, soyulan etiket sayisi). Sonuc bos
    kalacaksa deger oldugu gibi doner (0)."""
    s, bas = dil_soy(v, dil)
    n = int(bas)
    while True:
        s2, k = DIL_KALIPLARI[dil][1].subn(lambda m: m.group(1) + " " + ((m.group(2) + ": ") if m.group(2) else ""), s)
        if not k:
            break
        s, n = s2, n + k
    if not n:
        return v, 0
    s = re.sub(r"[ \t]{2,}", " ", s).strip()
    return (s, n) if s else (v, 0)


def deger_denetimi(v):
    """Eklenecek/alinacak deger: (temiz deger, None) ya da (None, neden)."""
    if not isinstance(v, str):
        return None, "dize değil"
    t = temiz_deger(v)
    if not t:
        return None, "boş"
    import unicodedata
    for ch in t:
        if ch == "�" or unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn"):
            return None, "denetim/bozuk karakter"
    if len(t.encode("utf-8", "surrogatepass")) > EN_UZUN_BAYT:
        return None, "aşırı uzun"
    return t, None


def hazirla(v):
    """Onlarin degeri: dil etiketi soyulur, sonra denetlenir. Doner: (deger|None, neden|None, soyuldu)."""
    if not isinstance(v, str):
        return None, "dize değil", False
    s, soyuldu = dil_temizle(temiz_deger(v))
    t, neden = deger_denetimi(s)
    return t, neden, soyuldu


def genel_onek(v):
    """Degerin basindaki "Etiket: " (en cok 4 sozcuk, icinde cumle noktalamasi yok); yoksa None."""
    m = GENEL_ONEK.match(v)
    if not m or len(m.group(1).split()) > 4 or any(c in m.group(1) for c in ".!?,;"):
        return None
    return m.group(1)


def konusmaci_uyumu(bizim, onlarin, bilinen=()):
    """Ortak anahtarda konusmaci/etiket onegini bizimkiyle uyumlu yapar. Doner: (deger|None, tur). None: bizimki kalsin.
    Uygulama okunan satirin basindaki etiketi ayirip govdeyi arayabilir ve etiketi ceviriye kendisi ekler
    (PackLookup.single); paketteki onek ekranda gorunur. Onegin varligi anahtarin Ingilizcesine baglidir, bu yuzden
    bizim degerdeki onek durumu korunur: iki tarafta da etiket varsa bizim etiket + onlarin sozu; yalniz bizde bilinen
    konusmaci (speakers) varsa bizim onek + onlarin degeri; obur tek tarafli durumlarda bizimki kalir."""
    gb, ga = genel_onek(dil_soy(temiz_deger(bizim))[0]), genel_onek(onlarin)  # bizim dil etiketi konusmaci degil
    if gb is None and ga is None:
        return onlarin, "aynı"
    if gb is not None and ga is not None:
        if gb == ga:
            return onlarin, "aynı"
        return gb + ": " + onlarin[len(ga) + 2:].strip(), "bizim etiket + onların sözü"
    if gb is not None:
        if gb in bilinen and gb.lower() not in onlarin.lower():  # ad onlarin sozunde zaten geciyorsa ikilenmesin
            return gb + ": " + onlarin, "bizim konuşmacı öneki eklendi"
        return None, "etiket yalnız bizde (bilinen konuşmacı değil)"
    return None, "etiket yalnız onlarda"


def paket_anahtari(metin):
    """Uygulamanin paket anahtari (PackKey.key): etiketler bosluk, NFKC, kucuk harf, NFD ile isaretler atilir, harf ve
    rakam disi bosluk, bosluklar teklenir; SHA-256'nin ilk 8 bayti (hex). Harf/rakam yoksa None."""
    import unicodedata
    s = re.sub(r"<[^<>]{0,40}>", " ", metin)
    s = unicodedata.normalize("NFD", unicodedata.normalize("NFKC", s).lower())
    cikti, bosluk = [], False
    for ch in s:
        kat = unicodedata.category(ch)
        if kat[0] == "M":
            continue
        if kat[0] in "LN":
            if bosluk and cikti:
                cikti.append(" ")
            bosluk = False
            cikti.append(ch)
        else:
            bosluk = True
    kanon = "".join(cikti)
    return hashlib.sha256(kanon.encode("utf-8")).hexdigest()[:16] if kanon else None


def kaynakla_ayni(anahtar, deger):
    """Deger, anahtarin Ingilizce kaynagiyla sadelestirilince birebir ayni mi (paket_anahtari(deger) == anahtar).
    Uygulama boyle ceviriyi gostermez (SubtitleStabilizer.shouldSend: normalize + Levenshtein >= 0.90; buyuk/kucuk
    harf ve noktalama sayilmaz). Paket Ingilizceyi tasimaz (anahtar ozettir), bu yuzden yalniz birebir aynilik
    olculebilir; %90-99 benzer degerler burada yakalanmaz."""
    return isinstance(deger, str) and paket_anahtari(deger) == anahtar


# Konusma ayiraci: bu sozcuklerden biriyle baslayan deger konusmadir (unlem, selam, onay).
UNLEMLER = frozenset("""hey hi hello yo okay ok yeah ye yep yup nope nah oh ah ahh uh um hmm mmm heh huh ugh igh wow whoa
lol lmao omg sorry thanks""".split())
# Sondaki sozcugu bunlardan biri olan deger ad sayilir: kisaltmalar ("Vice Beach St.") ve yer/kurum adi sozcukleri
# (gorev metnindeki "Broke Peak Trail.", "Legendary Custom Jewelry Store.", noktalamasiz "caprice canal").
AD_KISALTMALARI = frozenset("""st ave blvd rd dr jr sr inc co ltd corp bros mt ft street avenue road boulevard drive lane
way trail bridge overpass park beach bay island islands river lake dam store shop mart market motel hotel inn bar club
diner cafe restaurant station center centre mall plaza square tower building hall church school hospital airport port
marina pier jetty dock quay yard squad gang crew company county city town village heights hills valley point creek
canal highway freeway expressway parkway pass peak mountain reserve national apartments apartment pd""".split())
# Ad icinde kucuk harfle yazilabilen baglaclar ("Port of Gellhorn", "The Ogdoad that Never Comes"): konusma sayilmaz.
AD_BAGLACLARI = frozenset("of the a an and n that de da del di du la le los las van von y & at on in by for to".split())
# Olcu birimleri: yalniz sayi ve birimden olusan deger ("ft", "3 - 10 lbs") ad gibi oyunun yazisiyla kalir.
BIRIMLER = frozenset("ft mph kph mi oz yd yds lb lbs km kg mm cm m g".split())
# Bizim (Turkce) degerde ad ogesi sayilan kucuk harfli sozcukler: baglac ve soru eki ("Kont Sikula mı?").
TR_AD_BAGLACLARI = frozenset("ve ile ya veya de da mi mı mu mü".split())


def _sozcukler(t):
    """Bosluklar arasindaki parcalar, bas/son isaretleri atilmis; rakamli parca ("3rd", "90") sozcuk sayilmaz."""
    return [w for w in (re.sub(r"^\W+|\W+$", "", x) for x in t.split()) if w and not any(c.isdigit() for c in w)]


def konusma_mi(deger, bizim=None):
    """Kaynakla ayni degerin konusma/cumle mi ozel ad mi oldugu (belirsizde ad: Ingilizce kalir). Sira:
    (a) ! ? … icermeyen, yalniz sayi ve olcu biriminden olusan deger ad ("ft", "3 - 10 lbs");
    (b) ilk sozcugu unlem/selam olan konusma ("Hey", "lol", "Okay");
    (c) . ! ? … icermeyen degerde son sozcuk ad sonuysa ("caprice canal") ya da hic buyuk harf yoksa ("starfish") ad;
    (d) konusma adayi: son karakter (kapanis tirnagi atilinca) ! ? … ya da metinde ! ? … gecer, ya da ad sonu
        olmayan sondaki nokta; ya da baglac disinda tamami kucuk harfli bir sozcuk var ("Jimmy snorts");
    (e) aday olsa da: '!' ile bitmeyen, butun sozcukleri buyuk harfle baslayan (baglac haric) deger, bizim Turkce
        degerimiz de yalniz buyuk harfli sozcuk/baglac/soru ekinden olusuyorsa ad ("Kenton. Sir Todd.", "Cartagena.");
        '?' ile bitende ayrica bizimki onlarin buyuk harfli sozcuklerinden birini (2+ harf) icermemeli ("Andrew Node?" /
        "Andrew!!!" ad; "Joe?" / "Joe mu?" konusma). Bizim deger cumle cevirisiyse ("Jimmy burnunu çekiyor.") konusma.
    Gerisi ad."""
    t = deger.strip()
    son = t.rstrip("\"'\u201d\u2019)]\u00bb ")
    isaretli = any(c in t for c in "!?\u2026")
    parcalar = [w for w in (re.sub(r"^\W+|\W+$", "", x) for x in t.split()) if w]
    if not isaretli and parcalar and all(any(c.isdigit() for c in w) or w.lower() in BIRIMLER for w in parcalar):
        return False
    sozcukler = _sozcukler(t)
    if sozcukler and sozcukler[0].lower() in UNLEMLER:
        return True
    if not isaretli and "." not in son[-1:]:
        if sozcukler and sozcukler[-1].lower() in AD_KISALTMALARI:
            return False
        if not any(c.isupper() for c in t):
            return False
    aday = isaretli or son.endswith("..")
    if not aday and son[-1:] == "." and not re.search(r"(?:^|[\s.])[A-Za-z]\.$", son):
        aday = re.sub(r"\W", "", son.rsplit(None, 1)[-1]).lower() not in AD_KISALTMALARI
    if not aday:
        aday = any(w.islower() and w.lower() not in AD_BAGLACLARI for w in sozcukler)
    if not aday:
        return False
    if bizim is not None and sozcukler and not son.endswith("!") \
            and all(w[0].isupper() or w.lower() in AD_BAGLACLARI for w in sozcukler) \
            and all(w[0].isupper() or w.lower() in TR_AD_BAGLACLARI for w in _sozcukler(bizim)) \
            and (not son.endswith("?")
                 or any(len(w) >= 2 and w.lower() not in bizim.lower() for w in sozcukler if w.lower() not in AD_BAGLACLARI)):
        return False
    return True


def ekle_eksik(biz, asil):
    """Doner: (paket, sayac, degisenler [(tablo, anahtar, once, sonra)], elenenler {anahtar: neden})."""
    T = ("entries", "segments")
    cikti_t = {t: dict(biz.get(t, {})) for t in T}
    say = {"eklenen_satir": 0, "eklenen_anahtar": 0, "elenen_satir": 0, "elenen_anahtar": 0, "ortak_anahtar": 0,
           "ortak_degisen": 0, "ortak_ayni": 0, "istisna": 0, "capraz_bizE_onlarS": 0, "capraz_bizS_onlarE": 0,
           "soyulan_etiket": 0, "soyulan_etiket_ortak_alinan": 0, "soyulan_etiket_eklenen": 0,
           "soyulan_etiket_bizim": 0, "bizim_soyulan_deger": 0, "kaynakla_ayni_entries": 0, "kaynakla_ayni_segments": 0,
           "kaynakla_ayni_ad_entries": 0, "kaynakla_ayni_ad_segments": 0}
    nedenler = {}
    kaynakla_ayni_kalan = []
    degisen, elenen = [], {}
    bizde = set(biz.get("entries", {})) | set(biz.get("segments", {}))
    bilinen = frozenset(biz.get("speakers") or ())
    onlarda = sorted(set(asil.get("entries", {})) | set(asil.get("segments", {})))
    for k in onlarda:
        ov = {t: asil[t][k] for t in T if k in asil.get(t, {})}
        if k not in bizde:
            eklendi = False
            for t, v in ov.items():
                d, neden, soy = hazirla(v)
                if d is None:
                    say["elenen_satir"] += 1
                    nedenler["eklenen: " + neden] = nedenler.get("eklenen: " + neden, 0) + 1
                    continue
                cikti_t[t][k] = d
                say["eklenen_satir"] += 1
                say["soyulan_etiket"] += soy
                say["soyulan_etiket_eklenen"] += soy
                eklendi = True
            if eklendi:
                say["eklenen_anahtar"] += 1
            else:
                say["elenen_anahtar"] += 1
                elenen[k] = "denetim"
            continue
        say["ortak_anahtar"] += 1
        for t in T:
            if k not in biz.get(t, {}):
                continue
            if t in ov:
                v = ov[t]
            else:  # capraz: onlarin obur tablodaki degeri bizim tablomuzda kalir
                v = ov["segments" if t == "entries" else "entries"]
                say["capraz_bizE_onlarS" if t == "entries" else "capraz_bizS_onlarE"] += 1
            once = biz[t][k]
            d, neden, soy = hazirla(v)
            tur = None
            if d is not None:
                d, tur = konusmaci_uyumu(once, d, bilinen)
                if d is not None and not d:
                    d, tur = None, "önek çıkarınca boş"
                # Onlarin degeri kaynakla ayni (uygulama gostermez), bizimki degil: bizimki kalir.
                if d is not None and kaynakla_ayni(k, d) and not kaynakla_ayni(k, dil_temizle(once)[0]):
                    konusma = konusma_mi(d, dil_temizle(once)[0])
                    say[("kaynakla_ayni_" if konusma else "kaynakla_ayni_ad_") + t] += 1
                    kaynakla_ayni_kalan.append((t, k, d, once, konusma))
                    if konusma:
                        d, tur = None, "onların değeri kaynakla aynı (konuşma)"
                if d is None:
                    neden = tur
            if d is None:
                say["istisna"] += 1
                nedenler["istisna: " + neden] = nedenler.get("istisna: " + neden, 0) + 1
                continue
            if tur != "aynı":
                nedenler["konuşmacı: " + tur] = nedenler.get("konuşmacı: " + tur, 0) + 1
            say["soyulan_etiket"] += soy
            say["soyulan_etiket_ortak_alinan"] += soy
            if d == once:
                say["ortak_ayni"] += 1
                continue
            cikti_t[t][k] = d
            say["ortak_degisen"] += 1
            degisen.append((t, k, once, d))
    # Bizden kalan degerlerde (yalniz bizde, istisna, ayni) de dil etiketleri soyulur; onlardan gelenler zaten temiz.
    bizim_soyulan = []
    for t in T:
        for k, v in cikti_t[t].items():
            d2, n = dil_temizle(v)
            if n:
                cikti_t[t][k] = d2
                say["soyulan_etiket"] += n
                say["soyulan_etiket_bizim"] += n
                say["bizim_soyulan_deger"] += 1
                bizim_soyulan.append((t, k, v, d2))
    entries = dict(sorted(cikti_t["entries"].items()))
    segments = dict(sorted(cikti_t["segments"].items()))
    sira = sorted(set(entries) | set(segments))
    imza = {}
    for kaynak in (asil, biz):  # imza Ingilizceye bagli; bizimki oncelikli
        c = fuzzy_coz(kaynak) if "fuzzy" in kaynak else None
        if c:
            imza.update(c)
    kume = set(sira)
    imza = {k: v for k, v in imza.items() if k in kume}
    cikti = {"format": 2, "id": biz.get("id"), "title": biz.get("title")}
    kaynaklar = [s for s in (biz.get("source"), ("ek ve öncelikli satırlar: " + asil["source"]) if asil.get("source") else None) if s]
    if kaynaklar:
        cikti["source"] = "; ".join(kaynaklar)
    cikti["entries"] = entries
    cikti["segments"] = segments
    if imza:
        cikti["fuzzy"] = fuzzy_yaz(sira, imza)
    if "speakers" in biz:
        cikti["speakers"] = biz["speakers"]  # korunur
    say["nedenler"] = dict(sorted(nedenler.items()))
    say["bizim_soyulan"] = bizim_soyulan
    say["kaynakla_ayni_kalan"] = kaynakla_ayni_kalan  # (tablo, anahtar, onlarin, bizim, konusma mi)
    return cikti, say, degisen, elenen


def ekle_eksik_denetle(biz, asil, d, elenen_beklenen=None):
    """Bagimsiz sayisal kanit. Doner: (hata listesi, olcumler)."""
    T = ("entries", "segments")
    hata, o = [], {}
    B = {t: biz.get(t, {}) for t in T}
    A = {t: asil.get(t, {}) for t in T}
    D = {t: d.get(t, {}) for t in T}
    bk = set(B["entries"]) | set(B["segments"])
    ak = set(A["entries"]) | set(A["segments"])
    dk = set(D["entries"]) | set(D["segments"])
    # (3) anahtar kumesi
    elenen = {k for k in ak - bk if all(hazirla(A[t][k])[0] is None for t in T if k in A[t])}
    if dk != (bk | ak) - elenen:
        hata.append("anahtar kümesi birleşim eksi elenen değil (fark %d)" % len(dk ^ ((bk | ak) - elenen)))
    o["anahtar_biz"], o["anahtar_asil"], o["anahtar_yeni"], o["elenen_anahtar"] = len(bk), len(ak), len(dk), len(elenen)
    o["eklenen_anahtar"] = len(dk - bk)
    if not bk <= dk:
        hata.append("bizim anahtarlardan kaybolan var: %d" % len(bk - dk))
    # (1) yalniz bizde olanlar birebir, tablolari ayni
    ayni = soyuldu = 0
    for t in T:
        for k, v in B[t].items():
            if k in ak:
                continue
            if D[t].get(k) == v:
                ayni += 1
            elif D[t].get(k) == dil_temizle(v)[0]:
                soyuldu += 1
            else:
                hata.append("yalnız bizdeki anahtar dil etiketi dışında değişti: %s.%s" % (t, k))
                break
    o["yalniz_biz_birebir"], o["yalniz_biz_yalniz_dil_etiketi_soyulan"] = ayni, soyuldu
    # tablo yerlesimi: bizim anahtar bizim tablolarimizda, yeni anahtar onlarin tablolarinda (golgeleme yok)
    for t in T:
        for k in D[t]:
            if (k in bk and k not in B[t]) or (k not in bk and k not in A[t]):
                hata.append("anahtar beklenmeyen tabloda: %s.%s" % (t, k))
                break
    # (2) ortak anahtar: onlarin hazirlanmis degeri, konusmaci onegi uyarlanmis hali ya da belgelenmis istisna (bizimki)
    alinan = istisna = kaynakla = 0
    for t in T:
        for k, once in B[t].items():
            if k not in ak:
                continue
            v = A[t][k] if k in A[t] else A["segments" if t == "entries" else "entries"][k]
            h = hazirla(v)[0]
            son = D[t][k]
            bizim_temiz = dil_temizle(once)[0]
            if son != bizim_temiz and kaynakla_ayni(k, son) and not kaynakla_ayni(k, bizim_temiz) and konusma_mi(son, bizim_temiz):
                hata.append("ortak anahtarda kaynakla aynı konuşma değeri alındı, bizimki atıldı: %s.%s" % (t, k))
                break
            if son == bizim_temiz and h is not None and kaynakla_ayni(k, h) and not kaynakla_ayni(k, bizim_temiz) and konusma_mi(h, bizim_temiz):
                kaynakla += 1
            adaylar = set()
            if h is not None:
                adaylar.add(h)
                gb, ga = genel_onek(dil_soy(temiz_deger(once))[0]), genel_onek(h)
                if gb is not None:
                    adaylar.add(gb + ": " + (h[len(ga) + 2:].strip() if ga is not None else h))
            if son in adaylar:
                alinan += 1
            elif son == dil_temizle(once)[0]:
                istisna += 1
            else:
                hata.append("ortak anahtarda değer ne onların ne bizim: %s.%s" % (t, k))
                break
    o["ortak_onlarin"], o["ortak_istisna_bizim"] = alinan, istisna
    o["ortak_onlarinki_kaynakla_ayni_bizimki_kaldi"] = kaynakla
    # yeni anahtar: onlarin hazirlanmis degeri
    for t in T:
        for k in dk - bk:
            if k in D[t] and D[t][k] != hazirla(A[t].get(k))[0]:
                hata.append("eklenen değer onlarınkiyle aynı değil: %s.%s" % (t, k))
                break
    # (4) dil etiketi kalmadi mi
    hepsi = [v for t in T for v in D[t].values()]
    bas = sum(1 for v in hepsi if DIL_ONEKI.match(v))
    orta = sum(1 for v in hepsi if DIL_ORTA.search(v))
    soyulmamis = sum(1 for v in hepsi if dil_temizle(v)[1])  # soyulabilir ama birakilmis deger (bos kalacagi icin degil)
    bos_kalacak = sum(1 for v in hepsi if (DIL_ONEKI.match(v) or DIL_ORTA.search(v)) and not dil_temizle(v)[1])
    o["dil_etiketi_basta_kalan"], o["dil_etiketi_ortada_kalan"] = bas, orta
    o["dil_etiketi_soyulunca_bos_kalacagi_icin_birakilan"] = bos_kalacak
    o["dil_adi_iki_noktasiz_dokunulmadi"] = sum(1 for v in hepsi if DIL_IKI_NOKTASIZ.search(v))
    o["ingilizce_dil_etiketi_dokunulmadi"] = sum(1 for v in hepsi if DIL_INGILIZCE.search(v))
    o["dil_etiketli_asil_girdi"] = sum(1 for t in T for v in A[t].values() if DIL_ONEKI.match(temiz_deger(v)))
    o["dil_etiketli_biz_girdi"] = sum(1 for t in T for v in B[t].values() if DIL_ONEKI.match(v) or DIL_ORTA.search(v))
    if soyulmamis:
        hata.append("soyulabilir dil etiketi kaldı: %d değer" % soyulmamis)
    # fuzzy: cozulur, bizim imzalar aynen, eklenenler onlarinkiyle ayni
    ib, ia = fuzzy_coz(biz) or {}, fuzzy_coz(asil) or {}
    idd = fuzzy_coz(d) if "fuzzy" in d else ({} if not (ib or ia) else None)
    if idd is None:
        hata.append("yeni paketin bulanık imzası çözülemiyor")
    else:
        if any(idd.get(k) != v for k, v in ib.items()):
            hata.append("bizim imzalar korunmadı")
        if any(idd.get(k) != v for k, v in ia.items() if k in dk and k not in ib):
            hata.append("onların imzası aktarılmadı")
        if set(idd) - set(ib) - set(ia):
            hata.append("kaynağı olmayan imza var")
        o["imza_yeni"], o["imza_biz"] = len(idd), len(ib)
        o["imza_eklenen"] = len(set(idd) - set(ib))
        o["imzasiz_eklenen_anahtar"] = len((dk - bk) - set(idd))
        ortak_imza = [k for k in ib if k in ia]
        o["ortak_imza"], o["ortak_imza_farkli"] = len(ortak_imza), sum(1 for k in ortak_imza if ib[k] != ia[k])
    if d.get("speakers") != biz.get("speakers"):
        hata.append("speakers korunmadı")
    if d.get("format") != 2 or d.get("id") != biz.get("id") or d.get("title") != biz.get("title"):
        hata.append("biçim/kimlik/başlık değişti")
    beklenen_kaynak = "; ".join(x for x in (biz.get("source"), ("ek ve öncelikli satırlar: " + asil["source"]) if asil.get("source") else None) if x)
    if d.get("source", "") != beklenen_kaynak:
        hata.append("source eki uygun değil")
    for t in T:
        if list(D[t]) != sorted(D[t]):
            hata.append(t + " sıralı değil")
    return hata, o


def ekle_eksik_kipi(args):
    _, biz = oku(args.biz)
    _, asil = oku(args.asil)
    neden = guvenli_mi(biz, asil)
    if neden:
        sys.exit("BİRLEŞTİRİLEMEDİ: " + neden)
    kimlik = biz.get("id")
    if not KIMLIK.match(kimlik or ""):
        sys.exit("Güvenli olmayan kimlik")
    hedef = os.path.join(args.cikti, kimlik + ".json.gz")
    if args.denetle:
        ham, d = oku(hedef)
        hata, o = ekle_eksik_denetle(biz, asil, d)
        j, _, _, _ = ekle_eksik(biz, asil)
        if gz_yaz(json_bayt(j)) != ham:
            hata.append("yeniden üretim bayt bayt aynı değil")
        o["yeniden_uretim_ayni"] = not any("yeniden" in h for h in hata)
        print(json.dumps(o, ensure_ascii=False, indent=1, sort_keys=True))
        if hata:
            print("DENETİM BAŞARISIZ:")
            for h in hata:
                print(" - " + h)
            sys.exit(1)
        print("DENETİM GEÇTİ")
        return
    j, say, degisen, elenen = ekle_eksik(biz, asil)
    bayt = gz_yaz(json_bayt(j))
    os.makedirs(args.cikti, exist_ok=True)
    with open(hedef, "wb") as f:
        f.write(bayt)
    if args.ornek:
        rnd = random.Random(20261125)
        with open(args.ornek, "w", encoding="utf-8", newline="\n") as f:
            f.write("# rastgele 40 ortak satır: önce (bizim) -> sonra (yeni paket); tablo anahtar\n\n")
            for t, k, a, b in rnd.sample(degisen, min(40, len(degisen))):
                f.write("%s %s\n  önce:  %s\n  sonra: %s\n\n" % (t, k, a, b))
            f.write("# rastgele 20 bizden kalan değer: yalnız dil etiketi soyuldu (baştaki ve satır ortasındaki)\n\n")
            bs = say["bizim_soyulan"]
            for t, k, a, b in rnd.sample(bs, min(20, len(bs))):
                f.write("%s %s\n  önce:  %s\n  sonra: %s\n\n" % (t, k, a, b))
    fz_b, fz_d = biz.get("fuzzy", {}), j.get("fuzzy", {})
    nb = len(set(biz["entries"]) | set(biz.get("segments", {})))
    nd = len(set(j["entries"]) | set(j["segments"]))
    giris = {"id": kimlik, "title": j["title"], "version": args.surum, "sha256": sha(bayt), "size": len(bayt),
             "entries": len(j["entries"])}
    satir = [
        "Paket: %s (sürüm %d)" % (kimlik, args.surum),
        "Kural: yalnız bizde olan aynen (yalnız dil etiketi soyulur); yalnız onlarda olan eklenir; ortakta onların değeri (dil etiketi soyulmuş, "
        "konuşmacı öneki bizimkiyle uyumlu); denetimden geçmeyende ve onların değeri İngilizce kaynakla aynı bir konuşmayken (bizimki "
        "değilse; özel adda onlarınki) bizimki kalır. Çapraz anahtar bizim tablomuzda kalır.",
        "",
        "                önce        sonra",
        "entries     %9d   %9d" % (len(biz["entries"]), len(j["entries"])),
        "segments    %9d   %9d" % (len(biz.get("segments", {})), len(j["segments"])),
        "toplam      %9d   %9d" % (nb, nd),
        "fuzzy.count %9d   %9d" % (fz_b.get("count", 0), fz_d.get("count", 0)),
        "",
        "eklenen anahtar: %d (satır %d)" % (say["eklenen_anahtar"], say["eklenen_satir"]),
        "elenen (yeni) anahtar: %d (satır %d)" % (say["elenen_anahtar"], say["elenen_satir"]),
        "ortak anahtar: %d; değişen satır %d, aynı kalan %d, istisna (bizimki kaldı) %d" % (
            say["ortak_anahtar"], say["ortak_degisen"], say["ortak_ayni"], say["istisna"]),
        "kaynakla aynı konuşma (bizimki kaldı): entries %d, segments %d; kaynakla aynı ad (onlarınki kaldı): entries %d, segments %d" % (
            say["kaynakla_ayni_entries"], say["kaynakla_ayni_segments"], say["kaynakla_ayni_ad_entries"], say["kaynakla_ayni_ad_segments"]),
        "çapraz: bizde entries/onlarda segments %d, bizde segments/onlarda entries %d (bizim tabloda kaldı)" % (
            say["capraz_bizE_onlarS"], say["capraz_bizS_onlarE"]),
        "soyulan dil etiketi: %d (ortakta alınan %d, eklenen %d, bizden kalan %d değerde %d); etiketler: %s" % (
            say["soyulan_etiket"], say["soyulan_etiket_ortak_alinan"], say["soyulan_etiket_eklenen"],
            say["bizim_soyulan_deger"], say["soyulan_etiket_bizim"], ", ".join(DIL_ETIKETLERI)),
        "ayrıntı: " + "; ".join("%s=%d" % kv for kv in say["nedenler"].items()),
        "kalan dil etiketli değer (baş/orta, kesin liste): %d / %d" % (
            sum(1 for t in ("entries", "segments") for v in j[t].values() if DIL_ONEKI.match(v)),
            sum(1 for t in ("entries", "segments") for v in j[t].values() if DIL_ORTA.search(v))),
        "",
        "dosya boyutu: %d bayt (önce %d)" % (len(bayt), os.path.getsize(args.biz)),
        "sha256: " + sha(bayt),
        "dizin girdisi: " + json.dumps(giris, ensure_ascii=False, separators=(",", ":")),
    ]
    with open(os.path.join(args.cikti, "ozet.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(satir) + "\n")
    print("\n".join(satir))


def etiket_soy(d, dil):
    """Paketin degerlerindeki dil etiketlerini soyar; anahtarlar, tablolar, sira ve fuzzy degismez.
    Doner: (paket, sayac, degisenler [(tablo, anahtar, once, sonra)])."""
    j = {}
    say = {"deger": 0, "degisen_deger": 0, "soyulan_etiket": 0}
    degisen = []
    for alan, deger in d.items():
        if alan in ("entries", "segments") and isinstance(deger, dict):
            yeni = {}
            for k, v in deger.items():
                say["deger"] += 1
                v2, n = dil_temizle(v, dil) if isinstance(v, str) else (v, 0)
                if n:
                    say["degisen_deger"] += 1
                    say["soyulan_etiket"] += n
                    degisen.append((alan, k, v, v2))
                yeni[k] = v2
            j[alan] = yeni
        elif alan == "source" and isinstance(deger, str):
            j[alan] = deger + "; dil etiketleri ayıklandı"
        else:
            j[alan] = deger
    if "source" not in j:
        j["source"] = "dil etiketleri ayıklandı"
    return j, say, degisen


def etiket_soy_denetle(eski, yeni, dil):
    hata, o = [], {}
    bas_k, orta_k = DIL_KALIPLARI[dil]
    for t in ("entries", "segments"):
        E, Y = eski.get(t, {}), yeni.get(t, {})
        if list(E) != list(Y):
            hata.append(t + ": anahtar kümesi/sırası değişti")
        kotu = sum(1 for k in E if Y.get(k) != dil_temizle(E[k], dil)[0])
        if kotu:
            hata.append("%s: %d değer kuraldan farklı" % (t, kotu))
    if eski.get("fuzzy") != yeni.get("fuzzy"):
        hata.append("fuzzy değişti")
    if fuzzy_coz(yeni) is None and "fuzzy" in yeni:
        hata.append("fuzzy çözülemiyor")
    if {k: v for k, v in eski.items() if k not in ("entries", "segments", "source")} != \
            {k: v for k, v in yeni.items() if k not in ("entries", "segments", "source")}:
        hata.append("öbür alanlar değişti")
    if yeni.get("source") != (eski.get("source", "") + "; dil etiketleri ayıklandı" if eski.get("source") else "dil etiketleri ayıklandı"):
        hata.append("source eki uygun değil")
    for ad, d in (("once", eski), ("sonra", yeni)):
        hepsi = [v for t in ("entries", "segments") for v in d.get(t, {}).values()]
        o[ad + "_basta_etiketli"] = sum(1 for v in hepsi if bas_k.match(v))
        o[ad + "_ortada_etiketli"] = sum(1 for v in hepsi if orta_k.search(v))
        o[ad + "_soyulabilir"] = sum(1 for v in hepsi if dil_temizle(v, dil)[1])
    hepsi = [v for t in ("entries", "segments") for v in yeni.get(t, {}).values()]
    if dil == "ar":
        o["dokunulmadi_iki_noktasiz_dil_adi"] = sum(1 for v in hepsi if DIL_IKI_NOKTASIZ_AR.search(v))
        o["dokunulmadi_cumle_siniri_olmayan_etiket"] = sum(
            1 for v in hepsi if re.search(r"\S[ \t]+(?:%s)[ \t]*:" % "|".join(DIL_ETIKETLERI_AR), v) and not orta_k.search(v))
    o["anahtar_entries"], o["anahtar_segments"] = len(yeni.get("entries", {})), len(yeni.get("segments", {}))
    o["fuzzy_ayni"] = eski.get("fuzzy") == yeni.get("fuzzy")
    if o["sonra_soyulabilir"]:
        hata.append("soyulabilir etiket kaldı: %d" % o["sonra_soyulabilir"])
    return hata, o


def etiket_soy_kipi(args):
    ham, d = oku(args.etiket_soy)
    dil = dil_kodu(d.get("lang")) or VARSAYILAN_DIL
    if dil not in DIL_KALIPLARI:
        sys.exit("bu dil için etiket listesi yok: " + dil)
    kimlik = d.get("id") or os.path.basename(args.etiket_soy)[: -len(".json.gz")]
    if not KIMLIK.match(kimlik):
        sys.exit("Güvenli olmayan kimlik")
    hedef = os.path.join(args.cikti, kimlik + ".json.gz")
    j, say, degisen = etiket_soy(d, dil)
    bayt = gz_yaz(json_bayt(j))
    if args.denetle:
        yham, y = oku(hedef)
        hata, o = etiket_soy_denetle(d, y, dil)
        if yham != bayt:
            hata.append("yeniden üretim bayt bayt aynı değil")
        o.update(dil=dil, sha256=sha(yham), boyut=len(yham), degisen_deger=say["degisen_deger"], soyulan_etiket=say["soyulan_etiket"])
        print(json.dumps(o, ensure_ascii=False, indent=1, sort_keys=True))
        if hata:
            print("DENETİM BAŞARISIZ:\n - " + "\n - ".join(hata))
            sys.exit(1)
        print("DENETİM GEÇTİ")
        return
    os.makedirs(args.cikti, exist_ok=True)
    with open(hedef, "wb") as f:
        f.write(bayt)
    if args.ornek:
        rnd = random.Random(20261125)
        with open(args.ornek, "w", encoding="utf-8", newline="\n") as f:
            f.write("# rastgele 20 değer: önce -> sonra (dil etiketi soyuldu); tablo anahtar\n\n")
            for t, k, a, b in rnd.sample(degisen, min(20, len(degisen))):
                f.write("%s %s\n  önce:  %s\n  sonra: %s\n\n" % (t, k, a, b))
    print("%s (%s): değer=%d değişen=%d soyulan etiket=%d boyut=%d->%d sha256=%s" % (
        kimlik, dil, say["deger"], say["degisen_deger"], say["soyulan_etiket"], len(ham), len(bayt), sha(bayt)))


def ekle_eksik_sina():
    h = lambda i: "%016x" % i
    soz = " bu bir deneme cümlesi."
    B = {"format": 2, "id": "x", "title": "X", "source": "eski",
         "entries": {h(1): "bizim1", h(2): "Lucia:" + soz, h(3): "bizim3", h(4): "bizim4", h(9): "yalniz biz"},
         "segments": {h(5): "bizim parça", h(6): "parça6"}, "speakers": ["Lucia"]}
    A = {"format": 2, "id": "x", "title": "X", "source": "asil kaynak",
         "entries": {h(1): "onların1", h(2): soz.strip(), h(3): " ", h(5): "tam satır", h(10): "İspanyolca: Hadi gidelim!",
                     h(11): "bozuk\x07", h(12): "Jason: İspanyolca: Dur orada!"},
         "segments": {h(4): "onların parça4", h(6): "Kreolce: Parça altı.", h(13): "yeni parça"}}
    sb = sorted(set(B["entries"]) | set(B["segments"]))
    sa = sorted(set(A["entries"]) | set(A["segments"]))
    B["fuzzy"] = fuzzy_yaz(sb, {h(1): (20, bytes(8)), h(9): (21, bytes(range(8)))})
    A["fuzzy"] = fuzzy_yaz(sa, {h(1): (20, bytes([1] * 8)), h(13): (30, bytes(range(8, 24))), h(11): (22, bytes(16))})
    assert guvenli_mi(B, A) is None
    j, say, degisen, elenen = ekle_eksik(B, A)
    e, s = j["entries"], j["segments"]
    assert e[h(1)] == "onların1"                       # ortak: onlarinki
    assert e[h(2)] == "Lucia: " + soz.strip()          # bizim konusmaci onegi korunur
    assert e[h(3)] == "bizim3"                         # onlarinki bos: istisna
    assert e[h(4)] == "onların parça4" and h(4) not in s   # capraz: bizim tabloda tek deger
    assert s[h(5)] == "tam satır" and h(5) not in e    # capraz: entries'e eklenmez (golgelemez)
    assert s[h(6)] == "Parça altı."                    # dil etiketi soyuldu
    assert e[h(9)] == "yalniz biz"
    assert e[h(10)] == "Hadi gidelim!" and e[h(12)] == "Jason: Dur orada!"
    assert h(11) not in e and elenen == {h(11): "denetim"}
    assert s[h(13)] == "yeni parça"
    assert say["istisna"] == 1 and say["soyulan_etiket"] == 3 and say["eklenen_anahtar"] == 3, say
    assert say["capraz_bizE_onlarS"] == 1 and say["capraz_bizS_onlarE"] == 1
    assert j["speakers"] == ["Lucia"] and j["source"] == "eski; ek ve öncelikli satırlar: asil kaynak"
    imza = fuzzy_coz(j)
    assert imza[h(1)] == (20, bytes(8)) and imza[h(13)] == (30, bytes(range(8, 24))) and h(11) not in imza
    assert j["fuzzy"]["count"] == len(set(e) | set(s)) == 10
    hata, o = ekle_eksik_denetle(B, A, j)
    assert not hata, hata
    assert o["ortak_istisna_bizim"] == 1 and o["elenen_anahtar"] == 1
    # denetim bozulmayi yakalar
    j2 = json.loads(json_bayt(j))
    j2["entries"][h(9)] = "değişti"
    assert ekle_eksik_denetle(B, A, j2)[0]
    assert konusmaci_uyumu("Tarih: 12 Mart", "Lucia:" + soz)[0] == "Tarih:" + soz
    assert konusmaci_uyumu("Biliyorum: araba sigortası.", "Buldum, araba sigortası!", {"Lucia"})[0] is None
    assert konusmaci_uyumu("Personel Tamam, görüşürüz.", "Staff Member: Peki, görüşürüz.")[0] is None
    assert konusmaci_uyumu("Selam.", "Merhaba.") == ("Merhaba.", "aynı")
    assert konusmaci_uyumu("İspanyolca: Dur orada!", "Orada dur!")[0] == "Orada dur!"
    assert konusmaci_uyumu("Lucia: Dur!", "Lucia, dur!", {"Lucia"})[0] is None
    assert konusmaci_uyumu("Lucia: Dur!", "Dur hemen!", {"Lucia"})[0] == "Lucia: Dur hemen!"
    assert dil_soy("Bilinmeyen dil: Bu ne?") == ("Bu ne?", True) and dil_soy("Lucia: İspanyolca: Dur!") == ("Lucia: Dur!", True)
    assert dil_soy("İspanyolca: Rusça: Dur!") == ("Dur!", 2)
    assert dil_temizle("Ne oldu? İspanyolca: Dur!") == ("Ne oldu? Dur!", 1)
    assert dil_temizle("İspanyolca: Hey! Lucia: Rusça: Dur.") == ("Hey! Lucia: Dur.", 2)
    assert dil_temizle("İspanyolca konuşuyor. In Spanish: hey") == ("İspanyolca konuşuyor. In Spanish: hey", 0)
    assert dil_temizle("Rusça: ") == ("Rusça: ", 0) and dil_temizle("Bak: İspanyolca: x") == ("Bak: x", 1)
    assert dil_soy("Ne oldu? İspanyolca: Dur!") == ("Ne oldu? İspanyolca: Dur!", False)
    assert gz_yaz(json_bayt(j)) == gz_yaz(json_bayt(ekle_eksik(B, A)[0]))
    # Arapca dil etiketi
    assert dil_temizle("بالإسبانية: هيه! من هنا.", "ar") == ("هيه! من هنا.", 1)
    assert dil_temizle("انقلع! بالإسبانية: اخرج.", "ar") == ("انقلع! اخرج.", 1)
    assert dil_temizle("ما هذا؟ بلغة غير معروفة: تعال", "ar") == ("ما هذا؟ تعال", 1)
    assert dil_temizle("حسنًا، بالإسبانية: لا", "ar")[1] == 0 and dil_temizle("بالإسبانية: ", "ar")[1] == 0
    assert dil_temizle("İspanyolca: Dur!", "ar")[1] == 0 and dil_temizle("بالإسبانية: لا", "tr")[1] == 0
    pa = {"format": 2, "id": "x-ar", "lang": "ar", "source": "k", "entries": {h(1): "بالروسية: نعم.", h(2): "لا"},
          "segments": {h(3): "بالإسبانية: بالإسبانية: هيا!"}}
    pa["fuzzy"] = fuzzy_yaz([h(1), h(2), h(3)], {h(2): (20, bytes(8))})
    ja, sa_, _ = etiket_soy(pa, "ar")
    assert ja["entries"] == {h(1): "نعم.", h(2): "لا"} and ja["segments"] == {h(3): "هيا!"} and sa_["soyulan_etiket"] == 3
    assert ja["fuzzy"] == pa["fuzzy"] and ja["lang"] == "ar" and ja["source"] == "k; dil etiketleri ayıklandı"
    assert not etiket_soy_denetle(pa, ja, "ar")[0]
    # paket anahtari uygulamanin PackKey'iyle ayni (golden-vectors.json'dan)
    for metin, anahtar in (("You fucked up now, boy!", "e7f18c8f6d1083ab"), ("Caffè, per favore.", "68994b0ce45add3a"),
                           ("<b><h>SCANNATURI SPECIALE</></> KNIFE", "1e9ae63d544282c4"), ("İstanbul", "751c59fe1fa734e6"),
                           ("ENZO: Don Torrisi wants you.", "025d21d2f072b4a5"), ("Ｆｕｌｌ　ｗｉｄｔｈ ５", "ff5126e112d609b8")):
        assert paket_anahtari(metin) == anahtar, metin
    assert paket_anahtari("...") is None and not kaynakla_ayni(h(1), None)
    # kaynakla ayni: onlarin degeri Ingilizceyle ayni, bizimki degil -> konusmada bizimki kalir, ozel adda onlarinki;
    # bizimki de ayniysa onlarinki; yalniz onlarda olana ve konusmaci onekli Ingilizce degere de kural ayni bakar
    for v in ("Hey.", "Hey, Jay.", "Hey!", "Hey, Arnold:", "Hey Arnold!", "lol", "LOL", "Jimmy Snorts.", "Jimmy snorts.",
              "Hey, Jay!", "Banshee?", "Oxies, Percs, Xans...", "Little Cuba, 3rd Avenue? Now."):
        assert konusma_mi(v), v
    for v in ("Ali", "Kelly Hoops /", "Martha & Lyle", "Port Gellhorn Motel", "Saint Attaway Islands", "Hamlet Jetty",
              "T.H. Power Station", "THE INKED MERMAID", "The Inked Mermaid", '"All-Denim" Callaghan', "Princess",
              "Vice Beach St.", "Broke Peak Trail.", "Port of Gellhorn", "Pay 'n' Spray", "Little Cuba, 3rd Avenue.",
              "VCIA S. Terminal", "Zenshin Blade 3", "ft", "mph", "mi", "3 - 10 lbs", "caprice canal", "the kalaga",
              "fuckuthought", "gotthosemunchies", "#thedeepwall lol", "starfish", '"The Ogdoad that Never Comes"'):
        assert not konusma_mi(v), v
    # bizim degere gore: ad sozcuklerinden olusan deger, bizimki de ad gibiyse ad; bizimki cumle cevirisiyse konusma
    for v, bizim, beklenen in (("Andrew Node?", "Andrew!!!", False), ("Kenton. Sir Todd.", "Kenton. Efendim Todd.", False),
                               ("Vice Dale Water and Sewage. Westbrook Drive. Salton.",
                                "Vice Dale Su ve Kanalizasyon. Westbrook Drive. Salton.", False),
                               ("Cartagena.", "Cartagena'ya.", False), ("Count Fuckula.", "Kont Sikula mı?", False),
                               ('"The Ogdoad that Never Comes"', '"Hiç Gelmeyen Ogdoad"', False),
                               ("Jimmy Snorts.", "Jimmy burnunu çekiyor.", True), ("Hey.", "Selam.", True),
                               ("Hey, Jay.", "Selam, Jay.", True), ("Hey Arnold!", "Selam Arnold!", True),
                               ("Hey, Arnold:", "Selam Arnold!", True), ("lol", "Hahaha.", True), ("LOL", "Hahaha.", True),
                               ("Big Bertha!", "Büyük Bertha!", True), ("35mm?", "35mm mi?", True), ("0.9kg!", "0,9 kilo!", True),
                               ("Princess", "Prenses?", False), ("Ali", "Bira?", False), ("ft", "Hı..", False),
                               ("Joe?", "Joe mu?", True), ("Camila Fuentes? Giorgio Gallo?", "Camila Fuentes mi? Giorgio Gallo mu?", True),
                               ("Mister Mangrove???", "Bay Mangrove???", False)):
        assert konusma_mi(v, bizim) is beklenen, (v, bizim)
    k = paket_anahtari
    B2 = {"format": 2, "id": "y", "title": "Y", "speakers": ["Jason"],
          "entries": {k("Hey."): "Selam.", k("lol"): "Hahaha.", k("Okay."): "Okay", k("Run!"): "Koş!",
                      k("Jason: Hey."): "Jason: Selam.", k("Go."): "İspanyolca: Go!", k("Princess"): "Prenses?"},
          "segments": {k("THE INKED MERMAID"): "Mürekkepli Deniz Kızı", k("Jimmy snorts."): "Jimmy burnunu çekiyor."}}
    A2 = {"format": 2, "id": "y", "title": "Y",
          "entries": {k("Hey."): "Hey!", k("lol"): "LOL", k("Okay."): "OK.", k("Run!"): "Kaç!", k("Wait."): "Wait!",
                      k("Jason: Hey."): "Jason: HEY!", k("Go."): "GO", k("THE INKED MERMAID"): "The Inked Mermaid",
                      k("Princess"): "Princess", k("Jimmy snorts."): "Jimmy Snorts."}}
    j3, say3, _, _ = ekle_eksik(B2, A2)
    e3, s3 = j3["entries"], j3["segments"]
    assert e3[k("Hey.")] == "Selam." and e3[k("lol")] == "Hahaha." and e3[k("Jason: Hey.")] == "Jason: Selam."
    assert s3[k("Jimmy snorts.")] == "Jimmy burnunu çekiyor."                 # capraz konusma: bizimki
    assert s3[k("THE INKED MERMAID")] == "The Inked Mermaid" and e3[k("Princess")] == "Princess"   # ad: onlarinki
    assert e3[k("Okay.")] == "OK." and e3[k("Run!")] == "Kaç!" and e3[k("Wait.")] == "Wait!"
    assert e3[k("Go.")] == "GO"                                                # bizimki de (etiket soyulunca) ayni
    assert (say3["kaynakla_ayni_entries"], say3["kaynakla_ayni_segments"]) == (3, 1), say3
    assert (say3["kaynakla_ayni_ad_entries"], say3["kaynakla_ayni_ad_segments"]) == (1, 1), say3
    assert say3["nedenler"]["istisna: onların değeri kaynakla aynı (konuşma)"] == 4
    hata3, o3 = ekle_eksik_denetle(B2, A2, j3)
    assert not hata3, hata3
    assert o3["ortak_onlarinki_kaynakla_ayni_bizimki_kaldi"] == 4, o3
    j4 = json.loads(json_bayt(j3))
    j4["entries"][k("Hey.")] = "Hey!"                                         # kural bozulursa denetim yakalar
    assert any("kaynakla aynı" in x for x in ekle_eksik_denetle(B2, A2, j4)[0])
    print("ekle-eksik sınaması geçti")


def dil_ayrimi_sina():
    """Dile gore ayri listeler: ana liste yalniz tr; ar ayri agac; lang'siz paket tr; kaynaktaki ar paketi ana listeye
    sizmaz; kapi dil basina. Gecici klasor aracin yaninda acilir ve silinir (sistem Temp'i kullanilmaz)."""
    import shutil
    import tempfile
    from types import SimpleNamespace
    assert paket_dili("a", {}) == "tr" and paket_dili("a", {"lang": "AR"}) == "ar"
    assert paket_dili("a", {}, "ar") == "ar" and paket_dili("a", {"lang": "ar"}, "tr") == "ar"
    assert paket_dili("a", {"lang": "t r"}) is None and paket_dili("a", {"lang": "tr"}, "") == "tr"
    tmp = tempfile.mkdtemp(prefix=".dil-sina-", dir=os.path.dirname(os.path.abspath(__file__)))
    eski_http, eski_cikis = globals()["http_al"], os.environ.pop("GITHUB_OUTPUT", None)
    try:
        def paket(kimlik, dil=None, satir=3):
            d = {"format": 2, "id": kimlik, "title": kimlik.upper(),
                 "entries": {"%016x" % i: "satır %d" % i for i in range(1, satir + 1)}}
            if dil:
                d["lang"] = dil
            return gz_yaz(json_bayt(d))
        girdi = os.path.join(tmp, "girdi")
        os.makedirs(girdi)
        for kimlik, dil in (("oyun", None), ("oyun2", "tr"), ("oyun-ar", "ar"), ("pool-oyun", None)):
            open(os.path.join(girdi, kimlik + ".json.gz"), "wb").write(paket(kimlik, dil))
        cikti = os.path.join(tmp, "cikti")
        dizinler, _, _ = uret_hedefe(girdileri_tara([girdi]), cikti, {}, 1, True)
        ana = json.loads(open(os.path.join(cikti, "index.json"), "rb").read())["packs"]
        ar = json.loads(open(os.path.join(cikti, "packs-ar", "index.json"), "rb").read())["packs"]
        assert [p["id"] for p in ana] == ["oyun", "oyun2"] and all(p["lang"] == "tr" for p in ana), ana
        assert [p["id"] for p in ar] == ["oyun-ar"] and ar[0]["lang"] == "ar"
        v1 = os.path.join(cikti, "v1")
        assert open(os.path.join(v1, "packs", "index.html"), "rb").read() == open(os.path.join(cikti, "index.json"), "rb").read()
        assert open(os.path.join(v1, "packs-ar", "index.html"), "rb").read() == open(os.path.join(cikti, "packs-ar", "index.json"), "rb").read()
        assert open(os.path.join(v1, "packs-ar", "oyun-ar"), "rb").read() == paket("oyun-ar", "ar")
        assert not os.path.exists(os.path.join(v1, "packs", "oyun-ar")) and not glob.glob(os.path.join(cikti, "oyun-ar*"))
        try:
            denetle(SimpleNamespace(girdi=[girdi], cikti=cikti))
        except SystemExit:
            raise AssertionError("dil ağaçlı çıktının denetimi geçmedi")
        # --paket-dili: lang'siz paketi elle bir dile koymak
        DIL_ZORLA["oyun2"] = "ar"
        try:
            d2, _, _ = uret_hedefe(girdileri_tara([girdi]), os.path.join(tmp, "zorla"), {}, 1, False)
            assert [p["id"] for p in d2["ar"]] == ["oyun-ar", "oyun2"] and [p["id"] for p in d2["tr"]] == ["oyun"]
        finally:
            DIL_ZORLA.pop("oyun2")
        # --indir: kaynak listesinde ar olan (dosyasinda lang olmasa bile) ana listeye girmez; kapi dil basina
        kaynak = {"oyun": (paket("oyun"), "tr"), "oyun-ar": (paket("oyun-ar", "ar"), "ar"), "sizan": (paket("sizan"), "ar"),
                  "bozuk-dil": (paket("bozuk-dil"), "a r")}
        def sahte_http(url, zaman_asimi, etag=None, deneme=2, bekle=2.0):
            if url.endswith("/v1/packs"):
                return json_bayt({"packs": [{"id": k, "sha256": sha(b), "size": len(b), "lang": l}
                                            for k, (b, l) in sorted(kaynak.items())]}), None
            return kaynak[url.rsplit("/", 1)[1]][0], None
        globals()["http_al"] = sahte_http
        yayin = os.path.join(tmp, "yayin")
        args = SimpleNamespace(indir="http://sahte", kaynak=os.path.join(tmp, "kaynak"), girdi_ek=None, cikti=yayin,
                               surum=1, bekle=0, zaman_asimi=1)
        indir_kipi(args)
        ana = [p["id"] for p in json.loads(open(os.path.join(yayin, "index.json"), "rb").read())["packs"]]
        ar = [p["id"] for p in json.loads(open(os.path.join(yayin, "packs-ar", "index.json"), "rb").read())["packs"]]
        assert ana == ["oyun"] and ar == ["oyun-ar", "sizan"], (ana, ar)
        assert sorted(os.listdir(os.path.join(yayin, "v1", "packs"))) == ["index.html", "oyun"]
        assert sorted(os.listdir(os.path.join(yayin, "v1", "packs-ar"))) == ["index.html", "oyun-ar", "sizan"]
        once = dizin_dosyalari(yayin)
        for dusen, beklenen_ad in (("oyun-ar", "packs-ar"), ("oyun", "packs:")):
            yedek = kaynak.pop(dusen)
            try:
                indir_kipi(args)
                raise AssertionError("kapı çalışmadı: " + dusen)
            except SystemExit as e:
                assert "YAYINLANMADI" in str(e) and beklenen_ad in str(e), str(e)
            kaynak[dusen] = yedek
            assert dizin_dosyalari(yayin) == once, "kapı sonrası yayın değişti"
        indir_kipi(args)  # kaynak eski haline dondu: degisiklik yok
        assert dizin_dosyalari(yayin) == once
        # eski yayinda ana listeye sizmis ar paketi: packs-ar'a tasinir, kapi bunu kayip saymaz
        ind = json.loads(open(os.path.join(yayin, "index.json"), "rb").read())
        ind["packs"].append({"id": "oyun-ar", "title": "X", "version": 1, "sha256": "0" * 64, "size": 1, "entries": 3})
        open(os.path.join(yayin, "index.json"), "wb").write(json_bayt(ind))
        indir_kipi(args)
        assert [p["id"] for p in json.loads(open(os.path.join(yayin, "index.json"), "rb").read())["packs"]] == ["oyun"]
        # --katki: kaynak aynalanir, katki her kosuda yeniden uygulanir; surum yalniz icerik degisince ve ileri gider
        def surum(k):
            return {p["id"]: p for p in json.loads(open(os.path.join(yayin, "index.json"), "rb").read())["packs"]}[k]["version"]
        def deger(k, anahtar):
            return oku(os.path.join(yayin, k + ".json.gz"))[1]["entries"].get(anahtar)
        KATKI["oyun"] = ("", b"", {"format": 2, "id": "oyun", "lang": "tr", "source": "katkı kaynağı",
                                   "entries": {"%016x" % 1: "katkı bir", "%016x" % 9: "İspanyolca: katkı dokuz"}})
        try:
            v0 = surum("oyun")
            indir_kipi(args)
            assert surum("oyun") == v0 + 1 and deger("oyun", "%016x" % 1) == "katkı bir"
            assert deger("oyun", "%016x" % 9) == "katkı dokuz" and deger("oyun", "%016x" % 2) == "satır 2"
            once = dizin_dosyalari(yayin)
            indir_kipi(args)  # ikinci kosu: degisiklik yok (katki ezilmez, surum ayni)
            assert dizin_dosyalari(yayin) == once and surum("oyun") == v0 + 1
            try:
                denetle(SimpleNamespace(girdi=[os.path.join(tmp, "kaynak")], cikti=yayin))
            except SystemExit:
                raise AssertionError("katkılı yayının denetimi geçmedi")
            kaynak["oyun"] = (paket("oyun", satir=4), "tr")  # kaynak guncellendi: yeni satir gelir, katki yerinde
            indir_kipi(args)
            assert surum("oyun") == v0 + 2 and deger("oyun", "%016x" % 4) == "satır 4" and deger("oyun", "%016x" % 1) == "katkı bir"
            # onceki yayin okunamazsa surumler geri gitmesin: yayinlanmaz
            bos = SimpleNamespace(**dict(vars(args), cikti=os.path.join(tmp, "bos"), onceki_gerekli=True))
            try:
                indir_kipi(bos)
                raise AssertionError("önceki yayın yokken yayınlandı")
            except SystemExit as e:
                assert "önceki yayının listesi" in str(e)
        finally:
            KATKI.pop("oyun", None)
    finally:
        globals()["http_al"] = eski_http
        if eski_cikis is not None:
            os.environ["GITHUB_OUTPUT"] = eski_cikis
        shutil.rmtree(tmp, ignore_errors=True)
    print("dil ayrımı sınaması geçti")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--girdi", action="append", help="paket klasoru (birden cok); ilk klasor oncelikli")
    ap.add_argument("--atif-ek", help="ATIF.md sonuna ozgun hâliyle eklenecek sabit atif metni dosyasi")
    ap.add_argument("--cikti", default=VARSAYILAN_CIKTI)
    ap.add_argument("--surum", type=int, default=1)
    ap.add_argument("--v1", action="store_true")
    ap.add_argument("--denetle", action="store_true")
    ap.add_argument("--kendini-sina", action="store_true")
    ap.add_argument("--indir", metavar="TABAN_ADRES", help="kaynak sunucudan yalniz degisen paketleri indirip birlestirir")
    ap.add_argument("--kaynak", default="kaynak", help="--indir: indirilen ham paketlerin onbellek klasoru")
    ap.add_argument("--girdi-ek", action="append", help="--indir: kaynakta olmayan ek paket klasorleri")
    ap.add_argument("--bekle", type=float, default=1.0, help="--indir: indirmeler arasi bekleme (sn)")
    ap.add_argument("--zaman-asimi", type=float, default=60.0)
    ap.add_argument("--paket-dili", action="append", metavar="KIMLIK=DIL",
                    help="paketi elle bir dile koyar (ör. oyun-ar=ar); yoksa paketin lang alani, o da yoksa tr")
    ap.add_argument("--ekle-eksik", action="store_true", help="--biz paketine --asil paketini ekler (ortakta asil kazanir)")
    ap.add_argument("--biz", help="--ekle-eksik: bizim paket dosyasi")
    ap.add_argument("--asil", help="--ekle-eksik: eklenecek paket dosyasi")
    ap.add_argument("--ornek", help="--ekle-eksik/--etiket-soy: rastgele degisen satir ornegi dosyasi")
    ap.add_argument("--katki", action="append", help="katki paketleri klasoru: ayni kimlikli pakete --ekle-eksik kurali uygulanir")
    ap.add_argument("--onceki-gerekli", action="store_true", help="--indir: onceki yayinin listesi yoksa yayinlama")
    ap.add_argument("--etiket-soy", metavar="DOSYA", help="paketin degerlerindeki dil etiketlerini soyar (--cikti klasorune)")
    args = ap.parse_args()
    global ATIF_EK
    ATIF_EK = args.atif_ek
    for x in args.paket_dili or []:
        kimlik, _, dil = x.partition("=")
        if not KIMLIK.match(kimlik) or dil_kodu(dil) in (None, "?"):
            ap.error("--paket-dili kimlik=dil biçiminde olmalı: " + x)
        DIL_ZORLA[kimlik] = dil_kodu(dil)
    if args.kendini_sina:
        kendini_sina()
        ekle_eksik_sina()
        return dil_ayrimi_sina()
    for klasor in args.katki or []:
        for k, v in girdileri_tara([klasor]).items():
            KATKI.setdefault(k, v)
    if args.etiket_soy:
        if args.cikti == VARSAYILAN_CIKTI:
            ap.error("--etiket-soy icin --cikti gerekli")
        return etiket_soy_kipi(args)
    if args.ekle_eksik:
        if not (args.biz and args.asil) or args.cikti == VARSAYILAN_CIKTI:
            ap.error("--ekle-eksik icin --biz, --asil ve --cikti gerekli")
        return ekle_eksik_kipi(args)
    if args.indir:
        return indir_kipi(args)
    if not args.girdi:
        ap.error("--girdi gerekli")
    if args.denetle:
        return denetle(args)
    uret(args)


if __name__ == "__main__":
    main()
