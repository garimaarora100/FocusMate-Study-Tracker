"""Pydantic request schemas: all input validation happens here before touching the DB."""
from datetime import date, time
from typing import Literal

from pydantic import BaseModel, Field, field_validator

CATEGORIES = ("STUDY", "SLEEP", "FOOD", "EXERCISE", "ENTERTAINMENT", "TRAVEL", "OTHER")
ActivityType = Literal["STUDY", "SLEEP", "FOOD", "EXERCISE", "ENTERTAINMENT", "TRAVEL", "OTHER"]


def clean_name(value: str) -> str:
    """Trim spaces and refuse names that are blank after trimming."""
    value = value.strip()
    if not value:
        raise ValueError("Activity name must not be blank.")
    return value


class StartSessionRequest(BaseModel):
    activity_name: str = Field("Study Session", min_length=1, max_length=100)

    @field_validator("activity_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return clean_name(value)


class ActivityRequest(BaseModel):
    """date + start_time + end_time. If end_time < start_time the activity ends the NEXT day."""
    activity_name: str = Field(..., min_length=1, max_length=100)
    activity_type: ActivityType
    activity_date: date
    start_time: time
    end_time: time

    @field_validator("activity_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return clean_name(value)

    @field_validator("activity_type", mode="before")
    @classmethod
    def normalise_type(cls, value):
        """Accept 'study', ' Study ' etc.; the Literal check then enforces the allowed list."""
        return value.strip().upper() if isinstance(value, str) else value
