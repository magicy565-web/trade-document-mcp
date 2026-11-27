from typing import Annotated
from pydantic import BaseModel, ConfigDict, StringConstraints

Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


from pydantic import AfterValidator
from iso4217 import Currency as ISOCurrency
from iso3166 import countries


def minor_units(code):
    try:
        digits = ISOCurrency[code].exponent
    except KeyError as e:
        raise ValueError("Unknown ISO 4217 currency") from e
    if digits is None:
        raise ValueError("A settlement currency with defined minor unit is required")
    return digits


def currency_code(code):
    minor_units(code)
    return code


def country_code(code):
    try:
        countries.get(code)
    except KeyError as e:
        raise ValueError("Unknown ISO 3166 country") from e
    return code


Currency = Annotated[
    str, StringConstraints(pattern=r"^[A-Z]{3}$"), AfterValidator(currency_code)
]
Country = Annotated[
    str, StringConstraints(pattern=r"^[A-Z]{2}$"), AfterValidator(country_code)
]
