"""High Court neutral-citation prefixes (the middle segment of `YYYY:PREFIX:NNNN`).

There is no consolidated official list. Entries marked confirmed were seen in published judgments or
court circulars; the rest are best-effort and the grammar accepts any well-formed prefix regardless,
so an unknown prefix resolves through Indian Kanoon rather than being rejected.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HighCourt:
    prefix: str
    court: str
    bench: str | None = None
    confirmed: bool = False


HC_PREFIXES: dict[str, HighCourt] = {
    hc.prefix: hc
    for hc in [
        HighCourt("DHC", "Delhi High Court", confirmed=True),
        HighCourt("KHC", "Karnataka High Court", "Bengaluru", confirmed=True),
        HighCourt("KHC-D", "Karnataka High Court", "Dharwad", confirmed=True),
        HighCourt("KHC-K", "Karnataka High Court", "Kalaburagi", confirmed=True),
        HighCourt("MHC", "Madras High Court", confirmed=True),
        HighCourt("AHC", "Allahabad High Court", "Allahabad"),
        HighCourt("AHC-LKO", "Allahabad High Court", "Lucknow"),
        HighCourt("APHC", "Andhra Pradesh High Court"),
        HighCourt("BHC-AS", "Bombay High Court", "Appellate Side"),
        HighCourt("BHC-OS", "Bombay High Court", "Original Side"),
        HighCourt("BHC-NAG", "Bombay High Court", "Nagpur"),
        HighCourt("BHC-AUG", "Bombay High Court", "Aurangabad"),
        HighCourt("BHC-GOA", "Bombay High Court", "Goa"),
        HighCourt("CGHC", "Chhattisgarh High Court"),
        HighCourt("CHC", "Calcutta High Court"),
        HighCourt("GAHC", "Gauhati High Court"),
        HighCourt("GUJHC", "Gujarat High Court"),
        HighCourt("HHC", "Himachal Pradesh High Court"),
        HighCourt("JHHC", "Jharkhand High Court"),
        HighCourt("JKLHC", "High Court of Jammu and Kashmir and Ladakh"),
        HighCourt("KER", "Kerala High Court"),
        HighCourt("MPHC-JBP", "Madhya Pradesh High Court", "Jabalpur"),
        HighCourt("MPHC-IND", "Madhya Pradesh High Court", "Indore"),
        HighCourt("MPHC-GWL", "Madhya Pradesh High Court", "Gwalior"),
        HighCourt("MEGHC", "Meghalaya High Court"),
        HighCourt("MNHC", "Manipur High Court"),
        HighCourt("OHC", "Orissa High Court"),
        HighCourt("PHHC", "Punjab and Haryana High Court"),
        HighCourt("PHC", "Patna High Court"),
        HighCourt("RJ-JD", "Rajasthan High Court", "Jodhpur"),
        HighCourt("RJ-JP", "Rajasthan High Court", "Jaipur"),
        HighCourt("SHC", "Sikkim High Court"),
        HighCourt("TSHC", "Telangana High Court"),
        HighCourt("TRHC", "Tripura High Court"),
        HighCourt("UHC", "Uttarakhand High Court"),
    ]
}


def court_for_prefix(prefix: str) -> HighCourt | None:
    return HC_PREFIXES.get(prefix.upper())
