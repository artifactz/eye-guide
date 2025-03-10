import re, os, json
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont, TTFError


class FontIsExtraboldException(Exception):
    """The specified font is already Extrabold, no bolder version available."""


FONT_DIR = f'{os.path.dirname(__file__)}/fonts'


# font name synonyms, i.e. mapping to font file name
FONT_MAP = {
    "CMSS(\d|\d\d)": "ComputerModernSans",
    "CMR(\d|\d\d)": "ComputerModernSerif",
    "CMTI(\d|\d\d)": "ComputerModernSerif-Italic",
    "CMBX(\d|\d\d)": "ComputerModernSerif-Bold",
    "DGMetaSerifScience": "DeGruyterSerif",
    "DGMetaScience": "DeGruyterSans",
    "STIXGeneral": "STIXTwoText",
    "Times": "TimesNewRoman",
    "TimesNewer": "TimesNewerRoman",
}


# Reportlab comes with the Helvetica font, so we don't need to register it.
_registered_fonts = ['Helvetica', 'Helvetica-Bold', 'Helvetica-BoldOblique']
_missing_fonts = []
_remapped_fonts = {}


def setup_boldened_font(canvas, pdf_font_identifier: str, size: float, use_extrabold: bool) -> bool:
    """
    Sets up a boldened version of a font for overlay.
    """

    # if pdf_font_identifier == "KPCEMI+VectoraLH-Roman":
    #     print("break")

    identifier = _disambiguate_identifier(pdf_font_identifier)
    if remapping := _get_remapping(identifier):
        identifier = remapping["overlay_font"]
        size *= remapping["font_scale"]
        canvas._char_offsets = remapping["offsets"] if "offsets" in remapping else None
        if "offsets" in remapping:
            canvas._char_offsets = {k: (v[0][0] * size, v[0][1] * size) for k, v in remapping["offsets"].items()}
        else:
            canvas._char_offsets = None
    else:
        canvas._char_offsets = None
        try:
            identifier = _bolden(identifier)
        except FontIsExtraboldException:
            return None

    if not use_extrabold and "Extrabold" in identifier:
        return None

    identifier = _handle_helvetica(identifier)

    if identifier in _missing_fonts:
        return None

    if identifier not in _registered_fonts:
        # if identifier == "TimesNewerRoman-Bold":
        #     print("break")
        try:
            pdfmetrics.registerFont(TTFont(identifier, f"{FONT_DIR}/{identifier}.ttf"))
        except TTFError:
            print(f"Missing font: {identifier}")
            _missing_fonts.append(identifier)
            return None
        _registered_fonts.append(identifier)

    canvas.setFont(identifier, size)
    return (identifier, size)


def _get_remapping(identifier: str) -> dict:
    """
    Returns a font remapping.
    """
    _init_remapped_fonts()
    if identifier in _remapped_fonts:
        if _remapped_fonts[identifier] is None:
            with open(f"remap/{identifier}.json", "r") as f:
                _remapped_fonts[identifier] = json.load(f)
        return _remapped_fonts[identifier]


def _init_remapped_fonts():
    """
    Scans remap/ folder for remapped fonts.
    """
    if _remapped_fonts:
        return
    for file in os.listdir("remap"):
        if file.endswith(".json"):
            identifier = file.removesuffix(".json")
            _remapped_fonts[identifier] = None


def _disambiguate_identifier(pdf_identifier: str) -> str:
    """
    Cleans up a PDF font identifier.
    """
    family_name = pdf_identifier

    # Strip gibberish prefix such as "XNOPQH+"
    if m := re.match(r"^[A-Z]+\+(.+)$", family_name):
        family_name = m.group(1)

    # Remove spaces
    family_name = family_name.replace(" ", "")

    # Remove trailing digits (e.g. "Corbel3", not yet encountered though: "Corbel3-Bold")
    family_name = re.sub(r"(\d+)$", "", family_name)

    # Split into family name and modifiers
    splitter = "-" if "-" in family_name else ","
    splits = family_name.split(splitter, maxsplit=1)
    family_name = splits[0]

    # Strip Monotype suffix
    family_name = family_name.removesuffix("MT")

    # Strip PostScript suffix
    family_name = family_name.removesuffix("PS")

    # Attempt replacement via FONT_MAP
    for pattern, replacement in FONT_MAP.items():
        if m := re.match(f"^{pattern}$", family_name):
            family_name = replacement
            break

    if len(splits) == 1:
        family_name, modifiers = _disambiguate_capital_modifiers(family_name)
        if modifiers:
            return f"{family_name}-{modifiers}"
        return family_name

    if modifiers := _disambiguate_modifiers(splits[1]):
        return f"{family_name}-{modifiers}"

    # Assuming modifier is Regular, Roman, or similar
    return family_name


def _disambiguate_modifiers(pdf_modifiers: str):
    pdf_modifiers = pdf_modifiers.lower()  # TODO given the increasing number of formats, verify if really needed
    weight = ""
    italic = ""
    if "light" in pdf_modifiers:
        weight = "Light"
    elif "semibold" in pdf_modifiers:
        weight = "Semibold"
    elif "extrabold" in pdf_modifiers or "black" in pdf_modifiers:
        weight = "Extrabold"
    elif "bold" in pdf_modifiers:
        weight = "Bold"
    if "ital" in pdf_modifiers or "oblique" in pdf_modifiers or "slant" in pdf_modifiers:
        italic = "Italic"
    return weight + italic


def _disambiguate_capital_modifiers(font_name: str):
    """
    Sometimes font modifiers are a suffix of uppercase characters.
    Returns the stripped font name and its modifiers.
    """
    weight = ""
    italic = ""
    if font_name.endswith("TI"):
        font_name = font_name.removesuffix("TI")
        italic = "Italic"
    if font_name.endswith("TB"):
        font_name = font_name.removesuffix("TB")
        weight = "Bold"
    if font_name.endswith("T"):  # regular
        font_name = font_name.removesuffix("T")
    return font_name, weight + italic


def _bolden(identifier: str):
    """
    Returns a bolded version of a disambiguated identifier.
    """
    if "-" not in identifier:
        return identifier + "-Bold"
    family_name, modifiers = identifier.split("-", maxsplit=1)
    if "Extrabold" in modifiers:
        raise FontIsExtraboldException
    if "Light" in modifiers:
        return family_name + "-Italic" if "Italic" in modifiers else family_name
    if "Semibold" in modifiers:
        modifiers = modifiers.replace("Semibold", "Bold")
    elif "Bold" in modifiers:
        modifiers = modifiers.replace("Bold", "Extrabold")
    else:
        assert modifiers == "Italic"
        modifiers = "BoldItalic"
    return f"{family_name}-{modifiers}"


def _handle_helvetica(identifier: str):
    """
    In reportlab's Helvetica, "italic" is called "oblique".
    Returns fixed Helvetica identifier, or the unchanged identifier for other fonts.
    """
    if identifier == "Helvetica-Italic":
        return "Helvetica-Oblique"
    if identifier == "Helvetica-BoldItalic":
        return "Helvetica-BoldOblique"
    return identifier
