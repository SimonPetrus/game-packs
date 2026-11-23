#!/usr/bin/env python3
"""Oyun ceviri paketlerini birlestirir: pool-<kimlik> (ek satirlar) + <kimlik> (asil) -> tek paket.

Yalniz standart kitaplik. Kullanim:
  python3 -I paket_birlestir.py --girdi KLASOR [--girdi ...] [--cikti KLASOR] [--surum N] [--v1]
  python3 -I paket_birlestir.py --denetle [--girdi ...] [--cikti ...]
  python3 -I paket_birlestir.py --kendini-sina
  python3 -I paket_birlestir.py --indir https://kaynak --kaynak kaynak --cikti yayin   (GitHub Actions)

--girdi birden cok verilebilir; ayni kimlik birden cok klasorde varsa ILK klasordeki kazanir.
--v1: ek olarak uygulamanin simdiki adres duzenini (v1/packs, v1/packs/<kimlik>) de yazar (GitHub Pages icin).
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


def uret_hedefe(paketler, hedef, onceki, ilk_surum, v1):
    """Paketleri hedef klasore yazar (hedefteki eski *.json.gz silinir). Doner: (dizin listesi, plan, ayri)."""
    plan, ayri = plan_yap(paketler)
    os.makedirs(hedef, exist_ok=True)
    for eski in glob.glob(os.path.join(hedef, "*.json.gz")):
        os.remove(eski)
    dizin = []
    for kimlik, tur, bayt, d, bilgi in plan:
        with open(os.path.join(hedef, kimlik + ".json.gz"), "wb") as f:
            f.write(bayt)
        h = sha(bayt)
        o = onceki.get(kimlik)
        # Surum: icerik ayniysa onceki surum, degistiyse bir fazlasi (belirlenimci); app yalniz esitlige bakar.
        surum = ilk_surum if not o else (o["version"] if o.get("sha256") == h else int(o["version"]) + 1)
        dizin.append({"id": kimlik, "title": d.get("title") or kimlik, "version": surum, "sha256": h,
                      "size": len(bayt), "entries": len(d["entries"])})
        print("%-34s %-12s satır=%d boyut=%d%s" % (kimlik, tur, len(d["entries"]), len(bayt),
              (" ana=%d ek=%d çakışma=%d [%s]" % (bilgi["ana_satir"], bilgi["ek_satir"], bilgi["cakisma"], bilgi["yontem"])) if bilgi else ""))
    ind = json_bayt({"packs": dizin})
    with open(os.path.join(hedef, "index.json"), "wb") as f:
        f.write(ind)
    atif_yaz(os.path.join(hedef, "ATIF.md"), plan, paketler, None)
    if v1:  # uygulamanin simdiki adresleri: GET /v1/packs ve /v1/packs/<kimlik>
        kok = os.path.join(hedef, "v1", "packs")
        os.makedirs(kok, exist_ok=True)
        with open(os.path.join(kok, "index.html"), "wb") as f:  # /v1/packs/ -> JSON (Pages dizin dosyasi)
            f.write(ind)
        for kimlik, _, bayt, _, _ in plan:
            with open(os.path.join(kok, kimlik), "wb") as f:
                f.write(bayt)
    return dizin, plan, ayri


def uret(args):
    paketler = girdileri_tara(args.girdi)
    for k in paketler:
        if not KIMLIK.match(k):
            sys.exit("Güvenli olmayan kimlik: " + k)
    dizin, plan, ayri = uret_hedefe(paketler, args.cikti, onceki_surumler(args.cikti), args.surum, args.v1)
    for kimlik, havuz, neden in ayri:
        print("BİRLEŞTİRİLEMEDİ: %s + %s -> %s" % (kimlik, havuz, neden))
    print("toplam çıktı boyutu: %d bayt" % sum(os.path.getsize(p) for p in glob.glob(os.path.join(args.cikti, "*.json.gz"))))


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
    """Kaynak index'ini alir, yalniz degisen paketleri indirir. Doner: indirilen kimlikler. Hata -> KaynakHatasi."""
    import time
    taban = taban.rstrip("/")
    govde, _ = http_al(taban + "/v1/packs", zaman_asimi)
    try:
        liste = json.loads(govde)["packs"]
        assert isinstance(liste, list) and liste
        liste = [{"id": p["id"], "sha256": str(p["sha256"]).lower(), "size": int(p.get("size", 0))} for p in liste]
    except Exception:
        raise KaynakHatasi("kaynak index'i bozuk")
    liste = [p for p in liste if KIMLIK.match(p["id"]) and re.fullmatch(r"[0-9a-f]{64}", p["sha256"])]
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
        durum[k] = {"sha256": p["sha256"], "etag": etag}
        indirilen.append(k)
    # kaynaktan kalkan paketlerin yerel kopyasi silinir (yayindan da kalkar; sayi kapisi ayrica korur)
    gecerli = {p["id"] for p in liste}
    for yol in glob.glob(os.path.join(klasor, "*.json.gz")):
        if os.path.basename(yol)[:-8] not in gecerli:
            os.remove(yol)
    durum = {k: v for k, v in durum.items() if k in gecerli}
    gecici = durum_yol + ".tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(durum, f, sort_keys=True)
    os.replace(gecici, durum_yol)
    return indirilen


