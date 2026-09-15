from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator


class LineInput(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100)


class OrderInput(BaseModel):
    external_id: str = Field(min_length=1, max_length=100)
    customer_email: str = Field(min_length=3, max_length=254)
    # Supplied by a trusted integration, never by a public checkout user.
    risk_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    payment_method: Literal["cod", "prepaid"] = "cod"
    preferred_brands: list[str] = Field(default_factory=list, max_length=20)
    items: list[LineInput] = Field(min_length=1, max_length=50)

    @field_validator("customer_email")
    @classmethod
    def email_shape(cls, value):
        if "@" not in value or any(c in value for c in "\r\n "):
            raise ValueError("Use an email address without whitespace")
        return value

    @model_validator(mode="after")
    def unique_products(self):
        ids = [x.product_id for x in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Combine duplicate products into a single line")
        return self


class AuditDecision(BaseModel):
    decision: Literal["approve", "reject"]


class CustomerReply(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    decision: Literal["accept", "reject"]


class CustomerCancel(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=200)
    role: Literal["admin", "auditor", "viewer"] = "viewer"

    @field_validator("email")
    @classmethod
    def email_shape(cls, value):
        if "@" not in value or any(c in value for c in "\r\n "):
            raise ValueError("Use an email address without whitespace")
        return value


class UserLogin(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
