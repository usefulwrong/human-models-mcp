"""Reproduce the exact neutral nonimpaired CSV from the pinned publisher XML."""

import csv
import hashlib
import io
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "benchmarks/nichols2016_wrist"


def main():
    article = (FOLDER / "article.xml").read_bytes()
    assert hashlib.sha256(article).hexdigest() == "babc83e6fb84423a807b980f2fed423ea0bb924310e707221c66350f5b2fa483"
    table = next(item for item in ET.fromstring(article).findall(".//table-wrap") if item.get("id") == "pone.0157346.t002")
    rows = []
    for tr in table.findall(".//tbody/tr")[:5]:
        cells = ["".join(item.itertext()).strip() for item in tr.findall("td")]
        for axis, index in (("extension", 1), ("ulnar_deviation", 4)):
            mean, sd = map(float, re.fullmatch(r"(-?[\d.]+) \(([\d.]+)\)", cells[index]).groups())
            rows.append({"muscle": cells[0], "axis": axis, "mean_cm": mean, "sd_cm": sd,
                         "mean_m": mean*.01, "sd_m": sd*.01, "n_specimens": 8})
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    data = output.getvalue().encode()
    assert data == (FOLDER / "reference.csv").read_bytes()
    print("Publisher Table 2 extraction reproduced: 10 observations; SHA256 " + hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    main()
