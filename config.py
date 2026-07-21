"""PivotDesk — shared constants.

Kept in its own module so the data layer and the indicator layer can agree
on the market clock without depending on each other.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dt.time(9, 15)
MARKET_CLOSE = dt.time(15, 30)