def cikisa_yaz(degisti):
    yol = os.environ.get("GITHUB_OUTPUT")
    if yol:
        with open(yol, "a", encoding="utf-8") as f:
            f.write("degisti=%s\n" % ("true" if degisti else "false"))


def indir_kipi(args):
    import shutil
    try:
        indirilen = kaynak_indir(args.indir, args.kaynak, args.bekle, args.zaman_asimi)
    except KaynakHatasi as e:
        print("UYARI: kaynak alınamadı, hiçbir şey değiştirilmedi: %s" % e)
        cikisa_yaz(False)
        return
    print("kaynaktan indirilen (değişen) paket: %d %s" % (len(indirilen), ",".join(indirilen)))
    paketler = girdileri_tara([args.kaynak] + (args.girdi_ek or []))
    onceki = onceki_surumler(args.cikti)
    yeni = args.cikti.rstrip("/") + ".yeni"
    shutil.rmtree(yeni, ignore_errors=True)
    dizin, plan, ayri = uret_hedefe(paketler, yeni, onceki, args.surum, True)
    # Guvenlik kapilari: bozuk kaynak yayini bozmasin
    sorun = []
    if onceki and len(dizin) < len(onceki):
        sorun.append("paket sayısı azaldı: %d -> %d" % (len(onceki), len(dizin)))
    kayip = sorted(set(onceki) - {p["id"] for p in dizin})
    if kayip:
        sorun.append("önceki yayındaki paket(ler) kayboldu: " + ",".join(kayip))
    for p in dizin:
        o = onceki.get(p["id"])
        if o and p["entries"] < 0.8 * int(o.get("entries", 0)):
            sorun.append("%s: satır sayısı %%80'in altına düştü (%s -> %d)" % (p["id"], o.get("entries"), p["entries"]))
    if sorun:
        shutil.rmtree(yeni, ignore_errors=True)
        cikisa_yaz(False)
        sys.exit("YAYINLANMADI (güvenlik kapısı): " + "; ".join(sorun))
    if onceki and open(os.path.join(yeni, "index.json"), "rb").read() == open(os.path.join(args.cikti, "index.json"), "rb").read():
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
    print("DEĞİŞİKLİK VAR: %d paket yazıldı" % len(dizin))
    cikisa_yaz(True)


def denetle(args):
    paketler = girdileri_tara(args.girdi)
    cift, yalniz = eslestir(paketler)
    hata = []
    ok = 0
    rnd = random.Random(20260123)
    with open(os.path.join(args.cikti, "index.json"), "rb") as f:
        dizin = {p["id"]: p for p in json.loads(f.read())["packs"]}
    havuzlar = {h for h, _ in cift.values()}
    beklenen = {k for k in paketler if k not in havuzlar}
    if set(dizin) != beklenen:
        hata.append("index.json kimlikleri beklenenle aynı değil: fark=%s" % sorted(set(dizin) ^ beklenen))
    for kimlik, p in sorted(dizin.items()):
        yol = os.path.join(args.cikti, kimlik + ".json.gz")
        ham, d = oku(yol)
        if sha(ham) != p["sha256"] or len(ham) != p["size"] or len(d["entries"]) != p["entries"]:
            hata.append(kimlik + ": index.json sha/boyut/satır sayısı dosyayla uyuşmuyor")
        if kimlik not in cift:
            if ham != paketler[kimlik][1]:
                hata.append(kimlik + ": birleştirilmeyen paket girdiyle bayt bayt aynı değil")
            ok += 1
            continue
        a = paketler[kimlik][2]
        e = paketler[cift[kimlik][0]][2]
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
    plan, _ = plan_yap(paketler)
    for kimlik, tur, bayt, _, _ in plan:
        if kimlik in dizin and sha(bayt) != dizin[kimlik]["sha256"]:
            hata.append(kimlik + ": yeniden üretim bayt bayt aynı değil (belirlenimsizlik ya da bayat çıktı)")
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
    args = ap.parse_args()
    global ATIF_EK
    ATIF_EK = args.atif_ek
    if args.kendini_sina:
        return kendini_sina()
    if args.indir:
        return indir_kipi(args)
    if not args.girdi:
        ap.error("--girdi gerekli")
    if args.denetle:
        return denetle(args)
    uret(args)


if __name__ == "__main__":
    main()
