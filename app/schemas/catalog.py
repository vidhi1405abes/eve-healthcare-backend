from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Price = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2, examples=["499.00"])]


class CentreCreate(BaseModel):
    name: ShortText
    location: ShortText

    model_config = ConfigDict(json_schema_extra={"examples": [{"name": "Apollo Diagnostics", "location": "Delhi"}]})


class CentreUpdate(BaseModel):
    name: ShortText | None = None
    location: ShortText | None = None


class CentreOut(BaseModel):
    id: int
    name: str
    location: str

    model_config = ConfigDict(from_attributes=True)


class CentreTestOut(BaseModel):
    test_id: int
    name: str
    description: str | None
    price: Decimal


class CentreDetailOut(CentreOut):
    tests: list[CentreTestOut]


class DiagnosticTestCreate(BaseModel):
    name: ShortText
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"name": "Lipid Profile", "description": "Cholesterol and triglycerides"}]}
    )


class DiagnosticTestUpdate(BaseModel):
    name: ShortText | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None


class DiagnosticTestOut(BaseModel):
    id: int
    name: str
    description: str | None

    model_config = ConfigDict(from_attributes=True)


class PriceSet(BaseModel):
    price: Price

    model_config = ConfigDict(json_schema_extra={"examples": [{"price": "499.00"}]})


class CentrePriceOut(BaseModel):
    centre_id: int
    test_id: int
    price: Decimal
