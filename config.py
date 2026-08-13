from datetime import date, datetime


KEYWORDS = [
    "vistoria",
    "vistoria veicular",
    "vistoria de identificação veicular",
    "vistoria cautelar",
    "ecv",
]


DATE = date.today().isoformat()


def date_as_br(value: str = DATE) -> str:
    return datetime.fromisoformat(value).strftime("%d/%m/%Y")


def date_parts_br(value: str = DATE) -> tuple[str, str, str]:
    return tuple(date_as_br(value).split("/"))
