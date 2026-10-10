"""Saudi cities, districts and road-distance approximations (public approximate coordinates).

Coordinates are approximate public city and district centres, used only to give the synthetic network
plausible distances. Road distance is haversine distance times a road factor; it is not road geometry
from a routing service, and no claim is made about actual SPL routes or schedules.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class City:
    code: str
    name: str
    name_ar: str
    lat: float
    lng: float
    region: str            # central / west / east
    destination_weight: float
    origin_weight: float


# Demand is weighted toward Riyadh, Jeddah and the Eastern Province (synthetic scenario weights).
CITIES = (
    City("RUH", "Riyadh", "الرياض", 24.7136, 46.6753, "central", .30, .40),
    City("JED", "Jeddah", "جدة", 21.4858, 39.1925, "west", .19, .25),
    City("MAK", "Makkah", "مكة المكرمة", 21.3891, 39.8579, "west", .07, .04),
    City("MED", "Madinah", "المدينة المنورة", 24.5247, 39.5692, "west", .06, .04),
    City("DMM", "Dammam", "الدمام", 26.4207, 50.0888, "east", .09, .12),
    City("KHB", "Khobar", "الخبر", 26.2172, 50.1971, "east", .07, .05),
    City("DHA", "Dhahran", "الظهران", 26.2885, 50.1140, "east", .03, .02),
    City("HOF", "Al Ahsa (Hofuf)", "الأحساء (الهفوف)", 25.3833, 49.5865, "east", .04, .02),
    City("QSM", "Buraydah (Qassim)", "بريدة (القصيم)", 26.3260, 43.9750, "central", .04, .02),
    City("JUB", "Jubail", "الجبيل", 27.0046, 49.6460, "east", .03, .02),
    City("TIF", "Taif", "الطائف", 21.2703, 40.4158, "west", .03, .01),
    City("TUU", "Tabuk", "تبوك", 28.3838, 36.5550, "west", .025, .005),
    City("AHB", "Abha", "أبها", 18.2164, 42.5053, "west", .025, .005),
)
CITY = {c.code: c for c in CITIES}
REGION_HUB = {"central": "RUH", "west": "JED", "east": "DMM"}

# (English, Arabic, lat, lng) public district names with approximate centres; smaller cities use
# generic compass districts around the centre.
DISTRICTS = {
    "RUH": (("Al Olaya", "العليا", 24.6900, 46.6850), ("Al Malqa", "الملقا", 24.8100, 46.6100),
            ("An Nakheel", "النخيل", 24.7480, 46.6370), ("An Naseem", "النسيم", 24.7380, 46.8200),
            ("Al Aziziyah", "العزيزية", 24.5960, 46.7600), ("Ar Rawdah", "الروضة", 24.7350, 46.7700),
            ("Al Yasmin", "الياسمين", 24.8250, 46.6500), ("As Suwaidi", "السويدي", 24.5850, 46.6500),
            ("Hittin", "حطين", 24.7650, 46.6000), ("Ad Dar Al Baida", "الدار البيضاء", 24.5600, 46.8000)),
    "JED": (("Al Hamra", "الحمراء", 21.5100, 39.1700), ("Ar Rawdah", "الروضة", 21.5600, 39.1550),
            ("As Safa", "الصفا", 21.5800, 39.2100), ("Az Zahra", "الزهراء", 21.6000, 39.1400),
            ("Al Balad", "البلد", 21.4850, 39.1860), ("Al Marwah", "المروة", 21.6200, 39.2100),
            ("An Naeem", "النعيم", 21.6250, 39.1550), ("Al Aziziyah", "العزيزية", 21.5500, 39.2000)),
    "DMM": (("Al Faisaliyah", "الفيصلية", 26.4100, 50.0600), ("Ash Shati", "الشاطئ", 26.4600, 50.1100),
            ("Al Mazruiyah", "المزروعية", 26.4300, 50.0800), ("An Nur", "النور", 26.3900, 50.0300),
            ("Al Badiyah", "البادية", 26.4250, 50.0950)),
    "KHB": (("Al Aqrabiyah", "العقربية", 26.2900, 50.2000), ("Al Khobar Ash Shamaliyah", "الخبر الشمالية", 26.2950, 50.2150),
            ("Ar Rakah", "الراكة", 26.3350, 50.1950), ("Al Ulaya", "العليا", 26.2550, 50.2050)),
    "MAK": (("Al Aziziyah", "العزيزية", 21.4000, 39.8800), ("Al Awali", "العوالي", 21.3700, 39.8800),
            ("Ash Sharai", "الشرائع", 21.4500, 39.9200)),
    "MED": (("Quba", "قباء", 24.4400, 39.6200), ("Al Aziziyah", "العزيزية", 24.4500, 39.5900),
            ("Al Khalidiyah", "الخالدية", 24.5000, 39.5800)),
}
_COMPASS = (("Central", "الوسط", 0.0, 0.0), ("North", "الشمال", .035, 0.0), ("South", "الجنوب", -.035, 0.0),
            ("East", "الشرق", 0.0, .035), ("West", "الغرب", 0.0, -.035))


def districts(code: str):
    if code in DISTRICTS:
        return DISTRICTS[code]
    city = CITY[code]
    return tuple((n, a, round(city.lat + dlat, 4), round(city.lng + dlng, 4)) for n, a, dlat, dlng in _COMPASS)


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))


# Intercity roads are not straight lines; urban driving adds more detour.
ROAD_FACTOR_INTERCITY = 1.18
ROAD_FACTOR_URBAN = 1.35


def road_km(lat1, lng1, lat2, lng2, *, urban=False) -> float:
    return haversine_km(lat1, lng1, lat2, lng2) * (ROAD_FACTOR_URBAN if urban else ROAD_FACTOR_INTERCITY)


def offset_point(lat, lng, north_km, east_km):
    return (lat + north_km / 110.574, lng + east_km / (111.320 * math.cos(math.radians(lat))))


def interpolate(a, b, fraction):
    return (a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction)
