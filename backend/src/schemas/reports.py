from pydantic import BaseModel, Field, model_validator

MONTH_PATTERN = r"^\d{4}-\d{2}$"


class ReportRequest(BaseModel):
    month: str = Field(pattern=MONTH_PATTERN)
    department: str = Field(min_length=2, max_length=80)


class RosterCreate(BaseModel):
    department: str = Field(min_length=2, max_length=80)
    staff_no: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=80)


class ClaimRequest(BaseModel):
    department: str = Field(min_length=2, max_length=80)
    month: str = Field(pattern=MONTH_PATTERN)
    ta_id: int = Field(gt=0)
    roster_id: int = Field(gt=0)


class ClaimRevokeRequest(BaseModel):
    department: str = Field(min_length=2, max_length=80)
    month: str = Field(pattern=MONTH_PATTERN)
    # 客户端带上读到的版本号，重试时不会误伤撤销后补认的新归属。
    expected_version: int | None = Field(default=None, ge=1)
    reason: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _no_blank_department(self):
        if not self.department.strip():
            raise ValueError("department 不能为空")
        return self
