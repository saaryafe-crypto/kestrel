"""Composed-cover engine (owner gold standard Aug 1, @getintoai anatomy):
cut the REAL famous person out of a scraped press photo (rembg, local, free)
so the renderer can stack backdrop < logo discs < person cutout. The face is
never generated (owner rule Aug 1: unfamiliar AI faces = low conversion) —
this module only re-composes real photographs. Every gate falls back to the
plain photo cover; a slot never dies here."""
import os
import sys


def person_layer(src, dst):
    """Full-frame person layer for SITUATION covers (owner Aug 3: "logos
    always behind the face... prioritize the person"): same canvas as src,
    every non-person pixel transparent. The renderer draws src full-bleed,
    stamps the logo discs, then draws THIS on top with the identical
    cover-crop CSS — pixel-perfect alignment, so the person occludes any
    disc they collide with (the technology-page anatomy: logos live behind
    the person). Returns dst or None; on None the discs simply render on
    top as before — a slot never dies here."""
    try:
        from rembg import remove
        from PIL import Image
        img = Image.open(src).convert("RGB")
        out = remove(img)
        a = out.getchannel("A")
        solid = sum(a.histogram()[200:]) / (out.width * out.height)
        # generated situation scenes run person-dominant; same sanity band
        # as cutout(): outside it rembg grabbed the wrong subject
        if not 0.08 <= solid <= 0.90:
            print(f"person_layer rejected: alpha coverage {solid:.2f}",
                  file=sys.stderr)
            return None
        out.save(dst)
        return dst
    except Exception as e:
        print(f"person_layer failed ({e})", file=sys.stderr)
        return None


def cutout(src, dst):
    """Person cutout: src photo -> dst RGBA png cropped to the subject.
    Returns dst on success, None on any failure/rejection."""
    try:
        from rembg import remove
        from PIL import Image
        img = Image.open(src).convert("RGB")
        out = remove(img)
        a = out.getchannel("A")
        # coverage sanity: a clean chest-up person fills 8-85% of the frame;
        # outside that rembg latched onto the wrong subject (or everything)
        solid = sum(a.histogram()[200:]) / (out.width * out.height)
        if not 0.08 <= solid <= 0.85:
            print(f"cutout rejected: alpha coverage {solid:.2f}", file=sys.stderr)
            return None
        # crop to the subject so the renderer can size the person, ignoring
        # faint halo pixels (threshold 30) that would inflate the box
        bbox = a.point(lambda v: 255 if v > 30 else 0).getbbox()
        if not bbox:
            return None
        out = out.crop(bbox)
        if out.height < 380 or out.width < 300:
            print(f"cutout rejected: subject too small ({out.width}x{out.height})",
                  file=sys.stderr)
            return None
        out.save(dst)
        return dst
    except Exception as e:
        print(f"cutout failed ({e})", file=sys.stderr)
        return None
