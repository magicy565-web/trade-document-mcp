from .types import Country
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import Field
from .types import Model, Text


class Address(Model):
    street: Text
    city: Text
    country: Country
    postal_code: Text | None = None
    region: Text | None = None

    def display(self):
        return ", ".join(
            v
            for v in (
                self.street,
                self.city,
                self.region,
                self.postal_code,
                self.country,
            )
            if v
        )


class Party(Model):
    role: Literal["seller", "buyer", "ship_to", "importer"]
    legal_name: Text
    address: Address
    tax_id_type: Text | None = None
    tax_id: Text | None = None

    def display(self):
        return " | ".join(
            v
            for v in (
                self.legal_name,
                self.address.display(),
                self.tax_id_type,
                self.tax_id,
            )
            if v
        )


class Measure(Model):
    amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=5)]
    unit: Literal["kg", "g", "lb", "oz", "m", "cm", "mm", "in", "ft", "m2", "ft2"]


class Conversion(Model):
    amount: Decimal
    unit: str
    factor: Decimal
    base_amount: Decimal


FACTORS = {
    "kg": ("mass", "1"),
    "g": ("mass", "0.001"),
    "lb": ("mass", "0.45359237"),
    "oz": ("mass", "0.028349523125"),
    "m": ("length", "1"),
    "cm": ("length", "0.01"),
    "mm": ("length", "0.001"),
    "in": ("length", "0.0254"),
    "ft": ("length", "0.3048"),
    "m2": ("area", "1"),
    "ft2": ("area", "0.09290304"),
}


def convert_measure(value: Measure, to_unit: Text) -> Conversion:
    src_dimension, src = FACTORS[value.unit]
    if to_unit not in FACTORS or FACTORS[to_unit][0] != src_dimension:
        raise ValueError("Incompatible measurement units")
    base = value.amount * Decimal(src)
    target = Decimal(FACTORS[to_unit][1])
    return Conversion(
        amount=base / target,
        unit=to_unit,
        factor=Decimal(src) / target,
        base_amount=base,
    )
