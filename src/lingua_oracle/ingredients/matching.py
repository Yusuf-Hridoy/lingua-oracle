"""Deciding which ExactSDS product, if any, an uploaded sheet is.

A sheet that came out of the application can be checked against the record
behind it; a supplier's sheet cannot, and has to be read on its own terms. The
difference matters enough to be shown in the report rather than assumed, so the
match is made explicitly, the evidence for it is named, and the reader can
change it.

Nothing here writes anything. The search is a GET.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: The labels Section 1 puts in front of the product's name. Several languages,
#: because the application issues sheets in all of them.
_LABELS = (
    r"product\s+name", r"product\s+identifier", r"trade\s+name",
    r"produktname", r"handelsname", r"nom\s+du\s+produit",
    r"nombre\s+del\s+producto", r"nome\s+do\s+produto", r"produktnavn",
    r"productnaam", r"nome\s+commerciale", r"nazwa\s+produktu",
)
_LABEL_RE = re.compile(
    r"^\s*(?:1\.1\.?\s*)?(?:" + "|".join(_LABELS) + r")\s*[:–-]?\s*(?P<value>.*)$",
    re.IGNORECASE)
#: The application names its downloads "<regulation>_<language>_<id>.pdf".
_FILE_ID_RE = re.compile(r"(?:^|[_-])(\d{3,8})(?=\.|_|$)")
#: Boilerplate that follows the label on some sheets instead of a name.
_NOT_A_NAME = re.compile(r"^(see section|n/?a|not applicable|-{1,3})$",
                         re.IGNORECASE)
#: A numbered sub-section or section heading: the next part of the sheet,
#: not a product name.
_HEADING_LIKE = re.compile(r"^\s*\d{1,2}\.\d{1,2}\b|^\s*(?:SECTION|ABSCHNITT|PUNKT|"
                           r"RUBRIQUE)\s+\d", re.IGNORECASE)


def normalised(name: str) -> str:
    """A product name reduced to what two sheets would have to share to be one.

    Case, spacing and the punctuation producers vary freely - "WD-40 Specialist
    (Aerosol)" against "WD 40 Specialist aerosol" - are not differences between
    products.
    """
    return re.sub(r"[^a-z0-9]+", " ", (name or "").casefold()).strip()


@dataclass
class Candidate:
    product_id: int
    name: str
    regulation: str | None = None
    updated_at: str = ""


@dataclass
class Match:
    """What the sheet was matched to, and on what evidence."""

    #: "matched", "ambiguous", "none", or "unavailable" when the app could not
    #: be reached at all.
    state: str
    product_id: int | None = None
    name: str | None = None
    evidence: str = ""
    candidates: list[Candidate] = field(default_factory=list)
    searched_for: str = ""

    @property
    def is_app_product(self) -> bool:
        return self.state == "matched" and self.product_id is not None


def product_id_in_file_name(file_name: str) -> int | None:
    """The product id an application download carries in its name, if any."""
    stem = file_name.rsplit("/", 1)[-1]
    stem = stem[:-4] if stem.lower().endswith(".pdf") else stem
    found = _FILE_ID_RE.findall(stem)
    return int(found[-1]) if found else None


def product_name_in(lines) -> str | None:
    """The product name as Section 1 prints it.

    Taken from the label rather than from position: "Product name" and its
    translations are what a sheet puts in front of the name, and the first bold
    line of a page is as often a logo as a product.
    """
    for index, line in enumerate(lines[:120]):
        match = _LABEL_RE.match(line.text or "")
        if not match:
            continue
        value = " ".join((match.group("value") or "").split())
        if not value or _NOT_A_NAME.match(value):
            # Several producers put the label and the value on separate lines;
            # others head 1.1 "Product identifier" and give the name under its
            # own label, "Product name: ...". A heading or a filler is neither.
            for following in lines[index + 1:index + 3]:
                candidate = " ".join((following.text or "").split())
                inner = _LABEL_RE.match(candidate)
                if inner:
                    candidate = " ".join((inner.group("value") or "").split())
                if not candidate or _NOT_A_NAME.match(candidate) \
                        or not re.search(r"[^\W_]", candidate):
                    continue
                if _HEADING_LIKE.match(candidate):
                    break
                value = candidate
                break
        value = value.strip(" :–-")
        if value and not _NOT_A_NAME.match(value):
            return value[:120]
    return None


def search(client, query: str, limit: int = 10) -> list[Candidate]:
    """Products whose name matches, newest first. A GET, and nothing else."""
    page = client.get("/library", q=query, page_size=limit, page=1)
    rows = (page or {}).get("results") or []
    out = []
    for row in rows:
        product_id = row.get("primary_product_id")
        if not product_id:
            continue
        regulations = row.get("regulations") or []
        out.append(Candidate(
            product_id=int(product_id), name=row.get("product_name") or "",
            regulation=(regulations[0].get("regulation")
                        if regulations and isinstance(regulations[0], dict)
                        else None),
            updated_at=row.get("updated_at") or row.get("created_at") or ""))
    return out


def rank(candidates: list[Candidate], name: str,
         regulation: str | None = None) -> list[Candidate]:
    """Best first: the same name, then the same regulation, then the newest.

    A person choosing between products should not have to scan for the obvious
    one, and the order is an opinion rather than a decision - nothing is picked
    on their behalf unless exactly one candidate is left.
    """
    wanted = normalised(name)

    def key(candidate: Candidate) -> tuple:
        return (
            0 if normalised(candidate.name) == wanted else 1,
            0 if regulation and candidate.regulation == regulation else 1,
            # Newest first, so a reversed string sort puts recent dates on top.
            [-ord(c) for c in candidate.updated_at] or [0],
        )

    return sorted(candidates, key=key)


def match_product(client, file_name: str, lines,
                  regulation: str | None = None) -> Match:
    """Find the application product this sheet is, if it is one.

    The file name is tried first and only when it names a product that exists:
    an application download carries its own id, which is better evidence than
    any name. Otherwise the product name from Section 1 is searched for. One
    hit is a match; several are candidates for a person to choose between; none
    means this is somebody else's sheet, which is not a problem to report.
    """
    name = product_name_in(lines)
    product_id = product_id_in_file_name(file_name)

    if product_id is not None:
        detail = client.product(product_id)
        if detail and detail.get("product_name"):
            return Match(state="matched", product_id=product_id,
                         name=detail["product_name"],
                         evidence=f"the file name carries product {product_id}",
                         searched_for=str(product_id))

    if not name:
        return Match(state="none",
                     evidence="no product name found in Section 1")

    candidates = rank(search(client, name), name, regulation)
    exact = [c for c in candidates if normalised(c.name) == normalised(name)]
    if len(exact) == 1:
        candidates = exact
    if len(candidates) == 1:
        only = candidates[0]
        return Match(state="matched", product_id=only.product_id, name=only.name,
                     evidence=f"one product is named {name!r}", searched_for=name)
    if candidates:
        return Match(state="ambiguous", candidates=candidates,
                     evidence=f"{len(candidates)} products match {name!r}",
                     searched_for=name)
    return Match(state="none", searched_for=name,
                 evidence=f"no product named {name!r}")
